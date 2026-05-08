package main

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestRunTickProcessesInterview(t *testing.T) {
	var gotToken string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotToken = r.Header.Get("X-Internal-Worker-Token")
		if r.URL.Path != "/api/v1/internal/report-worker/tick" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"processed":true,"interview_id":"abc"}`))
	}))
	defer server.Close()

	processed, err := runTick(
		context.Background(),
		server.Client(),
		config{BackendURL: server.URL, Token: "secret", Timeout: time.Second},
	)

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !processed.Processed {
		t.Fatal("expected processed tick")
	}
	if processed.InterviewID != "abc" {
		t.Fatalf("unexpected interview id: %q", processed.InterviewID)
	}
	if gotToken != "secret" {
		t.Fatalf("unexpected worker token: %q", gotToken)
	}
}

func TestRunTickAddsDryRunQuery(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.RawQuery != "dry_run=true" {
			t.Fatalf("expected dry_run query, got %q", r.URL.RawQuery)
		}
		_, _ = w.Write([]byte(`{"processed":false,"interview_id":"candidate","dry_run":true,"pending_count":3}`))
	}))
	defer server.Close()

	result, err := runTick(
		context.Background(),
		server.Client(),
		config{BackendURL: server.URL, Token: "secret", Timeout: time.Second, DryRun: true},
	)

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.DryRun || result.InterviewID != "candidate" || result.PendingCount != 3 {
		t.Fatalf("unexpected dry-run result: %#v", result)
	}
}

func TestRunTickReturnsBackendErrors(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "forbidden", http.StatusForbidden)
	}))
	defer server.Close()

	processed, err := runTick(
		context.Background(),
		server.Client(),
		config{BackendURL: server.URL, Token: "secret", Timeout: time.Second},
	)

	if err == nil {
		t.Fatal("expected error")
	}
	if processed.Processed {
		t.Fatal("expected unprocessed tick")
	}
}

func TestRunCycleHonorsMaxJobsPerCycle(t *testing.T) {
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		_, _ = w.Write([]byte(`{"processed":true,"interview_id":"abc"}`))
	}))
	defer server.Close()

	state := &workerState{startedAt: time.Now().UTC(), maxJobsPerCycle: 2}
	ticks := runCycle(
		context.Background(),
		server.Client(),
		config{BackendURL: server.URL, Token: "secret", Timeout: time.Second, MaxJobsPerCycle: 2},
		state,
	)

	if ticks != 2 || calls != 2 {
		t.Fatalf("expected two ticks, got ticks=%d calls=%d", ticks, calls)
	}
	if state.snapshot()["processed_total"] != int64(2) {
		t.Fatalf("unexpected processed total: %#v", state.snapshot())
	}
}

func TestRunCycleStopsAfterDryRunCandidate(t *testing.T) {
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		_, _ = w.Write([]byte(`{"processed":false,"interview_id":"candidate","dry_run":true,"pending_count":5}`))
	}))
	defer server.Close()

	state := &workerState{startedAt: time.Now().UTC(), dryRun: true, maxJobsPerCycle: 5}
	ticks := runCycle(
		context.Background(),
		server.Client(),
		config{BackendURL: server.URL, Token: "secret", Timeout: time.Second, DryRun: true, MaxJobsPerCycle: 5},
		state,
	)

	snapshot := state.snapshot()
	if ticks != 1 || calls != 1 {
		t.Fatalf("expected one dry-run tick, got ticks=%d calls=%d", ticks, calls)
	}
	if snapshot["last_candidate_interview_id"] != "candidate" || snapshot["last_pending_count"] != 5 {
		t.Fatalf("unexpected snapshot: %#v", snapshot)
	}
}

func TestRunTickReturnsRateLimitErrorOn429(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Retry-After", "90")
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = w.Write([]byte("rate limited"))
	}))
	defer server.Close()

	_, err := runTick(
		context.Background(),
		server.Client(),
		config{BackendURL: server.URL, Token: "secret", Timeout: time.Second},
	)

	if err == nil {
		t.Fatal("expected error on 429")
	}
	var rl *rateLimitError
	if !errors.As(err, &rl) {
		t.Fatalf("expected rateLimitError, got %T: %v", err, err)
	}
	if rl.RetryAfter != 90*time.Second {
		t.Fatalf("expected 90s retry-after, got %s", rl.RetryAfter)
	}
}

func TestRunTickUsesDefaultRetryAfterWhenHeaderMissing(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
	}))
	defer server.Close()

	_, err := runTick(
		context.Background(),
		server.Client(),
		config{BackendURL: server.URL, Token: "secret", Timeout: time.Second},
	)

	var rl *rateLimitError
	if !errors.As(err, &rl) {
		t.Fatalf("expected rateLimitError, got %T: %v", err, err)
	}
	if rl.RetryAfter != defaultRateLimitBackoff {
		t.Fatalf("expected default backoff %s, got %s", defaultRateLimitBackoff, rl.RetryAfter)
	}
}

func TestRunCycleSkipsWhenBackingOff(t *testing.T) {
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		_, _ = w.Write([]byte(`{"processed":true,"interview_id":"abc"}`))
	}))
	defer server.Close()

	state := &workerState{
		startedAt:    time.Now().UTC(),
		backoffUntil: time.Now().UTC().Add(10 * time.Minute),
	}
	ticks := runCycle(
		context.Background(),
		server.Client(),
		config{BackendURL: server.URL, Token: "secret", Timeout: time.Second, MaxJobsPerCycle: 5},
		state,
	)

	if ticks != 0 || calls != 0 {
		t.Fatalf("expected zero ticks during backoff, got ticks=%d calls=%d", ticks, calls)
	}
}

func TestRecordTickBacksOffOnRateLimit(t *testing.T) {
	state := &workerState{startedAt: time.Now().UTC()}
	state.recordTick(tickResponse{}, &rateLimitError{RetryAfter: 2 * time.Minute})

	snap := state.snapshot()
	if snap["backoff_until"] == "" {
		t.Fatal("expected backoff_until to be set after rate limit error")
	}
	if snap["consecutive_errors"] != 0 {
		t.Fatalf("consecutive_errors should reset on rate limit, got %v", snap["consecutive_errors"])
	}
	if state.backoffRemaining() <= 0 {
		t.Fatal("expected positive backoff remaining")
	}
}

func TestRecordTickBacksOffAfterConsecutiveErrors(t *testing.T) {
	state := &workerState{startedAt: time.Now().UTC()}
	genericErr := context.Canceled

	for i := 0; i < consecutiveErrorThreshold-1; i++ {
		state.recordTick(tickResponse{}, genericErr)
		if state.backoffRemaining() > 0 {
			t.Fatalf("no backoff expected before threshold at error %d", i+1)
		}
	}
	state.recordTick(tickResponse{}, genericErr)
	if state.backoffRemaining() <= 0 {
		t.Fatal("expected backoff after reaching consecutive error threshold")
	}
	if snap := state.snapshot(); snap["consecutive_errors"].(int) != consecutiveErrorThreshold {
		t.Fatalf("expected consecutive_errors=%d, got %v", consecutiveErrorThreshold, snap["consecutive_errors"])
	}
}

func TestRecordTickClearsBackoffOnSuccess(t *testing.T) {
	state := &workerState{
		startedAt:    time.Now().UTC(),
		backoffUntil: time.Now().UTC().Add(10 * time.Minute),
		consecutiveErrors: 5,
	}
	state.recordTick(tickResponse{Processed: false}, nil)

	if state.backoffRemaining() > 0 {
		t.Fatal("expected backoff cleared after successful tick")
	}
	if snap := state.snapshot(); snap["consecutive_errors"] != 0 {
		t.Fatalf("expected consecutive_errors reset, got %v", snap["consecutive_errors"])
	}
}

func TestRecordTickTracksOldestPendingAt(t *testing.T) {
	state := &workerState{startedAt: time.Now().UTC()}
	state.recordTick(tickResponse{
		Processed:              false,
		PendingCount:           3,
		OldestPendingUpdatedAt: "2026-05-01T10:00:00Z",
	}, nil)

	snap := state.snapshot()
	if snap["oldest_pending_updated_at"] != "2026-05-01T10:00:00Z" {
		t.Fatalf("expected oldest_pending_updated_at to be tracked, got %v", snap["oldest_pending_updated_at"])
	}
}

func TestWorkerStateSnapshotTracksLastTick(t *testing.T) {
	state := &workerState{startedAt: time.Now().UTC(), dryRun: true, maxJobsPerCycle: 3}
	state.recordTick(tickResponse{Processed: true, InterviewID: "abc"}, nil)
	state.recordTick(tickResponse{Processed: false, InterviewID: "candidate", DryRun: true, PendingCount: 4}, nil)
	state.recordTick(tickResponse{}, context.Canceled)

	snapshot := state.snapshot()

	if snapshot["status"] != "ok" {
		t.Fatalf("unexpected status: %v", snapshot["status"])
	}
	if snapshot["last_interview_id"] != "abc" {
		t.Fatalf("unexpected interview id: %v", snapshot["last_interview_id"])
	}
	if snapshot["dry_run"] != true || snapshot["max_jobs_per_cycle"] != 3 {
		t.Fatalf("unexpected worker config in snapshot: %#v", snapshot)
	}
	if snapshot["last_candidate_interview_id"] != "candidate" || snapshot["last_pending_count"] != 4 {
		t.Fatalf("unexpected backlog state: %#v", snapshot)
	}
	if snapshot["processed_total"] != int64(1) || snapshot["error_total"] != int64(1) {
		t.Fatalf("unexpected counters: %#v", snapshot)
	}
	if snapshot["last_error"] == "" {
		t.Fatalf("expected error in snapshot: %#v", snapshot)
	}
}
