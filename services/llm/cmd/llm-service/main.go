package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

const defaultListenAddr = ":8080"

type config struct {
	GroqAPIKey       string
	OpenAIAPIKey     string
	AnthropicAPIKey  string
	OpenRouterAPIKey string
	AppURL           string
	GroqURL          string
	OpenAIURL        string
	AnthropicURL     string
	OpenRouterURL    string
}

type providerMetrics struct {
	mu              sync.Mutex
	requestsTotal   int64
	successTotal    int64
	errorTotal      int64
	rateLimitTotal  int64
	lastSuccessAt   time.Time
	lastErrorAt     time.Time
	lastLatencyMs   int64
	lastErrorDetail string
}

type server struct {
	cfg     config
	client  *http.Client
	metrics map[string]*providerMetrics
}

func newMetrics() map[string]*providerMetrics {
	return map[string]*providerMetrics{
		"groq":       {},
		"openai":     {},
		"anthropic":  {},
		"openrouter": {},
	}
}

func (s *server) recordRequest(provider string, latency time.Duration, err error) {
	m, ok := s.metrics[provider]
	if !ok {
		return
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.requestsTotal++
	m.lastLatencyMs = latency.Milliseconds()
	if err == nil {
		m.successTotal++
		m.lastSuccessAt = time.Now().UTC()
	} else {
		m.errorTotal++
		m.lastErrorAt = time.Now().UTC()
		m.lastErrorDetail = truncate(err.Error(), 200)
		var llmErr llmError
		if asLLMError(err, &llmErr) && llmErr.category == "rate_limit_error" {
			m.rateLimitTotal++
		}
	}
}

type message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type completeRequest struct {
	Provider       string         `json:"provider"`
	Model          string         `json:"model"`
	Messages       []message      `json:"messages"`
	PromptOverride string         `json:"prompt_override"`
	MaxTokens      int            `json:"max_tokens"`
	Temperature    float64        `json:"temperature"`
	TimeoutSeconds float64        `json:"timeout_seconds"`
	MaxRetries     int            `json:"max_retries"`
	Tool           map[string]any `json:"tool"`
}

type completeResponse struct {
	Text     string `json:"text"`
	Model    string `json:"model"`
	Provider string `json:"provider"`
}

type providerStatus struct {
	Provider        string `json:"provider"`
	RequiredAPIKey  string `json:"required_api_key"`
	Configured      bool   `json:"configured"`
	RequestsTotal   int64  `json:"requests_total"`
	SuccessTotal    int64  `json:"success_total"`
	ErrorTotal      int64  `json:"error_total"`
	RateLimitTotal  int64  `json:"rate_limit_total"`
	LastSuccessAt   string `json:"last_success_at,omitempty"`
	LastErrorAt     string `json:"last_error_at,omitempty"`
	LastLatencyMs   int64  `json:"last_latency_ms,omitempty"`
	LastErrorDetail string `json:"last_error_detail,omitempty"`
}

type llmError struct {
	status   int
	category string
	detail   string
	retry    bool
}

func (e llmError) Error() string {
	return e.detail
}

func main() {
	cfg := config{
		GroqAPIKey:       strings.TrimSpace(os.Getenv("GROQ_API_KEY")),
		OpenAIAPIKey:     strings.TrimSpace(os.Getenv("OPENAI_API_KEY")),
		AnthropicAPIKey:  strings.TrimSpace(os.Getenv("ANTHROPIC_API_KEY")),
		OpenRouterAPIKey: strings.TrimSpace(os.Getenv("OPENROUTER_API_KEY")),
		AppURL:           envOrDefault("APP_URL", "http://localhost:3000"),
		GroqURL:          envOrDefault("GROQ_CHAT_COMPLETIONS_URL", "https://api.groq.com/openai/v1/chat/completions"),
		OpenAIURL:        envOrDefault("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses"),
		AnthropicURL:     envOrDefault("ANTHROPIC_MESSAGES_URL", "https://api.anthropic.com/v1/messages"),
		OpenRouterURL:    envOrDefault("OPENROUTER_CHAT_COMPLETIONS_URL", "https://openrouter.ai/api/v1/chat/completions"),
	}
	srv := &server{cfg: cfg, client: &http.Client{}, metrics: newMetrics()}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "service": "llm-service"})
	})
	mux.HandleFunc("GET /v1/status", srv.handleStatus)
	mux.HandleFunc("POST /v1/complete", srv.handleComplete)

	addr := envOrDefault("LLM_SERVICE_ADDR", defaultListenAddr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		panic(err)
	}
}

func (s *server) handleStatus(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"service":   "llm-service",
		"providers": s.providerStatuses(),
	})
}

func (s *server) providerStatuses() []providerStatus {
	defs := []struct {
		name       string
		key        string
		configured bool
	}{
		{"groq", "GROQ_API_KEY", s.cfg.GroqAPIKey != ""},
		{"openai", "OPENAI_API_KEY", s.cfg.OpenAIAPIKey != ""},
		{"anthropic", "ANTHROPIC_API_KEY", s.cfg.AnthropicAPIKey != ""},
		{"openrouter", "OPENROUTER_API_KEY", s.cfg.OpenRouterAPIKey != ""},
	}
	result := make([]providerStatus, 0, len(defs))
	for _, d := range defs {
		ps := providerStatus{Provider: d.name, RequiredAPIKey: d.key, Configured: d.configured}
		if m, ok := s.metrics[d.name]; ok {
			m.mu.Lock()
			ps.RequestsTotal = m.requestsTotal
			ps.SuccessTotal = m.successTotal
			ps.ErrorTotal = m.errorTotal
			ps.RateLimitTotal = m.rateLimitTotal
			ps.LastLatencyMs = m.lastLatencyMs
			ps.LastErrorDetail = m.lastErrorDetail
			if !m.lastSuccessAt.IsZero() {
				ps.LastSuccessAt = m.lastSuccessAt.Format(time.RFC3339)
			}
			if !m.lastErrorAt.IsZero() {
				ps.LastErrorAt = m.lastErrorAt.Format(time.RFC3339)
			}
			m.mu.Unlock()
		}
		result = append(result, ps)
	}
	return result
}

func (s *server) handleComplete(w http.ResponseWriter, r *http.Request) {
	var payload completeRequest
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		writeError(w, http.StatusBadRequest, "provider_error", "Invalid JSON body", false)
		return
	}
	payload.Provider = strings.ToLower(strings.TrimSpace(payload.Provider))
	payload.Model = strings.TrimSpace(payload.Model)
	payload.PromptOverride = strings.TrimSpace(payload.PromptOverride)
	if payload.Provider == "" || payload.Model == "" {
		writeError(w, http.StatusUnprocessableEntity, "configuration_error", "provider and model are required", false)
		return
	}
	if payload.MaxTokens <= 0 {
		payload.MaxTokens = 512
	}
	if payload.TimeoutSeconds <= 0 {
		payload.TimeoutSeconds = 30
	}
	payload.MaxRetries = normalizeMaxRetries(payload.MaxRetries)

	ctx, cancel := context.WithTimeout(r.Context(), timeoutDuration(payload.TimeoutSeconds))
	defer cancel()

	start := time.Now()
	result, err := s.completeWithRetries(ctx, payload)
	s.recordRequest(payload.Provider, time.Since(start), err)

	if err != nil {
		var llmErr llmError
		if asLLMError(err, &llmErr) {
			writeError(w, llmErr.status, llmErr.category, llmErr.detail, llmErr.retry)
			return
		}
		writeError(w, http.StatusBadGateway, "provider_error", err.Error(), true)
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func (s *server) completeWithRetries(ctx context.Context, req completeRequest) (completeResponse, error) {
	attempts := normalizeMaxRetries(req.MaxRetries) + 1
	var lastErr error
	for attempt := 0; attempt < attempts; attempt++ {
		result, err := s.complete(ctx, req)
		if err == nil {
			return result, nil
		}
		lastErr = err

		var llmErr llmError
		if !asLLMError(err, &llmErr) || !llmErr.retry || attempt >= attempts-1 {
			if attempt >= attempts-1 && asLLMError(err, &llmErr) {
				llmErr.retry = false
				return completeResponse{}, llmErr
			}
			return completeResponse{}, err
		}

		if err := sleepBeforeRetry(ctx, attempt); err != nil {
			return completeResponse{}, llmError{
				status:   http.StatusGatewayTimeout,
				category: "timeout_error",
				detail:   "LLM retry timeout exceeded",
			}
		}
	}
	return completeResponse{}, lastErr
}

func (s *server) complete(ctx context.Context, req completeRequest) (completeResponse, error) {
	switch req.Provider {
	case "groq":
		if s.cfg.GroqAPIKey == "" {
			return completeResponse{}, configurationError("GROQ_API_KEY is not configured")
		}
		return s.chatCompletions(ctx, req, "groq", s.cfg.GroqURL, map[string]string{"Authorization": "Bearer " + s.cfg.GroqAPIKey})
	case "openai":
		if s.cfg.OpenAIAPIKey == "" {
			return completeResponse{}, configurationError("OPENAI_API_KEY is not configured")
		}
		return s.openAIResponse(ctx, req)
	case "anthropic":
		if s.cfg.AnthropicAPIKey == "" {
			return completeResponse{}, configurationError("ANTHROPIC_API_KEY is not configured")
		}
		return s.anthropicMessage(ctx, req)
	case "openrouter":
		if s.cfg.OpenRouterAPIKey == "" {
			return completeResponse{}, configurationError("OPENROUTER_API_KEY is not configured")
		}
		headers := map[string]string{
			"Authorization": "Bearer " + s.cfg.OpenRouterAPIKey,
			"HTTP-Referer":  s.cfg.AppURL,
			"X-Title":       "AIRecruit",
		}
		return s.chatCompletions(ctx, req, "openrouter", s.cfg.OpenRouterURL, headers)
	default:
		return completeResponse{}, llmError{status: http.StatusUnprocessableEntity, category: "configuration_error", detail: "unsupported LLM provider"}
	}
}

func (s *server) chatCompletions(ctx context.Context, req completeRequest, provider string, url string, headers map[string]string) (completeResponse, error) {
	system, messages := normalizeMessages(req.Messages, req.PromptOverride)
	if len(req.Tool) > 0 && provider != "groq" {
		messages = append(messages, structuredInstruction(req.Tool))
	}
	if system != "" {
		messages = append([]message{{Role: "system", Content: system}}, messages...)
	}
	payload := map[string]any{
		"model":       req.Model,
		"messages":    messages,
		"max_tokens":  req.MaxTokens,
		"temperature": req.Temperature,
	}
	if provider == "groq" && len(req.Tool) > 0 {
		name := toolName(req.Tool)
		payload["tools"] = []map[string]any{req.Tool}
		payload["tool_choice"] = map[string]any{"type": "function", "function": map[string]any{"name": name}}
	}
	if provider == "openrouter" {
		payload["provider"] = map[string]any{"allow_fallbacks": false}
	}
	data, err := s.postJSON(ctx, provider, url, headers, payload)
	if err != nil {
		return completeResponse{}, err
	}
	text := extractChatCompletionText(data, len(req.Tool) > 0 && provider == "groq")
	if text == "" && len(req.Tool) > 0 {
		return completeResponse{}, llmError{status: http.StatusBadGateway, category: "invalid_structured_output", detail: provider + " returned empty structured output"}
	}
	return completeResponse{Text: text, Model: req.Model, Provider: provider}, nil
}

func (s *server) openAIResponse(ctx context.Context, req completeRequest) (completeResponse, error) {
	system, messages := normalizeMessages(req.Messages, req.PromptOverride)
	payload := map[string]any{
		"model":             req.Model,
		"input":             messages,
		"max_output_tokens": req.MaxTokens,
		"temperature":       req.Temperature,
	}
	if system != "" {
		payload["instructions"] = system
	}
	if len(req.Tool) > 0 {
		payload["text"] = map[string]any{"format": map[string]any{
			"type":   "json_schema",
			"name":   toolName(req.Tool),
			"schema": toolSchema(req.Tool),
			"strict": false,
		}}
		messages = append(messages, structuredInstruction(req.Tool))
		payload["input"] = messages
	}
	data, err := s.postJSON(ctx, "openai", s.cfg.OpenAIURL, map[string]string{"Authorization": "Bearer " + s.cfg.OpenAIAPIKey}, payload)
	if err != nil {
		return completeResponse{}, err
	}
	text := extractOpenAIText(data)
	if text == "" && len(req.Tool) > 0 {
		return completeResponse{}, llmError{status: http.StatusBadGateway, category: "invalid_structured_output", detail: "openai returned empty structured output"}
	}
	return completeResponse{Text: text, Model: req.Model, Provider: "openai"}, nil
}

func (s *server) anthropicMessage(ctx context.Context, req completeRequest) (completeResponse, error) {
	system, messages := normalizeMessages(req.Messages, req.PromptOverride)
	if len(req.Tool) > 0 {
		messages = append(messages, structuredInstruction(req.Tool))
	}
	payload := map[string]any{
		"model":       req.Model,
		"max_tokens":  req.MaxTokens,
		"temperature": req.Temperature,
		"messages":    messages,
	}
	if system != "" {
		payload["system"] = system
	}
	data, err := s.postJSON(ctx, "anthropic", s.cfg.AnthropicURL, map[string]string{
		"x-api-key":         s.cfg.AnthropicAPIKey,
		"anthropic-version": "2023-06-01",
	}, payload)
	if err != nil {
		return completeResponse{}, err
	}
	text := extractAnthropicText(data)
	if text == "" && len(req.Tool) > 0 {
		return completeResponse{}, llmError{status: http.StatusBadGateway, category: "invalid_structured_output", detail: "anthropic returned empty structured output"}
	}
	return completeResponse{Text: text, Model: req.Model, Provider: "anthropic"}, nil
}

func (s *server) postJSON(ctx context.Context, provider string, url string, headers map[string]string, payload map[string]any) (map[string]any, error) {
	body, _ := json.Marshal(payload)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	for key, value := range headers {
		if strings.TrimSpace(value) != "" {
			httpReq.Header.Set(key, value)
		}
	}
	resp, err := s.client.Do(httpReq)
	if err != nil {
		if ctx.Err() != nil {
			return nil, llmError{status: http.StatusGatewayTimeout, category: "timeout_error", detail: provider + " request timed out", retry: true}
		}
		return nil, llmError{status: http.StatusGatewayTimeout, category: "timeout_error", detail: provider + " network request failed", retry: true}
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 2*1024*1024))
	if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
		return nil, llmError{status: http.StatusBadGateway, category: "auth_error", detail: provider + " authentication failed"}
	}
	if resp.StatusCode == http.StatusTooManyRequests {
		return nil, llmError{status: http.StatusTooManyRequests, category: "rate_limit_error", detail: provider + " rate limit exceeded", retry: true}
	}
	if resp.StatusCode >= 500 {
		return nil, llmError{status: http.StatusBadGateway, category: "provider_error", detail: provider + " provider error", retry: true}
	}
	if resp.StatusCode >= 400 {
		return nil, llmError{status: http.StatusBadGateway, category: "provider_error", detail: fmt.Sprintf("%s request failed with status %d: %s", provider, resp.StatusCode, truncate(string(raw), 240))}
	}
	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, llmError{status: http.StatusBadGateway, category: "provider_error", detail: provider + " returned invalid JSON"}
	}
	return data, nil
}

func normalizeMessages(input []message, promptOverride string) (string, []message) {
	var system []string
	var messages []message
	if promptOverride != "" {
		system = append(system, promptOverride)
	}
	for _, item := range input {
		role := strings.ToLower(strings.TrimSpace(item.Role))
		content := item.Content
		if role == "system" {
			if promptOverride == "" && strings.TrimSpace(content) != "" {
				system = append(system, content)
			}
			continue
		}
		if role != "assistant" {
			role = "user"
		}
		messages = append(messages, message{Role: role, Content: content})
	}
	return strings.Join(system, "\n\n"), messages
}

func structuredInstruction(tool map[string]any) message {
	description := ""
	if fn, ok := tool["function"].(map[string]any); ok {
		description, _ = fn["description"].(string)
	}
	schema, _ := json.Marshal(toolSchema(tool))
	return message{
		Role: "user",
		Content: fmt.Sprintf(
			"Return only valid JSON for `%s`. %s\nJSON schema:\n%s",
			toolName(tool),
			description,
			string(schema),
		),
	}
}

func toolName(tool map[string]any) string {
	if fn, ok := tool["function"].(map[string]any); ok {
		if name, ok := fn["name"].(string); ok && strings.TrimSpace(name) != "" {
			return strings.TrimSpace(name)
		}
	}
	return "submit_result"
}

func toolSchema(tool map[string]any) any {
	if fn, ok := tool["function"].(map[string]any); ok {
		if schema, ok := fn["parameters"]; ok {
			return schema
		}
	}
	return map[string]any{}
}

func extractChatCompletionText(data map[string]any, toolCall bool) string {
	choices, _ := data["choices"].([]any)
	if len(choices) == 0 {
		return ""
	}
	choice, _ := choices[0].(map[string]any)
	msg, _ := choice["message"].(map[string]any)
	if toolCall {
		calls, _ := msg["tool_calls"].([]any)
		if len(calls) == 0 {
			return ""
		}
		call, _ := calls[0].(map[string]any)
		fn, _ := call["function"].(map[string]any)
		text, _ := fn["arguments"].(string)
		return strings.TrimSpace(text)
	}
	if text, ok := msg["content"].(string); ok {
		return strings.TrimSpace(text)
	}
	return ""
}

func extractOpenAIText(data map[string]any) string {
	if text, ok := data["output_text"].(string); ok {
		return strings.TrimSpace(text)
	}
	var chunks []string
	output, _ := data["output"].([]any)
	for _, item := range output {
		obj, _ := item.(map[string]any)
		content, _ := obj["content"].([]any)
		for _, part := range content {
			partObj, _ := part.(map[string]any)
			if text, ok := partObj["text"].(string); ok {
				chunks = append(chunks, text)
			}
		}
	}
	return strings.TrimSpace(strings.Join(chunks, "\n"))
}

func extractAnthropicText(data map[string]any) string {
	var chunks []string
	content, _ := data["content"].([]any)
	for _, item := range content {
		obj, _ := item.(map[string]any)
		if obj["type"] == "text" {
			if text, ok := obj["text"].(string); ok {
				chunks = append(chunks, text)
			}
		}
	}
	return strings.TrimSpace(strings.Join(chunks, "\n"))
}

func configurationError(detail string) error {
	return llmError{status: http.StatusServiceUnavailable, category: "configuration_error", detail: detail}
}

func asLLMError(err error, target *llmError) bool {
	if err == nil {
		return false
	}
	if value, ok := err.(llmError); ok {
		*target = value
		return true
	}
	return false
}

func timeoutDuration(value float64) time.Duration {
	if value <= 0 {
		value = 30
	}
	if value > 180 {
		value = 180
	}
	return time.Duration(value * float64(time.Second))
}

func normalizeMaxRetries(value int) int {
	if value < 0 {
		return 0
	}
	if value > 5 {
		return 5
	}
	return value
}

func sleepBeforeRetry(ctx context.Context, attempt int) error {
	delay := time.Duration(250*(1<<attempt)) * time.Millisecond
	if delay > 2*time.Second {
		delay = 2 * time.Second
	}
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func envOrDefault(key string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value
}

func writeError(w http.ResponseWriter, status int, category string, detail string, retryable bool) {
	writeJSON(w, status, map[string]any{"category": category, "detail": detail, "retryable": retryable})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func truncate(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return value[:limit]
}
