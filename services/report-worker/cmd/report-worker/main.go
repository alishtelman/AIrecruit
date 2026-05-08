package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
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

const (
	defaultRateLimitBackoff    = 60 * time.Second
	consecutiveErrorThreshold  = 3
	consecutiveErrorBackoff    = 30 * time.Second
	maxConsecutiveErrorBackoff = 5 * time.Minute
)

type rateLimitError struct {
	RetryAfter time.Duration
}

func (e *rateLimitError) Error() string {
	return fmt.Sprintf("backend rate limited, retry after %s", e.RetryAfter)
}

type config struct {
	BackendURL      string
	Token           string
	Interval        time.Duration
	Timeout         time.Duration
	HealthAddr      string
	DryRun          bool
	MaxJobsPerCycle int
}

type tickResponse struct {
	Processed              bool   `json:"processed"`
	InterviewID            string `json:"interview_id"`
	DryRun                 bool   `json:"dry_run"`
	PendingCount           int    `json:"pending_count"`
	OldestPendingUpdatedAt string `json:"oldest_pending_updated_at"`
}

type workerState struct {
	mu                sync.RWMutex
	startedAt         time.Time
	dryRun            bool
	maxJobsPerCycle   int
	lastTickAt        time.Time
	lastSuccessAt     time.Time
	lastProcessedAt   time.Time
	lastInterviewID   string
	lastCandidateID   string
	lastPendingCount  int
	oldestPendingAt   string
	processedTotal    int64
	errorTotal        int64
	lastError         string
	consecutiveErrors int
	backoffUntil      time.Time
}

func main() {
	cfg := config{
		BackendURL:      strings.TrimRight(envOrDefault("BACKEND_INTERNAL_URL", "http://backend:8000"), "/"),
		Token:           strings.TrimSpace(os.Getenv("INTERNAL_WORKER_TOKEN")),
		Interval:        time.Duration(envIntOrDefault("REPORT_WORKER_INTERVAL_SECONDS", 5)) * time.Second,
		Timeout:         time.Duration(envIntOrDefault("REPORT_WORKER_REQUEST_TIMEOUT_SECONDS", 300)) * time.Second,
		HealthAddr:      envOrDefault("REPORT_WORKER_HEALTH_ADDR", ":8080"),
		DryRun:          envBoolOrDefault("REPORT_WORKER_DRY_RUN", false),
		MaxJobsPerCycle: envIntOrDefault("REPORT_WORKER_MAX_JOBS_PER_CYCLE", 1),
	}
	if cfg.Token == "" {
		log.Fatal("INTERNAL_WORKER_TOKEN is required")
	}

	client := &http.Client{Timeout: cfg.Timeout}
	state := &workerState{startedAt: time.Now().UTC(), dryRun: cfg.DryRun, maxJobsPerCycle: cfg.MaxJobsPerCycle}
	go serveHealth(cfg.HealthAddr, state)
	log.Printf(
		"report-worker started backend=%s interval=%s timeout=%s dry_run=%t max_jobs_per_cycle=%d",
		cfg.BackendURL,
		cfg.Interval,
		cfg.Timeout,
		cfg.DryRun,
		cfg.MaxJobsPerCycle,
	)

	for {
		runCycle(context.Background(), client, cfg, state)
		time.Sleep(cfg.Interval)
	}
}

func (s *workerState) backoffRemaining() time.Duration {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if s.backoffUntil.IsZero() {
		return 0
	}
	return time.Until(s.backoffUntil)
}

func runCycle(ctx context.Context, client *http.Client, cfg config, state *workerState) int {
	if rem := state.backoffRemaining(); rem > 0 {
		log.Printf("report-worker backing off for %s, skipping cycle", rem.Round(time.Second))
		return 0
	}
	limit := cfg.MaxJobsPerCycle
	if limit <= 0 {
		limit = 1
	}
	ticks := 0
	for ticks < limit {
		result, err := runTick(ctx, client, cfg)
		ticks++
		state.recordTick(result, err)
		if err != nil {
			log.Printf("report-worker tick failed: %v", err)
			break
		}
		if cfg.DryRun || !result.Processed {
			break
		}
	}
	return ticks
}

func runTick(ctx context.Context, client *http.Client, cfg config) (tickResponse, error) {
	endpoint := cfg.BackendURL + "/api/v1/internal/report-worker/tick"
	if cfg.DryRun {
		endpoint += "?dry_run=true"
	}
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		endpoint,
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
	if resp.StatusCode == http.StatusTooManyRequests {
		retryAfter := defaultRateLimitBackoff
		if ra := resp.Header.Get("Retry-After"); ra != "" {
			if secs, err2 := strconv.Atoi(ra); err2 == nil && secs > 0 {
				retryAfter = time.Duration(secs) * time.Second
			}
		}
		return tickResponse{}, &rateLimitError{RetryAfter: retryAfter}
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
	if result.PendingCount > 0 || err == nil {
		s.lastPendingCount = result.PendingCount
	}
	if result.OldestPendingUpdatedAt != "" {
		s.oldestPendingAt = result.OldestPendingUpdatedAt
	}
	if result.DryRun && result.InterviewID != "" {
		s.lastCandidateID = result.InterviewID
	}
	if err != nil {
		s.lastError = err.Error()
		s.errorTotal++
		var rl *rateLimitError
		if errors.As(err, &rl) {
			s.backoffUntil = now.Add(rl.RetryAfter)
			s.consecutiveErrors = 0
			log.Printf("report-worker rate limited, backoff until %s", s.backoffUntil.Format(time.RFC3339))
		} else {
			s.consecutiveErrors++
			if s.consecutiveErrors >= consecutiveErrorThreshold {
				backoff := time.Duration(s.consecutiveErrors-consecutiveErrorThreshold+1) * consecutiveErrorBackoff
				if backoff > maxConsecutiveErrorBackoff {
					backoff = maxConsecutiveErrorBackoff
				}
				s.backoffUntil = now.Add(backoff)
				log.Printf("report-worker %d consecutive errors, backoff until %s", s.consecutiveErrors, s.backoffUntil.Format(time.RFC3339))
			}
		}
		return
	}
	s.lastSuccessAt = now
	s.lastError = ""
	s.consecutiveErrors = 0
	s.backoffUntil = time.Time{}
	if result.Processed {
		if result.InterviewID != "" && result.InterviewID == s.lastInterviewID {
			log.Printf("report-worker warning: interview_id=%s was already the last processed; Python lock may be contended", result.InterviewID)
		}
		s.lastProcessedAt = now
		s.lastInterviewID = result.InterviewID
		s.processedTotal++
	}
}

func (s *workerState) snapshot() map[string]any {
	s.mu.RLock()
	defer s.mu.RUnlock()

	return map[string]any{
		"status":                      "ok",
		"service":                     "report-worker",
		"dry_run":                     s.dryRun,
		"max_jobs_per_cycle":          s.maxJobsPerCycle,
		"started_at":                  formatTime(s.startedAt),
		"last_tick_at":                formatTime(s.lastTickAt),
		"last_success_at":             formatTime(s.lastSuccessAt),
		"last_processed_at":           formatTime(s.lastProcessedAt),
		"last_interview_id":           s.lastInterviewID,
		"last_candidate_interview_id": s.lastCandidateID,
		"last_pending_count":          s.lastPendingCount,
		"oldest_pending_updated_at":   s.oldestPendingAt,
		"processed_total":             s.processedTotal,
		"error_total":                 s.errorTotal,
		"last_error":                  s.lastError,
		"consecutive_errors":          s.consecutiveErrors,
		"backoff_until":               formatTime(s.backoffUntil),
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

func envBoolOrDefault(key string, fallback bool) bool {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return fallback
	}
	return parsed
}
