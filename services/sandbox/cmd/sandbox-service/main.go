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
	if payload.ScenarioID != "rate_limiter_window_counter" {
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

payload = json.loads(sys.stdin.read())
source = str(payload.get("code") or "")
scenario_id = str(payload.get("scenario_id") or "")

tree = ast.parse(source, mode="exec")
validate_tree(tree)
ns = safe_globals()
exec(compile(tree, "<candidate_code>", "exec"), ns, ns)

if scenario_id == "rate_limiter_window_counter":
    results = run_rate_limiter_checks(ns)
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
