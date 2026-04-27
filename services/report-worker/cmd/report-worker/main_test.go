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

func TestWorkerStateSnapshotTracksLastTick(t *testing.T) {
	state := &workerState{startedAt: time.Now().UTC()}
	state.recordTick(tickResponse{Processed: true, InterviewID: "abc"}, nil)

	snapshot := state.snapshot()

	if snapshot["status"] != "ok" {
		t.Fatalf("unexpected status: %v", snapshot["status"])
	}
	if snapshot["last_interview_id"] != "abc" {
		t.Fatalf("unexpected interview id: %v", snapshot["last_interview_id"])
	}
	if snapshot["last_error"] != "" {
		t.Fatalf("unexpected error: %v", snapshot["last_error"])
	}
}
