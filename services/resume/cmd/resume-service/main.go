package main

import (
	"archive/zip"
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

const defaultMaxResumeSizeMB = 10
const rawTextMaxChars = 100_000

var allowedContentTypes = map[string]string{
	"application/pdf": ".pdf",
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}

type uploadResponse struct {
	Path     string `json:"path"`
	FileSize int64  `json:"file_size"`
	RawText  string `json:"raw_text"`
}

type statusResponse struct {
	Service             string   `json:"service"`
	StorageConfigured   bool     `json:"storage_configured"`
	StorageWritable     bool     `json:"storage_writable"`
	MaxResumeSizeBytes  int64    `json:"max_resume_size_bytes"`
	MaxResumeSizeMB     int64    `json:"max_resume_size_mb"`
	RawTextMaxChars     int      `json:"raw_text_max_chars"`
	AllowedContentTypes []string `json:"allowed_content_types"`
}

type server struct {
	storageDir string
	maxBytes   int64
}

func main() {
	srv := &server{
		storageDir: envOrDefault("RESUME_STORAGE_DIR", "/app/storage/resumes"),
		maxBytes:   int64(envIntOrDefault("MAX_RESUME_SIZE_MB", defaultMaxResumeSizeMB)) * 1024 * 1024,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", srv.handleHealth)
	mux.HandleFunc("GET /v1/status", srv.handleStatus)
	mux.HandleFunc("POST /v1/resumes", srv.handleUpload)

	addr := envOrDefault("RESUME_SERVICE_ADDR", ":8080")
	if err := http.ListenAndServe(addr, mux); err != nil {
		panic(err)
	}
}

func (s *server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":           "ok",
		"service":          "resume-service",
		"storage_writable": s.storageWritable(),
	})
}

func (s *server) handleStatus(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, s.status())
}

func (s *server) handleUpload(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(s.maxBytes); err != nil {
		writeError(w, http.StatusRequestEntityTooLarge, "file exceeds maximum allowed size")
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "file field is required")
		return
	}
	defer file.Close()

	result, err := s.processUpload(file, header)
	if err != nil {
		var httpErr httpError
		if errors.As(err, &httpErr) {
			writeError(w, httpErr.status, httpErr.detail)
			return
		}
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func (s *server) processUpload(file multipart.File, header *multipart.FileHeader) (uploadResponse, error) {
	contentType := strings.TrimSpace(header.Header.Get("Content-Type"))
	extension, ok := allowedContentTypes[contentType]
	if !ok {
		return uploadResponse{}, httpError{
			status: http.StatusUnsupportedMediaType,
			detail: fmt.Sprintf("Unsupported file type '%s'. Allowed: PDF, DOCX.", contentType),
		}
	}

	content, err := readLimited(file, s.maxBytes)
	if err != nil {
		return uploadResponse{}, httpError{status: http.StatusRequestEntityTooLarge, detail: "file exceeds maximum allowed size"}
	}

	rawText := extractText(content, extension)
	if len(rawText) > rawTextMaxChars {
		rawText = rawText[:rawTextMaxChars]
	}

	if err := os.MkdirAll(s.storageDir, 0o755); err != nil {
		return uploadResponse{}, err
	}
	path := filepath.Join(s.storageDir, randomHex(16)+extension)
	if err := os.WriteFile(path, content, 0o644); err != nil {
		return uploadResponse{}, err
	}

	return uploadResponse{Path: path, FileSize: int64(len(content)), RawText: rawText}, nil
}

func (s *server) status() statusResponse {
	return statusResponse{
		Service:             "resume-service",
		StorageConfigured:   strings.TrimSpace(s.storageDir) != "",
		StorageWritable:     s.storageWritable(),
		MaxResumeSizeBytes:  s.maxBytes,
		MaxResumeSizeMB:     s.maxBytes / 1024 / 1024,
		RawTextMaxChars:     rawTextMaxChars,
		AllowedContentTypes: allowedContentTypeList(),
	}
}

func (s *server) storageWritable() bool {
	if strings.TrimSpace(s.storageDir) == "" {
		return false
	}
	if err := os.MkdirAll(s.storageDir, 0o755); err != nil {
		return false
	}
	tmp, err := os.CreateTemp(s.storageDir, ".resume-service-health-*")
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

func allowedContentTypeList() []string {
	values := make([]string, 0, len(allowedContentTypes))
	for contentType := range allowedContentTypes {
		values = append(values, contentType)
	}
	sort.Strings(values)
	return values
}

func readLimited(reader io.Reader, maxBytes int64) ([]byte, error) {
	var buf bytes.Buffer
	limited := io.LimitReader(reader, maxBytes+1)
	if _, err := io.Copy(&buf, limited); err != nil {
		return nil, err
	}
	if int64(buf.Len()) > maxBytes {
		return nil, errors.New("too large")
	}
	return buf.Bytes(), nil
}

func extractText(content []byte, extension string) string {
	var text string
	if extension == ".docx" {
		text = extractDOCXText(content)
	} else if extension == ".pdf" {
		text = extractPDFText(content)
	}
	return strings.TrimSpace(text)
}

func extractDOCXText(content []byte) string {
	reader, err := zip.NewReader(bytes.NewReader(content), int64(len(content)))
	if err != nil {
		return ""
	}
	for _, file := range reader.File {
		if file.Name != "word/document.xml" {
			continue
		}
		handle, err := file.Open()
		if err != nil {
			return ""
		}
		defer handle.Close()
		return parseWordDocumentXML(handle)
	}
	return ""
}

func parseWordDocumentXML(reader io.Reader) string {
	decoder := xml.NewDecoder(reader)
	var paragraphs []string
	var current strings.Builder
	inText := false
	for {
		token, err := decoder.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			return ""
		}
		switch item := token.(type) {
		case xml.StartElement:
			if item.Name.Local == "t" {
				inText = true
			}
		case xml.CharData:
			if inText {
				current.WriteString(string(item))
			}
		case xml.EndElement:
			if item.Name.Local == "t" {
				inText = false
			}
			if item.Name.Local == "p" {
				value := strings.TrimSpace(current.String())
				if value != "" {
					paragraphs = append(paragraphs, value)
				}
				current.Reset()
			}
		}
	}
	return strings.Join(paragraphs, "\n")
}

func extractPDFText(content []byte) string {
	// This intentionally stays conservative: extraction failures are non-fatal,
	// matching the Python path that stores the file even when text parsing fails.
	raw := string(content)
	matches := regexp.MustCompile(`\(([^()]*)\)`).FindAllStringSubmatch(raw, -1)
	parts := make([]string, 0, len(matches))
	for _, match := range matches {
		if len(match) < 2 {
			continue
		}
		value := strings.TrimSpace(strings.ReplaceAll(match[1], `\)`, ")"))
		value = strings.ReplaceAll(value, `\(`, "(")
		if value != "" {
			parts = append(parts, value)
		}
	}
	return strings.Join(parts, "\n")
}

func randomHex(byteLen int) string {
	buffer := make([]byte, byteLen)
	if _, err := rand.Read(buffer); err != nil {
		panic(err)
	}
	return hex.EncodeToString(buffer)
}

func envOrDefault(key string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value
}

func envIntOrDefault(key string, fallback int) int {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	var parsed int
	if _, err := fmt.Sscanf(value, "%d", &parsed); err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}

type httpError struct {
	status int
	detail string
}

func (e httpError) Error() string {
	return e.detail
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
