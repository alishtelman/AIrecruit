package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

type server struct {
	backendProxy *httputil.ReverseProxy
	mediaProxy   *httputil.ReverseProxy
}

func main() {
	log.Println("Starting AI Recruiting API Gateway...")

	listenAddr := envOrDefault("API_GATEWAY_ADDR", ":8080")
	backendURL := parseURL(envOrDefault("BACKEND_URL", "http://backend:8000"))
	mediaURL := parseURL(envOrDefault("MEDIA_SERVICE_URL", "http://media-service:8080"))

	log.Printf("Routing Configured:")
	log.Printf("  Listen Address: %s", listenAddr)
	log.Printf("  Backend URL:    %s", backendURL)
	log.Printf("  Media URL:      %s", mediaURL)

	srv := &server{
		backendProxy: httputil.NewSingleHostReverseProxy(backendURL),
		mediaProxy:   httputil.NewSingleHostReverseProxy(mediaURL),
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", srv.handleHealth)
	mux.HandleFunc("/", srv.handleProxy)

	httpServer := &http.Server{
		Addr:    listenAddr,
		Handler: mux,
	}

	go func() {
		log.Printf("API Gateway listening on %s", listenAddr)
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("Listen and serve error: %v", err)
		}
	}()

	// Graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Println("Shutting down API Gateway...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := httpServer.Shutdown(ctx); err != nil {
		log.Fatalf("Graceful shutdown failed: %v", err)
	}
	log.Println("API Gateway stopped.")
}

func (s *server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"service":"api-gateway","status":"ok"}`))
}

func (s *server) handleProxy(w http.ResponseWriter, r *http.Request) {
	path := r.URL.Path
	method := r.Method

	// Proxy stateless media operations directly to Go sidecar
	if method == "POST" && path == "/api/v1/tts" {
		r.URL.Path = "/v1/tts"
		log.Printf("[PROXY] POST %s -> media-service %s", path, r.URL.Path)
		s.mediaProxy.ServeHTTP(w, r)
		return
	}

	if method == "POST" && path == "/api/v1/stt" {
		r.URL.Path = "/v1/stt"
		log.Printf("[PROXY] POST %s -> media-service %s", path, r.URL.Path)
		s.mediaProxy.ServeHTTP(w, r)
		return
	}

	// Default fallback to core backend orchestrator
	log.Printf("[PROXY] %s %s -> backend %s", method, path, r.URL.Path)
	s.backendProxy.ServeHTTP(w, r)
}

func envOrDefault(key string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value
}

func parseURL(raw string) *url.URL {
	u, err := url.Parse(raw)
	if err != nil {
		log.Fatalf("Failed to parse URL %q: %v", raw, err)
	}
	return u
}
