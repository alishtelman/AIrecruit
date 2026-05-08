package main

import (
	"context"
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
