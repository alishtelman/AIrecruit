package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"strings"
	"testing"
)

func TestHandleRunPythonReturnsRunnerChecks(t *testing.T) {
	srv := &server{
		run: func(ctx context.Context, req runRequest) (runResponse, error) {
			score := 10.0
			return runResponse{
				RunnerScore: &score,
				RunnerChecks: []runnerCheck{
					{CheckKey: "runner_blocks_over_limit", Passed: true, Details: "ok"},
				},
			}, nil
		},
	}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/coding/python",
		strings.NewReader(`{"scenario_id":"rate_limiter_window_counter","language":"python","code":"def allow_request(): pass"}`),
	)
	rec := httptest.NewRecorder()

	srv.handleRunPython(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "runner_blocks_over_limit") {
		t.Fatalf("expected runner check in response: %s", rec.Body.String())
	}
}

func TestHandleRunPythonRejectsUnsupportedScenario(t *testing.T) {
	srv := &server{run: func(ctx context.Context, req runRequest) (runResponse, error) {
		t.Fatal("runner should not be called")
		return runResponse{}, nil
	}}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/coding/python",
		strings.NewReader(`{"scenario_id":"unknown","language":"python","code":"print(1)"}`),
	)
	rec := httptest.NewRecorder()

	srv.handleRunPython(rec, req)

	if rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected status 422, got %d", rec.Code)
	}
}

func TestHandleValidateSQLReturnsValidationChecks(t *testing.T) {
	srv := &server{
		validate: func(ctx context.Context, req sqlValidationRequest) (sqlValidationResponse, error) {
			score := 10.0
			return sqlValidationResponse{
				ValidationScore: &score,
				ValidationChecks: []sqlValidationCheck{
					{CheckKey: "expected_rows", Status: "passed", Score: 10.0, Evidence: "ok"},
				},
			}, nil
		},
	}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/sql/validate",
		strings.NewReader(`{"scenario_id":"customer_revenue_rollup","query":"select 1"}`),
	)
	rec := httptest.NewRecorder()

	srv.handleValidateSQL(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "expected_rows") {
		t.Fatalf("expected validation check in response: %s", rec.Body.String())
	}
}

func TestHandleValidateSQLRejectsUnsupportedScenario(t *testing.T) {
	srv := &server{validate: func(ctx context.Context, req sqlValidationRequest) (sqlValidationResponse, error) {
		t.Fatal("validator should not be called")
		return sqlValidationResponse{}, nil
	}}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/sql/validate",
		strings.NewReader(`{"scenario_id":"unknown","query":"select 1"}`),
	)
	rec := httptest.NewRecorder()

	srv.handleValidateSQL(rec, req)

	if rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected status 422, got %d", rec.Code)
	}
}

func TestRunPythonExecutesRateLimiterChecks(t *testing.T) {
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("python3 is not available")
	}
	srv := &server{pythonBin: "python3"}
	code := `from collections import defaultdict, deque
windows = defaultdict(deque)
def allow_request(user_id: str, now: int, limit: int = 5, window_seconds: int = 60) -> bool:
    queue = windows[user_id]
    while queue and now - queue[0] >= window_seconds:
        queue.popleft()
    if len(queue) >= limit:
        return False
    queue.append(now)
    return True
`

	result, err := srv.runPython(context.Background(), runRequest{
		ScenarioID:     "rate_limiter_window_counter",
		Language:       "python",
		Code:           code,
		TimeoutSeconds: 2,
	})

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.RunnerScore == nil || *result.RunnerScore != 10.0 {
		t.Fatalf("unexpected score: %v", result.RunnerScore)
	}
	if len(result.RunnerChecks) != 4 {
		t.Fatalf("unexpected checks: %#v", result.RunnerChecks)
	}
}

func TestValidateSQLExecutesScenarioChecks(t *testing.T) {
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("python3 is not available")
	}
	srv := &server{pythonBin: "python3"}
	query := `SELECT
    c.name AS customer_name,
    COUNT(o.id) AS completed_order_count,
    SUM(o.total_amount) AS completed_revenue
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE c.is_active = 1
  AND o.status = 'completed'
  AND o.created_at >= '2024-03-01'
  AND o.created_at < '2024-04-01'
GROUP BY c.id, c.name
ORDER BY completed_revenue DESC`

	result, err := srv.validateSQL(context.Background(), sqlValidationRequest{
		ScenarioID:     "customer_revenue_rollup",
		Query:          query,
		TimeoutSeconds: 2,
	})

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.ValidationScore == nil || *result.ValidationScore != 10.0 {
		body, _ := json.Marshal(result)
		t.Fatalf("unexpected score: %v payload=%s", result.ValidationScore, body)
	}
	if len(result.ValidationChecks) != 4 {
		t.Fatalf("unexpected checks: %#v", result.ValidationChecks)
	}
}
