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
	backendProxy     *httputil.ReverseProxy
	mediaProxy       *httputil.ReverseProxy
	authProxy        *httputil.ReverseProxy
	templatesProxy   *httputil.ReverseProxy
	marketplaceProxy *httputil.ReverseProxy
	resumeProxy      *httputil.ReverseProxy
	dialogProxy      *httputil.ReverseProxy
}

func main() {
	log.Println("Starting AI Recruiting API Gateway...")

	listenAddr := envOrDefault("API_GATEWAY_ADDR", ":8080")
	backendURL := parseURL(envOrDefault("BACKEND_URL", "http://backend:8000"))
	mediaURL := parseURL(envOrDefault("MEDIA_SERVICE_URL", "http://media-service:8080"))
	authURL := parseURL(envOrDefault("AUTH_SERVICE_URL", "http://auth-service:8080"))
	templatesURL := parseURL(envOrDefault("TEMPLATES_SERVICE_URL", "http://templates-service:8080"))
	marketplaceURL := parseURL(envOrDefault("MARKETPLACE_SERVICE_URL", "http://marketplace-service:8080"))
	resumeURL := parseURL(envOrDefault("RESUME_SERVICE_URL", "http://resume-service:8080"))
	dialogURL := parseURL(envOrDefault("DIALOG_SERVICE_URL", "http://dialog-service:8080"))

	log.Printf("Routing Configured:")
	log.Printf("  Listen Address: %s", listenAddr)
	log.Printf("  Backend URL:    %s", backendURL)
	log.Printf("  Media URL:      %s", mediaURL)
	log.Printf("  Auth URL:       %s", authURL)
	log.Printf("  Templates URL:  %s", templatesURL)
	log.Printf("  Marketplace URL: %s", marketplaceURL)
	log.Printf("  Resume URL:     %s", resumeURL)
	log.Printf("  Dialog URL:     %s", dialogURL)

	srv := &server{
		backendProxy:     newReverseProxy(backendURL),
		mediaProxy:       newReverseProxy(mediaURL),
		authProxy:        newReverseProxy(authURL),
		templatesProxy:   newReverseProxy(templatesURL),
		marketplaceProxy: newReverseProxy(marketplaceURL),
		resumeProxy:      newReverseProxy(resumeURL),
		dialogProxy:      newReverseProxy(dialogURL),
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", srv.handleHealth)
	mux.HandleFunc("/", srv.handleProxy)

	corsHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" {
			w.Header().Set("Access-Control-Allow-Origin", origin)
		} else {
			w.Header().Set("Access-Control-Allow-Origin", "http://localhost:3000")
		}
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, Accept")
		w.Header().Set("Access-Control-Allow-Credentials", "true")

		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}

		mux.ServeHTTP(w, r)
	})

	httpServer := &http.Server{
		Addr:    listenAddr,
		Handler: corsHandler,
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

	// Proxy auth operations directly to Go auth-service
	if strings.HasPrefix(path, "/api/v1/auth") {
		log.Printf("[PROXY] %s %s -> auth-service %s", method, path, r.URL.Path)
		s.authProxy.ServeHTTP(w, r)
		return
	}

	// Proxy templates operations directly to Go templates-service
	if strings.HasPrefix(path, "/api/v1/company/templates") || path == "/api/v1/interviews/templates/public" {
		log.Printf("[PROXY] %s %s -> templates-service %s", method, path, r.URL.Path)
		s.templatesProxy.ServeHTTP(w, r)
		return
	}

	// Proxy shortlist operations directly to Go marketplace-service
	if strings.HasPrefix(path, "/api/v1/company/shortlists") {
		r.URL.Path = strings.Replace(path, "/api", "", 1)
		log.Printf("[PROXY] %s %s -> marketplace-service %s", method, path, r.URL.Path)
		s.marketplaceProxy.ServeHTTP(w, r)
		return
	}

	// Proxy candidate privacy, salary, and access-request operations directly to Go marketplace-service
	if strings.HasPrefix(path, "/api/v1/candidate/salary") || 
	   strings.HasPrefix(path, "/api/v1/candidate/privacy") || 
	   strings.HasPrefix(path, "/api/v1/candidate/access-requests") || 
	   strings.HasPrefix(path, "/api/v1/candidate/share/") || 
	   strings.HasPrefix(path, "/api/v1/company/share-links/") {
		r.URL.Path = strings.Replace(path, "/api", "", 1)
		log.Printf("[PROXY] %s %s -> marketplace-service %s", method, path, r.URL.Path)
		s.marketplaceProxy.ServeHTTP(w, r)
		return
	}

	// Proxy candidate resume operations and stats directly to Go resume-service
	if strings.HasPrefix(path, "/api/v1/candidate/resume") || path == "/api/v1/candidate/stats" {
		r.URL.Path = strings.Replace(path, "/api", "", 1)
		log.Printf("[PROXY] %s %s -> resume-service %s", method, path, r.URL.Path)
		s.resumeProxy.ServeHTTP(w, r)
		return
	}

	// Proxy behavioral proctoring signals & recording uploads directly to resume-service in Go
	if method == "POST" && strings.HasPrefix(path, "/api/v1/interviews/") && (strings.HasSuffix(path, "/signals") || strings.HasSuffix(path, "/recording")) {
		r.URL.Path = strings.Replace(path, "/api", "", 1)
		log.Printf("[PROXY] %s %s -> resume-service %s", method, path, r.URL.Path)
		s.resumeProxy.ServeHTTP(w, r)
		return
	}

	// Proxy interview/dialog engine operations directly to Go dialog-service
	if strings.HasPrefix(path, "/api/v1/interviews") {
		log.Printf("[PROXY] %s %s -> dialog-service %s", method, path, r.URL.Path)
		s.dialogProxy.ServeHTTP(w, r)
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

func newReverseProxy(target *url.URL) *httputil.ReverseProxy {
	p := httputil.NewSingleHostReverseProxy(target)
	p.ModifyResponse = func(res *http.Response) error {
		res.Header.Del("Access-Control-Allow-Origin")
		res.Header.Del("Access-Control-Allow-Credentials")
		res.Header.Del("Access-Control-Allow-Methods")
		res.Header.Del("Access-Control-Allow-Headers")
		res.Header.Del("Access-Control-Expose-Headers")
		return nil
	}
	return p
}
