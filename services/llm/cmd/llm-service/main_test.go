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
