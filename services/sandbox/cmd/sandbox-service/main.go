package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"
)

const defaultTimeoutSeconds = 2

type runRequest struct {
	ScenarioID     string  `json:"scenario_id"`
	Language       string  `json:"language"`
	Code           string  `json:"code"`
	TimeoutSeconds float64 `json:"timeout_seconds"`
}

type sqlValidationRequest struct {
	ScenarioID     string  `json:"scenario_id"`
	Query          string  `json:"query"`
	TimeoutSeconds float64 `json:"timeout_seconds"`
}

type runnerCheck struct {
	CheckKey string `json:"check_key"`
	Passed   bool   `json:"passed"`
	Details  string `json:"details"`
}

type sqlValidationCheck struct {
	CheckKey string  `json:"check_key"`
	Status   string  `json:"status"`
	Score    float64 `json:"score"`
	Evidence string  `json:"evidence,omitempty"`
}

type runResponse struct {
	RunnerScore  *float64       `json:"runner_score"`
	RunnerChecks []runnerCheck  `json:"runner_checks"`
	Error        string         `json:"error,omitempty"`
	Raw          map[string]any `json:"-"`
}

type sqlValidationResponse struct {
	ValidationScore  *float64             `json:"validation_score"`
	ValidationChecks []sqlValidationCheck `json:"validation_checks"`
}

type server struct {
	pythonBin string
	run       func(context.Context, runRequest) (runResponse, error)
	validate  func(context.Context, sqlValidationRequest) (sqlValidationResponse, error)
}

func main() {
	srv := &server{pythonBin: envOrDefault("PYTHON_BIN", "python3")}
	srv.run = srv.runPython
	srv.validate = srv.validateSQL

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "service": "sandbox-service"})
	})
	mux.HandleFunc("POST /v1/coding/python", srv.handleRunPython)
	mux.HandleFunc("POST /v1/sql/validate", srv.handleValidateSQL)

	addr := envOrDefault("SANDBOX_SERVICE_ADDR", ":8080")
	if err := http.ListenAndServe(addr, mux); err != nil {
		panic(err)
	}
}

func (s *server) handleValidateSQL(w http.ResponseWriter, r *http.Request) {
	var payload sqlValidationRequest
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid JSON body")
		return
	}
	payload.ScenarioID = strings.TrimSpace(payload.ScenarioID)
	payload.Query = strings.TrimSpace(payload.Query)
	if payload.Query == "" {
		writeError(w, http.StatusUnprocessableEntity, "query cannot be empty")
		return
	}
	if !isSupportedSQLScenario(payload.ScenarioID) {
		writeError(w, http.StatusUnprocessableEntity, "unsupported scenario")
		return
	}

	result, err := s.validate(r.Context(), payload)
	if err != nil {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func (s *server) handleRunPython(w http.ResponseWriter, r *http.Request) {
	var payload runRequest
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid JSON body")
		return
	}
	payload.ScenarioID = strings.TrimSpace(payload.ScenarioID)
	payload.Language = strings.ToLower(strings.TrimSpace(payload.Language))
	if payload.Code == "" {
		writeError(w, http.StatusUnprocessableEntity, "code cannot be empty")
		return
	}
	if payload.Language != "" && payload.Language != "python" && payload.Language != "py" {
		writeError(w, http.StatusUnprocessableEntity, "only python code is supported")
		return
	}
	if !isSupportedCodingScenario(payload.ScenarioID) {
		writeError(w, http.StatusUnprocessableEntity, "unsupported scenario")
		return
	}

	result, err := s.run(r.Context(), payload)
	if err != nil {
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func (s *server) runPython(ctx context.Context, payload runRequest) (runResponse, error) {
	timeout := timeoutDuration(payload.TimeoutSeconds)
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	input, _ := json.Marshal(map[string]string{
		"scenario_id": payload.ScenarioID,
		"code":        payload.Code,
	})
	cmd := exec.CommandContext(ctx, s.pythonBin, "-c", pythonRunnerSource)
	cmd.Stdin = bytes.NewReader(input)
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return runResponse{}, errors.New("timeout")
		}
		detail := strings.TrimSpace(stderr.String())
		if detail == "" {
			detail = strings.TrimSpace(stdout.String())
		}
		if detail == "" {
			detail = err.Error()
		}
		return runResponse{}, fmt.Errorf("%s", truncate(detail, 400))
	}

	var result runResponse
	if err := json.Unmarshal(stdout.Bytes(), &result); err != nil {
		return runResponse{}, errors.New("invalid runner response")
	}
	return result, nil
}

func (s *server) validateSQL(ctx context.Context, payload sqlValidationRequest) (sqlValidationResponse, error) {
	timeout := timeoutDuration(payload.TimeoutSeconds)
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	input, _ := json.Marshal(map[string]string{
		"scenario_id": payload.ScenarioID,
		"query":       payload.Query,
	})
	cmd := exec.CommandContext(ctx, s.pythonBin, "-c", sqlValidationSource)
	cmd.Stdin = bytes.NewReader(input)
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return sqlValidationResponse{}, errors.New("timeout")
		}
		detail := strings.TrimSpace(stderr.String())
		if detail == "" {
			detail = strings.TrimSpace(stdout.String())
		}
		if detail == "" {
			detail = err.Error()
		}
		return sqlValidationResponse{}, fmt.Errorf("%s", truncate(detail, 400))
	}

	var result sqlValidationResponse
	if err := json.Unmarshal(stdout.Bytes(), &result); err != nil {
		return sqlValidationResponse{}, errors.New("invalid SQL validation response")
	}
	return result, nil
}

func isSupportedSQLScenario(value string) bool {
	switch value {
	case "customer_revenue_rollup", "signup_funnel_rollup", "incident_error_budget_audit":
		return true
	default:
		return false
	}
}

func isSupportedCodingScenario(value string) bool {
	switch value {
	case "rate_limiter_window_counter", "feature_freshness_monitor", "flaky_test_classifier", "deployment_rollout_guard":
		return true
	default:
		return false
	}
}

func timeoutDuration(value float64) time.Duration {
	if value <= 0 {
		value = defaultTimeoutSeconds
	}
	if value > 10 {
		value = 10
	}
	return time.Duration(value * float64(time.Second))
}

func envOrDefault(key string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value
}

func truncate(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return value[:limit]
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

var pythonRunnerSource = strings.TrimSpace(`
import ast
import json
import sys
from collections import defaultdict, deque

ALLOWED_MODULES = {"collections", "typing"}
DISALLOWED_CALLS = {
    "open", "exec", "eval", "compile", "input", "globals",
    "locals", "vars", "dir", "getattr", "setattr", "delattr", "breakpoint"
}

def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = str(name or "").split(".")[0]
    if root not in ALLOWED_MODULES:
        raise ImportError(f"import '{name}' is not allowed")
    return __import__(name, globals, locals, fromlist, level)

def validate_tree(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if str(alias.name or "").split(".")[0] not in ALLOWED_MODULES:
                    raise ValueError(f"disallowed import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "").split(".")[0]
            if module not in ALLOWED_MODULES:
                raise ValueError(f"disallowed import: {node.module}")
        elif isinstance(node, ast.Attribute):
            if str(getattr(node, "attr", "")).startswith("__"):
                raise ValueError("dunder attribute access is not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DISALLOWED_CALLS:
                raise ValueError(f"disallowed call: {node.func.id}")

def safe_globals():
    return {
        "__builtins__": {
            "len": len,
            "range": range,
            "min": min,
            "max": max,
            "sum": sum,
            "abs": abs,
            "enumerate": enumerate,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "any": any,
            "all": all,
            "zip": zip,
            "sorted": sorted,
            "reversed": reversed,
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "__import__": safe_import,
        },
        "defaultdict": defaultdict,
        "deque": deque,
    }

def run_rate_limiter_checks(ns):
    fn = ns.get("allow_request")
    if not callable(fn):
        raise ValueError("allow_request function was not found")

    def reset_state():
        if "windows" in ns:
            ns["windows"] = defaultdict(deque)

    results = []

    reset_state()
    within_limit = [bool(fn("user-a", ts)) for ts in (0, 1, 2, 3, 4)]
    results.append({
        "check_key": "runner_allows_within_limit",
        "passed": all(within_limit),
        "details": f"sequence={within_limit}",
    })

    reset_state()
    for ts in (0, 1, 2, 3, 4):
        fn("user-a", ts)
    blocked = bool(fn("user-a", 5)) is False
    results.append({
        "check_key": "runner_blocks_over_limit",
        "passed": blocked,
        "details": f"sixth_request_blocked={blocked}",
    })

    reset_state()
    for ts in (0, 1, 2, 3, 4):
        fn("user-a", ts)
    expired_ok = bool(fn("user-a", 60)) is True
    results.append({
        "check_key": "runner_expires_old_entries",
        "passed": expired_ok,
        "details": f"request_after_window={expired_ok}",
    })

    reset_state()
    for ts in (0, 1, 2, 3, 4):
        fn("user-a", ts)
    other_user_ok = bool(fn("user-b", 5)) is True
    results.append({
        "check_key": "runner_isolates_users",
        "passed": other_user_ok,
        "details": f"other_user_allowed={other_user_ok}",
    })
    return results

def _call_feature_freshness(fn, record, now_ts=10000):
    try:
        return fn(record, now_ts, max_age_seconds=3600)
    except TypeError:
        try:
            return fn(record, now_ts)
        except TypeError:
            return fn(record)

def _decision_allows(result):
    if isinstance(result, bool):
        return result
    if isinstance(result, str):
        lowered = result.strip().lower()
        if any(token in lowered for token in ("allow", "allowed", "pass", "ok")):
            return True
        if any(token in lowered for token in ("block", "blocked", "deny", "reject", "stale")):
            return False
    if isinstance(result, dict):
        if "allowed" in result:
            return bool(result.get("allowed"))
        if "allow" in result:
            return bool(result.get("allow"))
        if "blocked" in result:
            return not bool(result.get("blocked"))
        if "block" in result:
            return not bool(result.get("block"))
        for key in ("decision", "status", "action", "recommendation"):
            value = str(result.get(key) or "").strip().lower()
            if value in {"allow", "allowed", "pass", "ok", "use_fallback"}:
                return True
            if value in {"block", "blocked", "deny", "reject", "stale"}:
                return False
    return None

def _used_fallback(result):
    if not isinstance(result, dict):
        return False
    if bool(result.get("used_fallback") or result.get("fallback_used") or result.get("fallback")):
        return True
    return str(result.get("source") or "").strip().lower() == "fallback"

def _has_reason(result):
    if isinstance(result, str):
        return bool(result.strip())
    if not isinstance(result, dict):
        return False
    for key in ("reason", "explanation", "message", "details"):
        if str(result.get(key) or "").strip():
            return True
    return False

def run_feature_freshness_checks(ns):
    fn = ns.get("evaluate_feature_freshness")
    if not callable(fn):
        raise ValueError("evaluate_feature_freshness function was not found")

    fresh_record = {
        "feature_age_seconds": 120,
        "features": {"risk_score": 0.42},
        "fallback_features": {"risk_score": 0.50},
    }
    stale_record = {
        "feature_age_seconds": 7200,
        "features": {"risk_score": 0.42},
        "fallback_features": {"risk_score": 0.50},
    }
    missing_record = {
        "feature_age_seconds": 120,
        "features": {"risk_score": None},
        "fallback_features": {"risk_score": 0.55},
    }

    fresh_result = _call_feature_freshness(fn, fresh_record)
    stale_result = _call_feature_freshness(fn, stale_record)
    fallback_result = _call_feature_freshness(fn, missing_record)
    fresh_decision = _decision_allows(fresh_result)
    stale_decision = _decision_allows(stale_result)
    fallback_decision = _decision_allows(fallback_result)

    reason_present = any(_has_reason(item) for item in (fresh_result, stale_result, fallback_result))
    results = [
        {
            "check_key": "runner_allows_fresh_features",
            "passed": fresh_decision is True,
            "details": f"fresh_decision={fresh_decision}",
        },
        {
            "check_key": "runner_blocks_stale_features",
            "passed": stale_decision is False,
            "details": f"stale_decision={stale_decision}",
        },
        {
            "check_key": "runner_uses_fallback_for_missing_feature",
            "passed": fallback_decision is True and _used_fallback(fallback_result),
            "details": f"fallback_decision={fallback_decision}; used_fallback={_used_fallback(fallback_result)}",
        },
        {
            "check_key": "runner_explains_feature_decision",
            "passed": reason_present,
            "details": f"reason_present={reason_present}",
        },
    ]
    return results

def _call_flaky_classifier(fn, runs):
    try:
        return fn(runs)
    except TypeError:
        return fn(test_runs=runs)

def _item_name(item):
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ""
    for key in ("test_id", "test", "name", "id", "nodeid"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""

def _items_from_keys(result, keys):
    if isinstance(result, dict):
        for key in keys:
            value = result.get(key)
            if isinstance(value, (list, tuple, set)):
                return list(value)
    if isinstance(result, (list, tuple, set)):
        return list(result)
    return []

def _contains_named_item(items, target):
    return any(_item_name(item) == target for item in items)

def _has_flaky(result, target):
    flaky_items = _items_from_keys(result, ("flaky_tests", "flaky", "flakes", "unstable_tests", "unstable"))
    if _contains_named_item(flaky_items, target):
        return True
    for item in flaky_items:
        if isinstance(item, dict) and bool(item.get("flaky")) and _item_name(item) == target:
            return True
    if isinstance(result, (list, tuple, set)):
        for item in result:
            if not isinstance(item, dict) or _item_name(item) != target:
                continue
            classification = str(item.get("classification") or item.get("status") or item.get("kind") or "").lower()
            if bool(item.get("flaky")) or "flaky" in classification:
                return True
    return False

def _has_stable_failure(result, target):
    stable_items = _items_from_keys(result, ("stable_failures", "persistent_failures", "consistent_failures", "failed_tests"))
    if _contains_named_item(stable_items, target):
        return True
    if isinstance(result, (list, tuple, set)):
        for item in result:
            if not isinstance(item, dict) or _item_name(item) != target:
                continue
            classification = str(item.get("classification") or item.get("status") or item.get("kind") or "").lower()
            if "stable" in classification or "persistent" in classification or "consistent" in classification:
                return True
    return False

def _has_diagnostics(result):
    if isinstance(result, str):
        return bool(result.strip())
    if isinstance(result, dict):
        for key in ("summary", "diagnostics", "report", "message"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return True
            if isinstance(value, (list, tuple, dict)) and value:
                return True
    return False

def run_flaky_classifier_checks(ns):
    fn = ns.get("classify_flaky_tests")
    if not callable(fn):
        raise ValueError("classify_flaky_tests function was not found")

    runs = [
        {"test_id": "test_login", "run_id": "build-1", "status": "failed"},
        {"test_id": "test_login", "run_id": "build-2", "status": "passed"},
        {"test_id": "test_checkout", "run_id": "build-1", "status": "failed"},
        {"test_id": "test_checkout", "run_id": "build-2", "status": "failed"},
        {"test_id": "test_search", "run_id": "build-1", "status": "passed"},
        {"test_id": "test_search", "run_id": "build-2", "status": "passed"},
    ]

def _call_rollout_guard(fn, snapshot):
    try:
        return fn(snapshot)
    except TypeError:
        return fn(metrics=snapshot)

def _rollout_action(result):
    if isinstance(result, str):
        lowered = result.strip().lower()
        if "rollback" in lowered or "roll back" in lowered:
            return "rollback"
        if "pause" in lowered or "hold" in lowered:
            return "pause"
        if "continue" in lowered or "proceed" in lowered:
            return "continue"
    if isinstance(result, dict):
        for key in ("action", "decision", "recommendation", "status"):
            value = str(result.get(key) or "").strip().lower().replace("-", "_")
            if value in {"rollback", "roll_back", "revert"}:
                return "rollback"
            if value in {"pause", "hold", "stop", "wait"}:
                return "pause"
            if value in {"continue", "proceed", "advance", "ok"}:
                return "continue"
    return ""

def run_deployment_rollout_checks(ns):
    fn = ns.get("evaluate_rollout_health")
    if not callable(fn):
        raise ValueError("evaluate_rollout_health function was not found")

    healthy = {
        "stage": "canary",
        "error_rate": 0.004,
        "latency_p95_ms": 180,
        "slo_burn_rate": 0.7,
        "alerts": [],
        "events": [{"type": "deploy_started", "severity": "info"}],
    }
    degraded = {
        "stage": "canary",
        "error_rate": 0.018,
        "latency_p95_ms": 460,
        "slo_burn_rate": 1.8,
        "alerts": [{"name": "latency-warning", "severity": "warning"}],
        "events": [{"type": "latency_regression", "severity": "warning"}],
    }
    critical = {
        "stage": "canary",
        "error_rate": 0.082,
        "latency_p95_ms": 1250,
        "slo_burn_rate": 6.5,
        "alerts": [{"name": "error-budget-burn", "severity": "critical"}],
        "events": [{"type": "customer-impact", "severity": "critical"}],
    }

    healthy_result = _call_rollout_guard(fn, healthy)
    degraded_result = _call_rollout_guard(fn, degraded)
    critical_result = _call_rollout_guard(fn, critical)
    healthy_action = _rollout_action(healthy_result)
    degraded_action = _rollout_action(degraded_result)
    critical_action = _rollout_action(critical_result)
    reason_present = any(_has_reason(item) for item in (healthy_result, degraded_result, critical_result))

    return [
        {
            "check_key": "runner_continues_healthy_rollout",
            "passed": healthy_action == "continue",
            "details": f"healthy_action={healthy_action}",
        },
        {
            "check_key": "runner_pauses_degraded_rollout",
            "passed": degraded_action == "pause",
            "details": f"degraded_action={degraded_action}",
        },
        {
            "check_key": "runner_rolls_back_critical_failure",
            "passed": critical_action == "rollback",
            "details": f"critical_action={critical_action}",
        },
        {
            "check_key": "runner_explains_rollout_decision",
            "passed": reason_present,
            "details": f"reason_present={reason_present}",
        },
    ]
    result = _call_flaky_classifier(fn, runs)
    grouped = False
    if isinstance(result, dict):
        groups = result.get("groups") or result.get("by_test") or result.get("grouped_runs")
        grouped = isinstance(groups, dict) and "test_login" in groups and "test_checkout" in groups
    flags_flaky = _has_flaky(result, "test_login")
    separates_stable = _has_stable_failure(result, "test_checkout") and not _has_flaky(result, "test_checkout")
    diagnostics_present = _has_diagnostics(result)

    return [
        {
            "check_key": "runner_groups_repeated_runs",
            "passed": grouped,
            "details": f"grouped={grouped}",
        },
        {
            "check_key": "runner_flags_flaky_mixed_outcomes",
            "passed": flags_flaky,
            "details": f"test_login_flaky={flags_flaky}",
        },
        {
            "check_key": "runner_separates_stable_failures",
            "passed": separates_stable,
            "details": f"test_checkout_stable_failure={separates_stable}",
        },
        {
            "check_key": "runner_emits_ci_diagnostics",
            "passed": diagnostics_present,
            "details": f"diagnostics_present={diagnostics_present}",
        },
    ]

payload = json.loads(sys.stdin.read())
source = str(payload.get("code") or "")
scenario_id = str(payload.get("scenario_id") or "")

tree = ast.parse(source, mode="exec")
validate_tree(tree)
ns = safe_globals()
exec(compile(tree, "<candidate_code>", "exec"), ns, ns)

if scenario_id == "rate_limiter_window_counter":
    results = run_rate_limiter_checks(ns)
elif scenario_id == "feature_freshness_monitor":
    results = run_feature_freshness_checks(ns)
elif scenario_id == "flaky_test_classifier":
    results = run_flaky_classifier_checks(ns)
elif scenario_id == "deployment_rollout_guard":
    results = run_deployment_rollout_checks(ns)
else:
    results = []

runner_score = round(
    sum(10.0 if item.get("passed") else 0.0 for item in results) / len(results),
    1,
) if results else None
print(json.dumps({"runner_score": runner_score, "runner_checks": results}))
`)

var sqlValidationSource = strings.TrimSpace(`
import json
import sqlite3
import sys

SCENARIOS = {
    "customer_revenue_rollup": {
        "schema_statements": (
            """
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                is_active INTEGER NOT NULL
            );
            """,
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                total_amount REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            """,
        ),
        "seed_statements": (
            "INSERT INTO customers (id, name, is_active) VALUES (1, 'Alice', 1);",
            "INSERT INTO customers (id, name, is_active) VALUES (2, 'Bob', 1);",
            "INSERT INTO customers (id, name, is_active) VALUES (3, 'Carol', 0);",
            "INSERT INTO customers (id, name, is_active) VALUES (4, 'Dana', 1);",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (1, 1, 'completed', 120, '2024-03-05');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (2, 1, 'completed', 80, '2024-03-18');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (3, 1, 'pending', 40, '2024-03-20');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (4, 1, 'completed', 50, '2024-02-27');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (5, 2, 'completed', 60, '2024-03-09');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (6, 2, 'completed', 40, '2024-03-11');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (7, 2, 'refunded', 25, '2024-03-14');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (8, 3, 'completed', 500, '2024-03-12');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (9, 4, 'completed', 110, '2024-03-21');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (10, 4, 'completed', 20, '2024-04-02');",
            "INSERT INTO orders (id, customer_id, status, total_amount, created_at) VALUES (11, 4, 'pending', 70, '2024-03-25');",
        ),
        "expected_columns": ("customer_name", "completed_order_count", "completed_revenue"),
        "expected_rows": (("Alice", 2, 200.0), ("Dana", 1, 110.0), ("Bob", 2, 100.0)),
    },
    "signup_funnel_rollup": {
        "schema_statements": (
            """
            CREATE TABLE signup_events (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_date TEXT NOT NULL
            );
            """,
        ),
        "seed_statements": (
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (1, 101, 'started', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (2, 102, 'started', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (3, 103, 'started', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (4, 104, 'started', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (5, 101, 'verified', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (6, 102, 'verified', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (7, 104, 'verified', '2024-04-01');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (8, 201, 'started', '2024-04-02');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (9, 202, 'started', '2024-04-02');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (10, 203, 'started', '2024-04-02');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (11, 201, 'verified', '2024-04-02');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (12, 301, 'started', '2024-04-03');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (13, 302, 'started', '2024-04-03');",
            "INSERT INTO signup_events (id, user_id, event_type, event_date) VALUES (14, 301, 'verified', '2024-04-03');",
        ),
        "expected_columns": ("event_date", "started_users", "verified_users", "verified_rate"),
        "expected_rows": (("2024-04-01", 4, 3, 0.75), ("2024-04-02", 3, 1, 0.3333)),
    },
    "incident_error_budget_audit": {
        "schema_statements": (
            """
            CREATE TABLE service_daily_metrics (
                id INTEGER PRIMARY KEY,
                service_name TEXT NOT NULL,
                metric_date TEXT NOT NULL,
                error_rate REAL NOT NULL
            );
            """,
        ),
        "seed_statements": (
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (1, 'auth', '2024-04-01', 0.012);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (2, 'auth', '2024-04-02', 0.021);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (3, 'auth', '2024-04-03', 0.011);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (4, 'payments', '2024-04-01', 0.015);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (5, 'payments', '2024-04-02', 0.004);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (6, 'payments', '2024-04-03', 0.013);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (7, 'search', '2024-04-01', 0.009);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (8, 'search', '2024-04-02', 0.014);",
            "INSERT INTO service_daily_metrics (id, service_name, metric_date, error_rate) VALUES (9, 'search', '2024-04-03', 0.008);",
        ),
        "expected_columns": ("service_name", "breach_days", "max_error_rate"),
        "expected_rows": (("auth", 3, 0.021), ("payments", 2, 0.015)),
    },
}

def normalize_row(row):
    normalized = []
    for value in row:
        if isinstance(value, (int, float)):
            normalized.append(round(float(value), 4))
        else:
            normalized.append(value)
    return tuple(normalized)

payload = json.loads(sys.stdin.read())
scenario_id = str(payload.get("scenario_id") or "").strip()
query = str(payload.get("query") or "").strip()
scenario = SCENARIOS.get(scenario_id)
if not scenario:
    raise ValueError("unsupported scenario")

stripped_query = query.strip().rstrip(";").strip()
lowered_query = stripped_query.lower()
is_select_only = bool(stripped_query) and lowered_query.startswith(("select", "with")) and ";" not in stripped_query

checks = [{
    "check_key": "query_is_select_only",
    "status": "passed" if is_select_only else "missed",
    "score": 10.0 if is_select_only else 0.0,
    "evidence": None if is_select_only else "Only a single SELECT/CTE query is allowed.",
}]

if not is_select_only:
    for key in ("query_executes", "expected_columns", "expected_rows"):
        checks.append({"check_key": key, "status": "missed", "score": 0.0, "evidence": None})
    print(json.dumps({"validation_score": 2.5, "validation_checks": checks}))
    raise SystemExit(0)

conn = None
try:
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    for statement in scenario.get("schema_statements", ()):
        cursor.executescript(str(statement))
    for statement in scenario.get("seed_statements", ()):
        cursor.execute(str(statement))

    cursor.execute(stripped_query)
    rows = [normalize_row(tuple(row)) for row in cursor.fetchall()]
    columns = tuple(str(item[0] or "").strip().lower() for item in (cursor.description or ()))
    expected_columns = tuple(str(item).strip().lower() for item in scenario.get("expected_columns", ()))
    expected_rows = tuple(normalize_row(tuple(row)) for row in scenario.get("expected_rows", ()))

    columns_match = columns == expected_columns
    rows_match = rows == list(expected_rows)
    checks.extend([
        {"check_key": "query_executes", "status": "passed", "score": 10.0, "evidence": f"rows={len(rows)}"},
        {"check_key": "expected_columns", "status": "passed" if columns_match else "missed", "score": 10.0 if columns_match else 0.0, "evidence": ", ".join(columns) if columns else None},
        {"check_key": "expected_rows", "status": "passed" if rows_match else "missed", "score": 10.0 if rows_match else 0.0, "evidence": str(rows[:3])[:240] if rows else None},
    ])
except Exception as exc:
    checks.extend([
        {"check_key": "query_executes", "status": "missed", "score": 0.0, "evidence": str(exc)[:240] or None},
        {"check_key": "expected_columns", "status": "missed", "score": 0.0, "evidence": None},
        {"check_key": "expected_rows", "status": "missed", "score": 0.0, "evidence": None},
    ])
finally:
    if conn is not None:
        conn.close()

validation_score = round(sum(float(item.get("score") or 0.0) for item in checks) / len(checks), 1) if checks else None
print(json.dumps({"validation_score": validation_score, "validation_checks": checks}))
`)
