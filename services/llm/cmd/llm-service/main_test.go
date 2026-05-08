package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHandleCompleteUsesGroqChatCompletions(t *testing.T) {
	var captured map[string]any
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer groq-key" {
			t.Fatalf("missing auth header: %s", r.Header.Get("Authorization"))
		}
		if err := json.NewDecoder(r.Body).Decode(&captured); err != nil {
			t.Fatal(err)
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"choices": []any{map[string]any{"message": map[string]any{"content": "groq ok"}}},
		})
	}))
	defer upstream.Close()

	srv := &server{
		cfg:    config{GroqAPIKey: "groq-key", GroqURL: upstream.URL},
		client: upstream.Client(),
	}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/complete",
		strings.NewReader(`{"provider":"groq","model":"llama-3.3-70b-versatile","messages":[{"role":"system","content":"sys"},{"role":"user","content":"hello"}],"max_tokens":12,"temperature":0}`),
	)
	rec := httptest.NewRecorder()

	srv.handleComplete(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	if captured["model"] != "llama-3.3-70b-versatile" {
		t.Fatalf("unexpected payload: %#v", captured)
	}
	messages := captured["messages"].([]any)
	first := messages[0].(map[string]any)
	if first["role"] != "system" || first["content"] != "sys" {
		t.Fatalf("expected system prompt first: %#v", messages)
	}
}

func TestHandleStatusDoesNotExposeSecrets(t *testing.T) {
	srv := &server{
		cfg: config{
			GroqAPIKey:       "groq-secret",
			OpenRouterAPIKey: "openrouter-secret",
		},
		client: http.DefaultClient,
	}
	req := httptest.NewRequest(http.MethodGet, "/v1/status", nil)
	rec := httptest.NewRecorder()

	srv.handleStatus(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	body := rec.Body.String()
	if strings.Contains(body, "groq-secret") || strings.Contains(body, "openrouter-secret") {
		t.Fatalf("status leaked secret: %s", body)
	}
	if !strings.Contains(body, `"provider":"groq"`) || !strings.Contains(body, `"required_api_key":"OPENROUTER_API_KEY"`) {
		t.Fatalf("status missing provider metadata: %s", body)
	}
	if !strings.Contains(body, `"configured":true`) || !strings.Contains(body, `"configured":false`) {
		t.Fatalf("status missing configured flags: %s", body)
	}
}

func TestOpenRouterDisablesProviderFallbacks(t *testing.T) {
	var captured map[string]any
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("HTTP-Referer") != "http://app.test" {
			t.Fatalf("missing referer header: %s", r.Header.Get("HTTP-Referer"))
		}
		_ = json.NewDecoder(r.Body).Decode(&captured)
		writeJSON(w, http.StatusOK, map[string]any{
			"choices": []any{map[string]any{"message": map[string]any{"content": "openrouter ok"}}},
		})
	}))
	defer upstream.Close()

	srv := &server{
		cfg:    config{OpenRouterAPIKey: "or-key", AppURL: "http://app.test", OpenRouterURL: upstream.URL},
		client: upstream.Client(),
	}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/complete",
		strings.NewReader(`{"provider":"openrouter","model":"openrouter/free","messages":[{"role":"user","content":"hello"}]}`),
	)
	rec := httptest.NewRecorder()

	srv.handleComplete(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	provider := captured["provider"].(map[string]any)
	if provider["allow_fallbacks"] != false {
		t.Fatalf("expected OpenRouter fallbacks disabled: %#v", captured)
	}
}

func TestMissingKeyReturnsConfigurationError(t *testing.T) {
	srv := &server{cfg: config{}, client: http.DefaultClient}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/complete",
		strings.NewReader(`{"provider":"openai","model":"gpt-4.1-mini","messages":[{"role":"user","content":"hello"}]}`),
	)
	rec := httptest.NewRecorder()

	srv.handleComplete(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "configuration_error") || !strings.Contains(rec.Body.String(), "OPENAI_API_KEY") {
		t.Fatalf("unexpected body: %s", rec.Body.String())
	}
}

func TestStructuredGroqExtractsToolCall(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"choices": []any{map[string]any{"message": map[string]any{
				"tool_calls": []any{map[string]any{"function": map[string]any{"arguments": `{"ok":true}`}}},
			}}},
		})
	}))
	defer upstream.Close()

	srv := &server{cfg: config{GroqAPIKey: "groq-key", GroqURL: upstream.URL}, client: upstream.Client()}
	result, err := srv.complete(context.Background(), completeRequest{
		Provider: "groq",
		Model:    "llama-3.3-70b-versatile",
		Messages: []message{{Role: "user", Content: "hello"}},
		Tool: map[string]any{"function": map[string]any{
			"name":       "submit_result",
			"parameters": map[string]any{"type": "object"},
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Text != `{"ok":true}` {
		t.Fatalf("unexpected result: %#v", result)
	}
}

func TestRetriesTransientProviderErrorInsideService(t *testing.T) {
	calls := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if calls == 1 {
			writeJSON(w, http.StatusBadGateway, map[string]any{"error": "temporary"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"choices": []any{map[string]any{"message": map[string]any{"content": "retried ok"}}},
		})
	}))
	defer upstream.Close()

	srv := &server{cfg: config{GroqAPIKey: "groq-key", GroqURL: upstream.URL}, client: upstream.Client()}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/complete",
		strings.NewReader(`{"provider":"groq","model":"llama-3.3-70b-versatile","messages":[{"role":"user","content":"hello"}],"max_retries":1}`),
	)
	rec := httptest.NewRecorder()

	srv.handleComplete(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	if calls != 2 {
		t.Fatalf("expected 2 upstream calls, got %d", calls)
	}
	if !strings.Contains(rec.Body.String(), "retried ok") {
		t.Fatalf("unexpected body: %s", rec.Body.String())
	}
}

func TestExhaustedTransientRetriesAreTerminalForCaller(t *testing.T) {
	calls := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		writeJSON(w, http.StatusInternalServerError, map[string]any{"error": "temporary"})
	}))
	defer upstream.Close()

	srv := &server{cfg: config{GroqAPIKey: "groq-key", GroqURL: upstream.URL}, client: upstream.Client()}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/complete",
		strings.NewReader(`{"provider":"groq","model":"llama-3.3-70b-versatile","messages":[{"role":"user","content":"hello"}],"max_retries":1}`),
	)
	rec := httptest.NewRecorder()

	srv.handleComplete(rec, req)

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("expected 502, got %d: %s", rec.Code, rec.Body.String())
	}
	if calls != 2 {
		t.Fatalf("expected 2 upstream calls, got %d", calls)
	}
	if !strings.Contains(rec.Body.String(), `"retryable":false`) {
		t.Fatalf("expected terminal error after Go retries: %s", rec.Body.String())
	}
}

func TestStructuredOpenAIResponseUsesJSONSchemaFormat(t *testing.T) {
	var captured map[string]any
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer openai-key" {
			t.Fatalf("missing auth header: %s", r.Header.Get("Authorization"))
		}
		_ = json.NewDecoder(r.Body).Decode(&captured)
		writeJSON(w, http.StatusOK, map[string]any{"output_text": `{"ok":true}`})
	}))
	defer upstream.Close()

	srv := &server{cfg: config{OpenAIAPIKey: "openai-key", OpenAIURL: upstream.URL}, client: upstream.Client()}
	result, err := srv.complete(context.Background(), completeRequest{
		Provider: "openai",
		Model:    "gpt-4.1-mini",
		Messages: []message{{Role: "user", Content: "hello"}},
		Tool: map[string]any{"function": map[string]any{
			"name":       "submit_result",
			"parameters": map[string]any{"type": "object"},
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Text != `{"ok":true}` {
		t.Fatalf("unexpected result: %#v", result)
	}
	text, ok := captured["text"].(map[string]any)
	if !ok || text["format"] == nil {
		t.Fatalf("expected OpenAI JSON schema format: %#v", captured)
	}
	input := captured["input"].([]any)
	last := input[len(input)-1].(map[string]any)
	if !strings.Contains(last["content"].(string), "Return only valid JSON") {
		t.Fatalf("expected structured instruction: %#v", input)
	}
}

func TestStructuredAnthropicResponseUsesMessagesAPI(t *testing.T) {
	var captured map[string]any
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("x-api-key") != "anthropic-key" {
			t.Fatalf("missing api key header: %s", r.Header.Get("x-api-key"))
		}
		_ = json.NewDecoder(r.Body).Decode(&captured)
		writeJSON(w, http.StatusOK, map[string]any{
			"content": []any{map[string]any{"type": "text", "text": `{"ok":true}`}},
		})
	}))
	defer upstream.Close()

	srv := &server{cfg: config{AnthropicAPIKey: "anthropic-key", AnthropicURL: upstream.URL}, client: upstream.Client()}
	result, err := srv.complete(context.Background(), completeRequest{
		Provider: "anthropic",
		Model:    "claude-3-5-haiku-latest",
		Messages: []message{{Role: "system", Content: "sys"}, {Role: "user", Content: "hello"}},
		Tool: map[string]any{"function": map[string]any{
			"name":       "submit_result",
			"parameters": map[string]any{"type": "object"},
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Text != `{"ok":true}` {
		t.Fatalf("unexpected result: %#v", result)
	}
	if captured["system"] != "sys" {
		t.Fatalf("expected system prompt: %#v", captured)
	}
	messages := captured["messages"].([]any)
	last := messages[len(messages)-1].(map[string]any)
	if !strings.Contains(last["content"].(string), "Return only valid JSON") {
		t.Fatalf("expected structured instruction: %#v", messages)
	}
}

func TestHandleCompleteRecordsSuccessMetrics(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{
			"choices": []any{map[string]any{"message": map[string]any{"content": "ok"}}},
		})
	}))
	defer upstream.Close()

	srv := &server{
		cfg:     config{GroqAPIKey: "groq-key", GroqURL: upstream.URL},
		client:  upstream.Client(),
		metrics: newMetrics(),
	}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/complete",
		strings.NewReader(`{"provider":"groq","model":"llama","messages":[{"role":"user","content":"hi"}]}`),
	)
	srv.handleComplete(httptest.NewRecorder(), req)

	m := srv.metrics["groq"]
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.requestsTotal != 1 || m.successTotal != 1 || m.errorTotal != 0 {
		t.Fatalf("unexpected metrics after success: req=%d ok=%d err=%d", m.requestsTotal, m.successTotal, m.errorTotal)
	}
	if m.lastSuccessAt.IsZero() {
		t.Fatal("expected lastSuccessAt to be set")
	}
	if m.lastLatencyMs < 0 {
		t.Fatalf("unexpected latency: %d", m.lastLatencyMs)
	}
}

func TestHandleCompleteRecordsErrorMetrics(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"error": "boom"})
	}))
	defer upstream.Close()

	srv := &server{
		cfg:     config{GroqAPIKey: "groq-key", GroqURL: upstream.URL},
		client:  upstream.Client(),
		metrics: newMetrics(),
	}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/complete",
		strings.NewReader(`{"provider":"groq","model":"llama","messages":[{"role":"user","content":"hi"}],"max_retries":0}`),
	)
	srv.handleComplete(httptest.NewRecorder(), req)

	m := srv.metrics["groq"]
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.requestsTotal != 1 || m.successTotal != 0 || m.errorTotal != 1 {
		t.Fatalf("unexpected metrics after error: req=%d ok=%d err=%d", m.requestsTotal, m.successTotal, m.errorTotal)
	}
	if m.lastErrorAt.IsZero() {
		t.Fatal("expected lastErrorAt to be set")
	}
	if m.lastErrorDetail == "" {
		t.Fatal("expected lastErrorDetail to be set")
	}
}

func TestHandleCompleteRecordsRateLimitMetric(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
	}))
	defer upstream.Close()

	srv := &server{
		cfg:     config{GroqAPIKey: "groq-key", GroqURL: upstream.URL},
		client:  upstream.Client(),
		metrics: newMetrics(),
	}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/complete",
		strings.NewReader(`{"provider":"groq","model":"llama","messages":[{"role":"user","content":"hi"}],"max_retries":0}`),
	)
	srv.handleComplete(httptest.NewRecorder(), req)

	m := srv.metrics["groq"]
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.rateLimitTotal != 1 {
		t.Fatalf("expected rate_limit_total=1, got %d", m.rateLimitTotal)
	}
}

func TestHandleStatusIncludesMetrics(t *testing.T) {
	srv := &server{
		cfg:     config{GroqAPIKey: "groq-key"},
		client:  http.DefaultClient,
		metrics: newMetrics(),
	}
	srv.metrics["groq"].requestsTotal = 5
	srv.metrics["groq"].successTotal = 4
	srv.metrics["groq"].errorTotal = 1
	srv.metrics["groq"].rateLimitTotal = 1
	srv.metrics["groq"].lastLatencyMs = 340

	req := httptest.NewRequest(http.MethodGet, "/v1/status", nil)
	rec := httptest.NewRecorder()
	srv.handleStatus(rec, req)

	body := rec.Body.String()
	if !strings.Contains(body, `"requests_total":5`) {
		t.Fatalf("expected requests_total in status: %s", body)
	}
	if !strings.Contains(body, `"success_total":4`) {
		t.Fatalf("expected success_total in status: %s", body)
	}
	if !strings.Contains(body, `"rate_limit_total":1`) {
		t.Fatalf("expected rate_limit_total in status: %s", body)
	}
	if !strings.Contains(body, `"last_latency_ms":340`) {
		t.Fatalf("expected last_latency_ms in status: %s", body)
	}
	if strings.Contains(body, "groq-key") {
		t.Fatalf("status response must not leak API key: %s", body)
	}
}

func TestStructuredOpenRouterResponseUsesChatCompletionsInstruction(t *testing.T) {
	var captured map[string]any
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewDecoder(r.Body).Decode(&captured)
		writeJSON(w, http.StatusOK, map[string]any{
			"choices": []any{map[string]any{"message": map[string]any{"content": `{"ok":true}`}}},
		})
	}))
	defer upstream.Close()

	srv := &server{
		cfg:    config{OpenRouterAPIKey: "or-key", AppURL: "http://app.test", OpenRouterURL: upstream.URL},
		client: upstream.Client(),
	}
	result, err := srv.complete(context.Background(), completeRequest{
		Provider: "openrouter",
		Model:    "openrouter/free",
		Messages: []message{{Role: "user", Content: "hello"}},
		Tool: map[string]any{"function": map[string]any{
			"name":       "submit_result",
			"parameters": map[string]any{"type": "object"},
		}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Text != `{"ok":true}` {
		t.Fatalf("unexpected result: %#v", result)
	}
	messages := captured["messages"].([]any)
	last := messages[len(messages)-1].(map[string]any)
	if !strings.Contains(last["content"].(string), "Return only valid JSON") {
		t.Fatalf("expected structured instruction: %#v", messages)
	}
	provider := captured["provider"].(map[string]any)
	if provider["allow_fallbacks"] != false {
		t.Fatalf("expected OpenRouter fallbacks disabled: %#v", captured)
	}
}
