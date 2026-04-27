package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

type config struct {
	BackendURL string
	Token      string
	Interval   time.Duration
	Timeout    time.Duration
	HealthAddr string
}

type tickResponse struct {
	Processed   bool   `json:"processed"`
	InterviewID string `json:"interview_id"`
}

type workerState struct {
	mu              sync.RWMutex
	startedAt       time.Time
	lastTickAt      time.Time
	lastSuccessAt   time.Time
	lastProcessedAt time.Time
	lastInterviewID string
	lastError       string
}

func main() {
	cfg := config{
		BackendURL: strings.TrimRight(envOrDefault("BACKEND_INTERNAL_URL", "http://backend:8000"), "/"),
		Token:      strings.TrimSpace(os.Getenv("INTERNAL_WORKER_TOKEN")),
		Interval:   time.Duration(envIntOrDefault("REPORT_WORKER_INTERVAL_SECONDS", 5)) * time.Second,
		Timeout:    time.Duration(envIntOrDefault("REPORT_WORKER_REQUEST_TIMEOUT_SECONDS", 300)) * time.Second,
		HealthAddr: envOrDefault("REPORT_WORKER_HEALTH_ADDR", ":8080"),
	}
	if cfg.Token == "" {
		log.Fatal("INTERNAL_WORKER_TOKEN is required")
	}

	client := &http.Client{Timeout: cfg.Timeout}
	state := &workerState{startedAt: time.Now().UTC()}
	go serveHealth(cfg.HealthAddr, state)
	log.Printf("report-worker started backend=%s interval=%s timeout=%s", cfg.BackendURL, cfg.Interval, cfg.Timeout)

	for {
		result, err := runTick(context.Background(), client, cfg)
		state.recordTick(result, err)
		if err != nil {
			log.Printf("report-worker tick failed: %v", err)
		}
		if !result.Processed {
			time.Sleep(cfg.Interval)
		}
	}
}

func runTick(ctx context.Context, client *http.Client, cfg config) (tickResponse, error) {
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		cfg.BackendURL+"/api/v1/internal/report-worker/tick",
		bytes.NewReader(nil),
	)
	if err != nil {
		return tickResponse{}, err
	}
	req.Header.Set("X-Internal-Worker-Token", cfg.Token)

	resp, err := client.Do(req)
	if err != nil {
		return tickResponse{}, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return tickResponse{}, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return tickResponse{}, fmt.Errorf("backend status %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}

	var payload tickResponse
	if err := json.Unmarshal(body, &payload); err != nil {
		return tickResponse{}, err
	}
	if payload.Processed {
		log.Printf("report-worker processed interview_id=%s", payload.InterviewID)
	}
	return payload, nil
}

func serveHealth(addr string, state *workerState) {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, state.snapshot())
	})
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Printf("report-worker health server stopped: %v", err)
	}
}

func (s *workerState) recordTick(result tickResponse, err error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now().UTC()
	s.lastTickAt = now
	if err != nil {
		s.lastError = err.Error()
		return
	}
	s.lastSuccessAt = now
	s.lastError = ""
	if result.Processed {
		s.lastProcessedAt = now
		s.lastInterviewID = result.InterviewID
	}
}

func (s *workerState) snapshot() map[string]any {
	s.mu.RLock()
	defer s.mu.RUnlock()

	return map[string]any{
		"status":            "ok",
		"service":           "report-worker",
		"started_at":        formatTime(s.startedAt),
		"last_tick_at":      formatTime(s.lastTickAt),
		"last_success_at":   formatTime(s.lastSuccessAt),
		"last_processed_at": formatTime(s.lastProcessedAt),
		"last_interview_id": s.lastInterviewID,
		"last_error":        s.lastError,
	}
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func formatTime(value time.Time) string {
	if value.IsZero() {
		return ""
	}
	return value.Format(time.RFC3339)
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
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}
