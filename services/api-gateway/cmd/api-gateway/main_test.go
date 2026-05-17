package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"strings"
	"testing"
)

func TestGatewayRouting(t *testing.T) {
	// 1. Setup mock backends
	backendServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Mock-Source", "backend")
		w.Header().Set("X-Mock-Path", r.URL.Path)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("backend-response"))
	}))
	defer backendServer.Close()

	mediaServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Mock-Source", "media")
		w.Header().Set("X-Mock-Path", r.URL.Path)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("media-response"))
	}))
	defer mediaServer.Close()

	authServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Mock-Source", "auth")
		w.Header().Set("X-Mock-Path", r.URL.Path)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("auth-response"))
	}))
	defer authServer.Close()

	// 2. Parse mock URLs
	backendURL, _ := url.Parse(backendServer.URL)
	mediaURL, _ := url.Parse(mediaServer.URL)
	authURL, _ := url.Parse(authServer.URL)

	// 3. Initialize gateway server
	srv := &server{
		backendProxy: httputil.NewSingleHostReverseProxy(backendURL),
		mediaProxy:   httputil.NewSingleHostReverseProxy(mediaURL),
		authProxy:    httputil.NewSingleHostReverseProxy(authURL),
	}

	tests := []struct {
		name           string
		method         string
		path           string
		expectedSource string
		expectedPath   string
		expectedBody   string
	}{
		{
			name:           "Health Check",
			method:         "GET",
			path:           "/health",
			expectedSource: "", // Server itself handles health checks
			expectedPath:   "",
			expectedBody:   `{"service":"api-gateway","status":"ok"}`,
		},
		{
			name:           "TTS POST Rewrite",
			method:         "POST",
			path:           "/api/v1/tts",
			expectedSource: "media",
			expectedPath:   "/v1/tts",
			expectedBody:   "media-response",
		},
		{
			name:           "TTS GET Fallback",
			method:         "GET",
			path:           "/api/v1/tts",
			expectedSource: "backend",
			expectedPath:   "/api/v1/tts",
			expectedBody:   "backend-response",
		},
		{
			name:           "STT POST Rewrite",
			method:         "POST",
			path:           "/api/v1/stt",
			expectedSource: "media",
			expectedPath:   "/v1/stt",
			expectedBody:   "media-response",
		},
		{
			name:           "Interview Recording Upload goes to backend",
			method:         "POST",
			path:           "/api/v1/interviews/93a73297-b0f5-4624-b2d5-f2a2b4c03db3/recording",
			expectedSource: "backend",
			expectedPath:   "/api/v1/interviews/93a73297-b0f5-4624-b2d5-f2a2b4c03db3/recording",
			expectedBody:   "backend-response",
		},
		{
			name:           "Resume Upload goes to backend",
			method:         "POST",
			path:           "/api/v1/candidate/resume/upload",
			expectedSource: "backend",
			expectedPath:   "/api/v1/candidate/resume/upload",
			expectedBody:   "backend-response",
		},
		{
			name:           "Auth Login rewrites to auth-service",
			method:         "POST",
			path:           "/api/v1/auth/login",
			expectedSource: "auth",
			expectedPath:   "/api/v1/auth/login",
			expectedBody:   "auth-response",
		},
		{
			name:           "Candidates GET Fallback",
			method:         "GET",
			path:           "/api/v1/company/candidates",
			expectedSource: "backend",
			expectedPath:   "/api/v1/company/candidates",
			expectedBody:   "backend-response",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(tt.method, tt.path, nil)
			w := httptest.NewRecorder()

			if tt.path == "/health" {
				srv.handleHealth(w, req)
			} else {
				srv.handleProxy(w, req)
			}

			resp := w.Result()
			defer resp.Body.Close()

			bodyBytes, _ := io.ReadAll(resp.Body)
			bodyStr := strings.TrimSpace(string(bodyBytes))

			if bodyStr != tt.expectedBody {
				t.Errorf("expected body %q, got %q", tt.expectedBody, bodyStr)
			}

			if tt.expectedSource != "" {
				source := resp.Header.Get("X-Mock-Source")
				if source != tt.expectedSource {
					t.Errorf("expected source %q, got %q", tt.expectedSource, source)
				}

				mockPath := resp.Header.Get("X-Mock-Path")
				if mockPath != tt.expectedPath {
					t.Errorf("expected rewritten path %q, got %q", tt.expectedPath, mockPath)
				}
			}
		})
	}
}
