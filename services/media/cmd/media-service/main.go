package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

type endpointSnapshot struct {
	RequestsTotal   int64  `json:"requests_total"`
	SuccessTotal    int64  `json:"success_total"`
	ErrorTotal      int64  `json:"error_total"`
	LastLatencyMs   int64  `json:"last_latency_ms,omitempty"`
	LastSuccessAt   string `json:"last_success_at,omitempty"`
	LastErrorAt     string `json:"last_error_at,omitempty"`
	LastErrorDetail string `json:"last_error_detail,omitempty"`
}

type endpointMetrics struct {
	mu              sync.Mutex
	requestsTotal   int64
	successTotal    int64
	errorTotal      int64
	lastSuccessAt   time.Time
	lastErrorAt     time.Time
	lastLatencyMs   int64
	lastErrorDetail string
}

func (m *endpointMetrics) record(latency time.Duration, err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.requestsTotal++
	m.lastLatencyMs = latency.Milliseconds()
	now := time.Now().UTC()
	if err == nil {
		m.successTotal++
		m.lastSuccessAt = now
	} else {
		m.errorTotal++
		m.lastErrorAt = now
		detail := err.Error()
		if len(detail) > 200 {
			detail = detail[:200]
		}
		m.lastErrorDetail = detail
	}
}

func (m *endpointMetrics) snapshot() endpointSnapshot {
	m.mu.Lock()
	defer m.mu.Unlock()
	snap := endpointSnapshot{
		RequestsTotal:   m.requestsTotal,
		SuccessTotal:    m.successTotal,
		ErrorTotal:      m.errorTotal,
		LastLatencyMs:   m.lastLatencyMs,
		LastErrorDetail: m.lastErrorDetail,
	}
	if !m.lastSuccessAt.IsZero() {
		snap.LastSuccessAt = m.lastSuccessAt.Format(time.RFC3339)
	}
	if !m.lastErrorAt.IsZero() {
		snap.LastErrorAt = m.lastErrorAt.Format(time.RFC3339)
	}
	return snap
}

const (
	defaultListenAddr      = ":8080"
	defaultLanguage        = "en"
	maxTTSChars            = 4000
	groqMaxSegmentChars    = 200
	groqTTSModel           = "canopylabs/orpheus-v1-english"
	groqTTSVoice           = "hannah"
	groqSTTModel           = "whisper-large-v3-turbo"
	defaultElevenLabsModel = "eleven_flash_v2_5"
	defaultElevenLabsVoice = "JBFqnCBsd6RMkjVDRZzb"
	maxSTTBytes            = 25 * 1024 * 1024
	defaultRecordingDir    = "/app/storage/recordings"
)

var allowedRecordingTypes = map[string]string{
	"video/mp4":  ".mp4",
	"video/webm": ".webm",
}

type config struct {
	GroqAPIKey          string
	ElevenLabsAPIKey    string
	TTSProvider         string
	TTSFallbackProvider string
	ElevenLabsVoiceID   string
	ElevenLabsModel     string
	RecordingDir        string
	MaxRecordingBytes   int64
}

type server struct {
	cfg       config
	client    *http.Client
	tts       endpointMetrics
	stt       endpointMetrics
	recording endpointMetrics
}

type apiError struct {
	status int
	detail string
}

func (e apiError) Error() string {
	return e.detail
}

type ttsRequest struct {
	Text     string `json:"text"`
	Language string `json:"language"`
}

type ttsResult struct {
	audio     []byte
	mediaType string
	provider  string
	model     string
}

type providerStatus struct {
	Provider       string `json:"provider"`
	Configured     bool   `json:"configured"`
	RequiredAPIKey string `json:"required_api_key"`
	Model          string `json:"model,omitempty"`
}

type statusResponse struct {
	Service                     string           `json:"service"`
	TTSProvider                 string           `json:"tts_provider"`
	TTSFallbackProvider         string           `json:"tts_fallback_provider"`
	TTSProviderChain            []string         `json:"tts_provider_chain"`
	TTSProviders                []providerStatus `json:"tts_providers"`
	STTProvider                 string           `json:"stt_provider"`
	STTConfigured               bool             `json:"stt_configured"`
	STTRequiredAPIKey           string           `json:"stt_required_api_key"`
	STTModel                    string           `json:"stt_model"`
	MaxTTSChars                 int              `json:"max_tts_chars"`
	MaxSTTBytes                 int              `json:"max_stt_bytes"`
	MaxRecordingBytes           int64            `json:"max_recording_bytes"`
	MaxRecordingSizeMB          int64            `json:"max_recording_size_mb"`
	RecordingStorageConfigured  bool             `json:"recording_storage_configured"`
	RecordingStorageWritable    bool             `json:"recording_storage_writable"`
	RecordingAllowedContentType []string         `json:"recording_allowed_content_types"`
	TTS                         endpointSnapshot `json:"tts"`
	STT                         endpointSnapshot `json:"stt"`
	Recording                   endpointSnapshot `json:"recording_upload"`
}

func main() {
	cfg := config{
		GroqAPIKey:          os.Getenv("GROQ_API_KEY"),
		ElevenLabsAPIKey:    os.Getenv("ELEVENLABS_API_KEY"),
		TTSProvider:         envOrDefault("TTS_PROVIDER", "groq"),
		TTSFallbackProvider: envOrDefault("TTS_FALLBACK_PROVIDER", "groq"),
		ElevenLabsVoiceID:   envOrDefault("ELEVENLABS_VOICE_ID", defaultElevenLabsVoice),
		ElevenLabsModel:     envOrDefault("ELEVENLABS_TTS_MODEL", defaultElevenLabsModel),
		RecordingDir:        envOrDefault("RECORDING_STORAGE_DIR", defaultRecordingDir),
		MaxRecordingBytes:   envInt64OrDefault("MAX_RECORDING_SIZE_MB", 250) * 1024 * 1024,
	}
	srv := &server{
		cfg: cfg,
		client: &http.Client{
			Timeout: 60 * time.Second,
		},
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", srv.handleHealth)
	mux.HandleFunc("GET /v1/status", srv.handleStatus)
	mux.HandleFunc("POST /v1/tts", srv.handleTTS)
	mux.HandleFunc("POST /v1/stt", srv.handleSTT)
	mux.HandleFunc("POST /v1/recordings/{recording_id}", srv.handleRecordingUpload)

	addr := envOrDefault("MEDIA_SERVICE_ADDR", defaultListenAddr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		panic(err)
	}
}

func (s *server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":                     "ok",
		"service":                    "media-service",
		"recording_storage_writable": s.recordingStorageWritable(),
	})
}

func (s *server) handleStatus(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, s.status())
}

func (s *server) handleTTS(w http.ResponseWriter, r *http.Request) {
	var payload ttsRequest
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid JSON body")
		return
	}

	start := time.Now()
	result, err := s.synthesize(r.Context(), payload.Text, payload.Language)
	s.tts.record(time.Since(start), err)
	if err != nil {
		writeAPIError(w, err)
		return
	}

	w.Header().Set("Content-Type", result.mediaType)
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-TTS-Provider", result.provider)
	w.Header().Set("X-TTS-Model", result.model)
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(result.audio)
}

func (s *server) handleSTT(w http.ResponseWriter, r *http.Request) {
	if s.cfg.GroqAPIKey == "" {
		writeError(w, http.StatusServiceUnavailable, "STT service not configured (no GROQ_API_KEY)")
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, maxSTTBytes+1)
	if err := r.ParseMultipartForm(maxSTTBytes + 1024*1024); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid multipart audio upload")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "Missing audio file")
		return
	}
	defer file.Close()

	audio, err := io.ReadAll(io.LimitReader(file, maxSTTBytes+1))
	if err != nil {
		writeError(w, http.StatusBadRequest, "Failed to read audio file")
		return
	}
	if len(audio) == 0 {
		writeError(w, http.StatusBadRequest, "Empty audio file")
		return
	}
	if len(audio) > maxSTTBytes {
		writeError(w, http.StatusRequestEntityTooLarge, "Audio file too large (max 25 MB)")
		return
	}

	start := time.Now()
	text, err := s.transcribeWithGroq(r.Context(), audio, header)
	s.stt.record(time.Since(start), err)
	if err != nil {
		writeAPIError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"text": text})
}

func (s *server) handleRecordingUpload(w http.ResponseWriter, r *http.Request) {
	recordingID := strings.TrimSpace(r.PathValue("recording_id"))
	if !isSafeRecordingID(recordingID) {
		writeError(w, http.StatusBadRequest, "Invalid recording id")
		return
	}

	contentType := strings.ToLower(strings.TrimSpace(strings.Split(r.Header.Get("Content-Type"), ";")[0]))
	extension, ok := allowedRecordingTypes[contentType]
	if !ok {
		writeError(w, http.StatusUnsupportedMediaType, "Unsupported recording format. Allowed: video/webm, video/mp4.")
		return
	}

	recStart := time.Now()
	var recErr error
	defer func() { s.recording.record(time.Since(recStart), recErr) }()

	if err := os.MkdirAll(s.cfg.RecordingDir, 0o755); err != nil {
		recErr = err
		writeError(w, http.StatusInternalServerError, "Failed to prepare recording storage")
		return
	}

	dest := s.cfg.RecordingDir + string(os.PathSeparator) + recordingID + extension
	temp := dest + ".tmp"
	out, err := os.Create(temp)
	if err != nil {
		recErr = err
		writeError(w, http.StatusInternalServerError, "Failed to create recording file")
		return
	}
	defer out.Close()

	reader := http.MaxBytesReader(w, r.Body, s.cfg.MaxRecordingBytes+1)
	written, err := io.Copy(out, reader)
	if err != nil {
		_ = os.Remove(temp)
		recErr = err
		var maxBytesErr *http.MaxBytesError
		if errors.As(err, &maxBytesErr) {
			writeError(w, http.StatusRequestEntityTooLarge, fmt.Sprintf("Recording exceeds maximum allowed size of %d MB.", s.cfg.MaxRecordingBytes/1024/1024))
			return
		}
		writeError(w, http.StatusBadRequest, "Failed to read recording upload")
		return
	}
	if written > s.cfg.MaxRecordingBytes {
		_ = os.Remove(temp)
		recErr = fmt.Errorf("recording too large: %d bytes", written)
		writeError(w, http.StatusRequestEntityTooLarge, fmt.Sprintf("Recording exceeds maximum allowed size of %d MB.", s.cfg.MaxRecordingBytes/1024/1024))
		return
	}
	if err := out.Close(); err != nil {
		_ = os.Remove(temp)
		recErr = err
		writeError(w, http.StatusInternalServerError, "Failed to finalize recording file")
		return
	}
	if err := os.Rename(temp, dest); err != nil {
		_ = os.Remove(temp)
		recErr = err
		writeError(w, http.StatusInternalServerError, "Failed to store recording file")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"path":       dest,
		"bytes":      written,
		"media_type": contentType,
	})
}

func (s *server) status() statusResponse {
	return statusResponse{
		Service:                     "media-service",
		TTSProvider:                 normalizeProviderName(s.cfg.TTSProvider),
		TTSFallbackProvider:         normalizeProviderName(s.cfg.TTSFallbackProvider),
		TTSProviderChain:            providerChain(s.cfg.TTSProvider, s.cfg.TTSFallbackProvider),
		TTSProviders:                s.ttsProviderStatuses(),
		STTProvider:                 "groq",
		STTConfigured:               strings.TrimSpace(s.cfg.GroqAPIKey) != "",
		STTRequiredAPIKey:           "GROQ_API_KEY",
		STTModel:                    groqSTTModel,
		MaxTTSChars:                 maxTTSChars,
		MaxSTTBytes:                 maxSTTBytes,
		MaxRecordingBytes:           s.cfg.MaxRecordingBytes,
		MaxRecordingSizeMB:          s.cfg.MaxRecordingBytes / 1024 / 1024,
		RecordingStorageConfigured:  strings.TrimSpace(s.cfg.RecordingDir) != "",
		RecordingStorageWritable:    s.recordingStorageWritable(),
		RecordingAllowedContentType: allowedRecordingContentTypes(),
		TTS:                         s.tts.snapshot(),
		STT:                         s.stt.snapshot(),
		Recording:                   s.recording.snapshot(),
	}
}

func (s *server) ttsProviderStatuses() []providerStatus {
	return []providerStatus{
		{
			Provider:       "elevenlabs",
			Configured:     strings.TrimSpace(s.cfg.ElevenLabsAPIKey) != "",
			RequiredAPIKey: "ELEVENLABS_API_KEY",
			Model:          s.cfg.ElevenLabsModel,
		},
		{
			Provider:       "groq",
			Configured:     strings.TrimSpace(s.cfg.GroqAPIKey) != "",
			RequiredAPIKey: "GROQ_API_KEY",
			Model:          groqTTSModel,
		},
	}
}

func (s *server) recordingStorageWritable() bool {
	if strings.TrimSpace(s.cfg.RecordingDir) == "" {
		return false
	}
	if err := os.MkdirAll(s.cfg.RecordingDir, 0o755); err != nil {
		return false
	}
	tmp, err := os.CreateTemp(s.cfg.RecordingDir, ".media-service-health-*")
	if err != nil {
		return false
	}
	name := tmp.Name()
	if err := tmp.Close(); err != nil {
		_ = os.Remove(name)
		return false
	}
	return os.Remove(name) == nil
}

func (s *server) synthesize(ctx context.Context, text string, language string) (ttsResult, error) {
	normalizedText, err := normalizeTTSText(text)
	if err != nil {
		return ttsResult{}, apiError{status: http.StatusUnprocessableEntity, detail: err.Error()}
	}
	normalizedLanguage := normalizeLanguage(language)

	var errs []error
	for _, provider := range providerChain(s.cfg.TTSProvider, s.cfg.TTSFallbackProvider) {
		var result ttsResult
		var err error
		switch provider {
		case "groq":
			result, err = s.synthesizeGroq(ctx, normalizedText, normalizedLanguage)
		case "elevenlabs":
			result, err = s.synthesizeElevenLabs(ctx, normalizedText)
		default:
			err = apiError{status: http.StatusServiceUnavailable, detail: fmt.Sprintf("Unsupported TTS provider '%s'", provider)}
		}
		if err == nil {
			return result, nil
		}
		errs = append(errs, err)
	}

	return ttsResult{}, selectProviderError(errs)
}

func (s *server) synthesizeGroq(ctx context.Context, text string, language string) (ttsResult, error) {
	if s.cfg.GroqAPIKey == "" {
		return ttsResult{}, apiError{status: http.StatusServiceUnavailable, detail: "Groq TTS not configured (no GROQ_API_KEY)"}
	}
	if language != "en" {
		return ttsResult{}, apiError{status: http.StatusUnprocessableEntity, detail: fmt.Sprintf("Groq TTS does not support language '%s'", language)}
	}

	var chunks [][]byte
	for _, chunk := range chunkText(text, groqMaxSegmentChars) {
		body, _ := json.Marshal(map[string]string{
			"model":           groqTTSModel,
			"voice":           groqTTSVoice,
			"input":           chunk,
			"response_format": "wav",
		})
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://api.groq.com/openai/v1/audio/speech", bytes.NewReader(body))
		if err != nil {
			return ttsResult{}, apiError{status: http.StatusBadGateway, detail: err.Error()}
		}
		req.Header.Set("Authorization", "Bearer "+s.cfg.GroqAPIKey)
		req.Header.Set("Content-Type", "application/json")

		resp, err := s.client.Do(req)
		if err != nil {
			return ttsResult{}, apiError{status: http.StatusServiceUnavailable, detail: "Groq TTS request failed: " + err.Error()}
		}
		audio, readErr := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		if readErr != nil {
			return ttsResult{}, apiError{status: http.StatusBadGateway, detail: "Failed to read Groq TTS response"}
		}
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return ttsResult{}, upstreamError(resp.StatusCode, "Groq TTS failed", audio)
		}
		chunks = append(chunks, audio)
	}

	audio, err := mergeWAVChunks(chunks)
	if err != nil {
		return ttsResult{}, apiError{status: http.StatusBadGateway, detail: err.Error()}
	}
	return ttsResult{audio: audio, mediaType: "audio/wav", provider: "groq", model: groqTTSModel}, nil
}

func (s *server) synthesizeElevenLabs(ctx context.Context, text string) (ttsResult, error) {
	if s.cfg.ElevenLabsAPIKey == "" {
		return ttsResult{}, apiError{status: http.StatusServiceUnavailable, detail: "ElevenLabs TTS not configured (no ELEVENLABS_API_KEY)"}
	}
	body, _ := json.Marshal(map[string]string{
		"text":     text,
		"model_id": s.cfg.ElevenLabsModel,
	})
	url := "https://api.elevenlabs.io/v1/text-to-speech/" + s.cfg.ElevenLabsVoiceID
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return ttsResult{}, apiError{status: http.StatusBadGateway, detail: err.Error()}
	}
	req.Header.Set("xi-api-key", s.cfg.ElevenLabsAPIKey)
	req.Header.Set("Accept", "audio/mpeg")
	req.Header.Set("Content-Type", "application/json")

	resp, err := s.client.Do(req)
	if err != nil {
		return ttsResult{}, apiError{status: http.StatusServiceUnavailable, detail: "ElevenLabs TTS request failed: " + err.Error()}
	}
	audio, readErr := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if readErr != nil {
		return ttsResult{}, apiError{status: http.StatusBadGateway, detail: "Failed to read ElevenLabs TTS response"}
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return ttsResult{}, upstreamError(resp.StatusCode, "ElevenLabs TTS failed", audio)
	}

	mediaType := resp.Header.Get("Content-Type")
	if mediaType == "" {
		mediaType = "audio/mpeg"
	}
	if idx := strings.Index(mediaType, ";"); idx >= 0 {
		mediaType = mediaType[:idx]
	}
	return ttsResult{audio: audio, mediaType: mediaType, provider: "elevenlabs", model: s.cfg.ElevenLabsModel}, nil
}

func (s *server) transcribeWithGroq(ctx context.Context, audio []byte, header *multipart.FileHeader) (string, error) {
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	contentType := header.Header.Get("Content-Type")
	if contentType == "" {
		contentType = "audio/webm"
	}
	filename := header.Filename
	if filename == "" {
		filename = "audio.webm"
	}

	partHeader := make(textproto.MIMEHeader)
	partHeader.Set("Content-Disposition", fmt.Sprintf(`form-data; name="file"; filename="%s"`, escapeQuotes(filename)))
	partHeader.Set("Content-Type", contentType)
	part, err := writer.CreatePart(partHeader)
	if err != nil {
		return "", apiError{status: http.StatusBadGateway, detail: err.Error()}
	}
	_, _ = part.Write(audio)
	_ = writer.WriteField("model", groqSTTModel)
	if err := writer.Close(); err != nil {
		return "", apiError{status: http.StatusBadGateway, detail: err.Error()}
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://api.groq.com/openai/v1/audio/transcriptions", &body)
	if err != nil {
		return "", apiError{status: http.StatusBadGateway, detail: err.Error()}
	}
	req.Header.Set("Authorization", "Bearer "+s.cfg.GroqAPIKey)
	req.Header.Set("Content-Type", writer.FormDataContentType())

	resp, err := s.client.Do(req)
	if err != nil {
		return "", apiError{status: http.StatusServiceUnavailable, detail: "Transcription request failed: " + err.Error()}
	}
	respBody, readErr := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if readErr != nil {
		return "", apiError{status: http.StatusBadGateway, detail: "Failed to read transcription response"}
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", upstreamError(resp.StatusCode, "Transcription failed", respBody)
	}

	var payload struct {
		Text string `json:"text"`
	}
	if err := json.Unmarshal(respBody, &payload); err != nil {
		return "", apiError{status: http.StatusBadGateway, detail: "Invalid transcription response"}
	}
	return payload.Text, nil
}

func envOrDefault(key string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value
}

func envInt64OrDefault(key string, fallback int64) int64 {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}

func isSafeRecordingID(value string) bool {
	if value == "" || len(value) > 120 {
		return false
	}
	for _, ch := range value {
		if (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '-' || ch == '_' {
			continue
		}
		return false
	}
	return true
}

func normalizeTTSText(text string) (string, error) {
	normalized := strings.TrimSpace(text)
	if normalized == "" {
		return "", errors.New("text cannot be empty")
	}
	if len([]rune(normalized)) > maxTTSChars {
		return string([]rune(normalized)[:maxTTSChars]), nil
	}
	return normalized, nil
}

func normalizeLanguage(language string) string {
	normalized := strings.ToLower(strings.TrimSpace(language))
	if normalized == "" {
		return defaultLanguage
	}
	return normalized
}

func providerChain(primary string, fallback string) []string {
	seen := map[string]bool{}
	var chain []string
	for _, value := range []string{primary, fallback} {
		name := normalizeProviderName(value)
		if name == "" || seen[name] {
			continue
		}
		seen[name] = true
		chain = append(chain, name)
	}
	return chain
}

func normalizeProviderName(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}

func allowedRecordingContentTypes() []string {
	values := make([]string, 0, len(allowedRecordingTypes))
	for contentType := range allowedRecordingTypes {
		values = append(values, contentType)
	}
	sort.Strings(values)
	return values
}

func chunkText(text string, maxChars int) []string {
	words := strings.Fields(text)
	remaining := strings.Join(words, " ")
	if len([]rune(remaining)) <= maxChars {
		return []string{remaining}
	}

	var chunks []string
	splitChars := ".!?;:, "
	for remaining != "" {
		runes := []rune(remaining)
		if len(runes) <= maxChars {
			chunks = append(chunks, strings.TrimSpace(remaining))
			break
		}
		window := string(runes[:maxChars])
		splitAt := -1
		for _, ch := range splitChars {
			if idx := strings.LastIndex(window, string(ch)); idx > splitAt {
				splitAt = idx
			}
		}
		if splitAt <= 0 {
			splitAt = len(string(runes[:maxChars]))
		}
		chunk := strings.TrimSpace(remaining[:splitAt])
		if chunk == "" {
			chunk = strings.TrimSpace(string(runes[:maxChars]))
			splitAt = len(chunk)
		}
		chunks = append(chunks, chunk)
		remaining = strings.TrimSpace(remaining[splitAt:])
	}
	return chunks
}

func mergeWAVChunks(chunks [][]byte) ([]byte, error) {
	if len(chunks) == 0 {
		return nil, errors.New("no audio chunks to merge")
	}
	if len(chunks) == 1 {
		return chunks[0], nil
	}

	var fmtChunk []byte
	var data bytes.Buffer
	for _, chunk := range chunks {
		currentFmt, currentData, err := parseWAV(chunk)
		if err != nil {
			return nil, err
		}
		if fmtChunk == nil {
			fmtChunk = currentFmt
		} else if !bytes.Equal(fmtChunk, currentFmt) {
			return nil, errors.New("incompatible TTS audio chunk parameters")
		}
		data.Write(currentData)
	}

	var out bytes.Buffer
	out.WriteString("RIFF")
	_ = binary.Write(&out, binary.LittleEndian, uint32(4+8+len(fmtChunk)+8+data.Len()))
	out.WriteString("WAVE")
	out.WriteString("fmt ")
	_ = binary.Write(&out, binary.LittleEndian, uint32(len(fmtChunk)))
	out.Write(fmtChunk)
	out.WriteString("data")
	_ = binary.Write(&out, binary.LittleEndian, uint32(data.Len()))
	out.Write(data.Bytes())
	return out.Bytes(), nil
}

func parseWAV(payload []byte) ([]byte, []byte, error) {
	if len(payload) < 12 || string(payload[:4]) != "RIFF" || string(payload[8:12]) != "WAVE" {
		return nil, nil, errors.New("invalid WAV audio response")
	}
	var fmtChunk []byte
	var dataChunk []byte
	offset := 12
	for offset+8 <= len(payload) {
		id := string(payload[offset : offset+4])
		size := int(binary.LittleEndian.Uint32(payload[offset+4 : offset+8]))
		offset += 8
		if offset+size > len(payload) {
			return nil, nil, errors.New("invalid WAV chunk size")
		}
		chunkData := payload[offset : offset+size]
		switch id {
		case "fmt ":
			fmtChunk = append([]byte(nil), chunkData...)
		case "data":
			dataChunk = append([]byte(nil), chunkData...)
		}
		offset += size
		if size%2 == 1 {
			offset++
		}
	}
	if fmtChunk == nil || dataChunk == nil {
		return nil, nil, errors.New("missing WAV fmt or data chunk")
	}
	return fmtChunk, dataChunk, nil
}

func upstreamError(status int, prefix string, body []byte) apiError {
	detail := strings.TrimSpace(string(body))
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err == nil {
		if value, ok := payload["detail"].(string); ok && strings.TrimSpace(value) != "" {
			detail = strings.TrimSpace(value)
		}
		if value, ok := payload["message"].(string); ok && strings.TrimSpace(value) != "" {
			detail = strings.TrimSpace(value)
		}
		if errObj, ok := payload["error"].(map[string]any); ok {
			if value, ok := errObj["message"].(string); ok && strings.TrimSpace(value) != "" {
				detail = strings.TrimSpace(value)
			}
		}
	}
	if detail == "" {
		detail = "HTTP " + strconv.Itoa(status)
	}

	switch status {
	case http.StatusTooManyRequests, http.StatusInternalServerError, http.StatusBadGateway, http.StatusServiceUnavailable, http.StatusGatewayTimeout:
		return apiError{status: http.StatusServiceUnavailable, detail: prefix + ": " + detail}
	case http.StatusUnauthorized, http.StatusForbidden:
		return apiError{status: http.StatusServiceUnavailable, detail: prefix + " authentication failed: " + detail}
	case http.StatusBadRequest, http.StatusNotFound, http.StatusUnprocessableEntity:
		return apiError{status: http.StatusUnprocessableEntity, detail: prefix + ": " + detail}
	default:
		return apiError{status: http.StatusBadGateway, detail: prefix + ": " + detail}
	}
}

func selectProviderError(errs []error) error {
	if len(errs) == 0 {
		return apiError{status: http.StatusServiceUnavailable, detail: "No TTS providers available"}
	}
	for _, err := range errs {
		var apiErr apiError
		if errors.As(err, &apiErr) && apiErr.status == http.StatusBadGateway {
			return err
		}
	}
	return errs[len(errs)-1]
}

func writeAPIError(w http.ResponseWriter, err error) {
	var apiErr apiError
	if errors.As(err, &apiErr) {
		writeError(w, apiErr.status, apiErr.detail)
		return
	}
	writeError(w, http.StatusInternalServerError, err.Error())
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func escapeQuotes(value string) string {
	return strings.ReplaceAll(value, `"`, `\"`)
}
