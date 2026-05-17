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

func TestHandleStatusReturnsSafeDiagnostics(t *testing.T) {
	srv := &server{pythonBin: "/secret/python"}
	req := httptest.NewRequest(http.MethodGet, "/v1/status", nil)
	rec := httptest.NewRecorder()

	srv.handleStatus(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", rec.Code, rec.Body.String())
	}
	body := rec.Body.String()
	if strings.Contains(body, "/secret/python") {
		t.Fatalf("status leaked python path: %s", body)
	}
	var payload statusResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.Service != "sandbox-service" || payload.PythonAvailable {
		t.Fatalf("unexpected runtime status: %#v", payload)
	}
	if payload.DefaultTimeoutSeconds != defaultTimeoutSeconds || payload.MaxTimeoutSeconds != maxTimeoutSeconds {
		t.Fatalf("unexpected timeout limits: %#v", payload)
	}
	if len(payload.SupportedCodingScenarios) != 4 || payload.SupportedCodingScenarios[0] != "deployment_rollout_guard" {
		t.Fatalf("unexpected coding scenarios: %#v", payload.SupportedCodingScenarios)
	}
	if len(payload.SupportedSQLScenarios) != 3 || payload.SupportedSQLScenarios[0] != "customer_revenue_rollup" {
		t.Fatalf("unexpected sql scenarios: %#v", payload.SupportedSQLScenarios)
	}
}

func TestHandleHealthReportsRuntimeAndScenarioCounts(t *testing.T) {
	srv := &server{pythonBin: "python3"}
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()

	srv.handleHealth(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), `"coding_scenarios_count":4`) {
		t.Fatalf("expected coding scenario count: %s", rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), `"sql_scenarios_count":3`) {
		t.Fatalf("expected sql scenario count: %s", rec.Body.String())
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

func TestRunPythonExecutesFeatureFreshnessChecks(t *testing.T) {
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("python3 is not available")
	}
	srv := &server{pythonBin: "python3"}
	code := `def evaluate_feature_freshness(record, now_ts, max_age_seconds=3600):
    age = record.get("feature_age_seconds")
    features = record.get("features", {})
    fallback = record.get("fallback_features", {})
    if age is None or age > max_age_seconds:
        return {"allowed": False, "reason": "feature data is stale"}
    used_fallback = False
    risk_score = features.get("risk_score")
    if risk_score is None:
        risk_score = fallback.get("risk_score")
        used_fallback = True
    if risk_score is None:
        return {"allowed": False, "reason": "risk_score is missing"}
    return {"allowed": True, "used_fallback": used_fallback, "reason": "fresh enough for scoring"}
`

	result, err := srv.runPython(context.Background(), runRequest{
		ScenarioID:     "feature_freshness_monitor",
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

func TestRunPythonExecutesFlakyClassifierChecks(t *testing.T) {
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("python3 is not available")
	}
	srv := &server{pythonBin: "python3"}
	code := `from collections import defaultdict

def classify_flaky_tests(runs):
    groups = defaultdict(list)
    for item in runs:
        groups[item["test_id"]].append(item)
    flaky_tests = []
    stable_failures = []
    for test_id, items in groups.items():
        statuses = {item["status"] for item in items}
        if "failed" in statuses and "passed" in statuses:
            flaky_tests.append(test_id)
        elif statuses == {"failed"}:
            stable_failures.append(test_id)
    return {
        "groups": dict(groups),
        "flaky_tests": flaky_tests,
        "stable_failures": stable_failures,
        "summary": f"{len(flaky_tests)} flaky, {len(stable_failures)} stable failures",
    }
`

	result, err := srv.runPython(context.Background(), runRequest{
		ScenarioID:     "flaky_test_classifier",
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

func TestRunPythonExecutesDeploymentRolloutChecks(t *testing.T) {
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("python3 is not available")
	}
	srv := &server{pythonBin: "python3"}
	code := `def evaluate_rollout_health(snapshot):
    error_rate = snapshot.get("error_rate", 0)
    latency = snapshot.get("latency_p95_ms", 0)
    burn = snapshot.get("slo_burn_rate", 0)
    has_critical = any(item.get("severity") == "critical" for item in snapshot.get("alerts", []))
    if has_critical or error_rate >= 0.05 or latency >= 1000 or burn >= 4:
        return {"action": "rollback", "reason": "critical rollout health regression"}
    if error_rate >= 0.01 or latency >= 400 or burn >= 1.5:
        return {"action": "pause", "reason": "degraded metrics require investigation"}
    return {"action": "continue", "reason": "canary metrics are healthy"}
`

	result, err := srv.runPython(context.Background(), runRequest{
		ScenarioID:     "deployment_rollout_guard",
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

func TestHandleRunPythonRecordsMetrics(t *testing.T) {
	srv := &server{
		run: func(ctx context.Context, req runRequest) (runResponse, error) {
			score := 10.0
			return runResponse{RunnerScore: &score, RunnerChecks: []runnerCheck{}}, nil
		},
	}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/coding/python",
		strings.NewReader(`{"scenario_id":"rate_limiter_window_counter","language":"python","code":"x=1"}`),
	)
	srv.handleRunPython(httptest.NewRecorder(), req)

	snap := srv.python.snapshot()
	if snap.RequestsTotal != 1 || snap.SuccessTotal != 1 || snap.ErrorTotal != 0 {
		t.Fatalf("unexpected python metrics: %+v", snap)
	}
}

func TestHandleValidateSQLRecordsMetrics(t *testing.T) {
	srv := &server{
		validate: func(ctx context.Context, req sqlValidationRequest) (sqlValidationResponse, error) {
			score := 10.0
			return sqlValidationResponse{ValidationScore: &score, ValidationChecks: []sqlValidationCheck{}}, nil
		},
	}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/sql/validate",
		strings.NewReader(`{"scenario_id":"customer_revenue_rollup","query":"SELECT 1"}`),
	)
	srv.handleValidateSQL(httptest.NewRecorder(), req)

	snap := srv.sql.snapshot()
	if snap.RequestsTotal != 1 || snap.SuccessTotal != 1 {
		t.Fatalf("unexpected sql metrics: %+v", snap)
	}
}

func TestSandboxStatusIncludesEndpointMetrics(t *testing.T) {
	srv := &server{pythonBin: "python3"}
	srv.python.requestsTotal = 5
	srv.python.successTotal = 4
	srv.sql.requestsTotal = 2

	status := srv.status()
	if status.PythonRunner.RequestsTotal != 5 || status.PythonRunner.SuccessTotal != 4 {
		t.Fatalf("unexpected python_runner metrics in status: %+v", status.PythonRunner)
	}
	if status.SQLValidator.RequestsTotal != 2 {
		t.Fatalf("unexpected sql_validator metrics in status: %+v", status.SQLValidator)
	}
}
