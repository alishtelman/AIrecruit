import httpx
import pytest

from app.ai.assessor import (
    _build_coding_task_runner_checks,
    _build_sql_live_validation_checks,
    _run_coding_task_runner_in_sandbox,
    _run_sql_live_validation_in_sandbox,
)
from app.core.config import settings


def test_run_coding_task_runner_in_sandbox_maps_payload(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.SANDBOX_SERVICE_URL
    settings.SANDBOX_SERVICE_URL = "http://sandbox-service:8080"

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, path: str, json: dict) -> httpx.Response:
            assert path == "/v1/coding/python"
            assert json["scenario_id"] == "rate_limiter_window_counter"
            assert json["language"] == "python"
            assert json["code"] == "code"
            return httpx.Response(
                200,
                json={
                    "runner_score": 10.0,
                    "runner_checks": [
                        {
                            "check_key": "runner_blocks_over_limit",
                            "passed": True,
                            "details": "ok",
                        }
                    ],
                },
            )

    monkeypatch.setattr("app.ai.assessor.httpx.Client", _FakeClient)
    try:
        payload = _run_coding_task_runner_in_sandbox(
            scenario_id="rate_limiter_window_counter",
            artifact_code="code",
            artifact_language="python",
        )
    finally:
        settings.SANDBOX_SERVICE_URL = original_url

    assert payload["runner_score"] == 10.0
    assert payload["runner_checks"][0]["check_key"] == "runner_blocks_over_limit"


def test_build_coding_task_runner_checks_uses_sandbox(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.SANDBOX_SERVICE_URL
    settings.SANDBOX_SERVICE_URL = "http://sandbox-service:8080"

    def _fake_sandbox(**kwargs):
        return {
            "runner_score": 10.0,
            "runner_checks": [
                {
                    "check_key": "runner_blocks_over_limit",
                    "passed": True,
                    "details": "sixth_request_blocked=True",
                }
            ],
        }

    monkeypatch.setattr("app.ai.assessor._run_coding_task_runner_in_sandbox", _fake_sandbox)
    try:
        checks, score = _build_coding_task_runner_checks(
            scenario_id="rate_limiter_window_counter",
            artifact_code="def allow_request(): pass",
            artifact_language="python",
            report_language="en",
        )
    finally:
        settings.SANDBOX_SERVICE_URL = original_url

    assert score == 10.0
    assert checks == [
        {
            "check_key": "runner_blocks_over_limit",
            "title": "Blocks the request after the sliding-window limit is reached",
            "status": "passed",
            "score": 10.0,
            "evidence": "sixth_request_blocked=True",
        }
    ]


def test_build_coding_task_runner_checks_falls_back_when_sandbox_unavailable(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.SANDBOX_SERVICE_URL
    settings.SANDBOX_SERVICE_URL = "http://sandbox-service:8080"

    def _failing_sandbox(**kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr("app.ai.assessor._run_coding_task_runner_in_sandbox", _failing_sandbox)
    try:
        checks, score = _build_coding_task_runner_checks(
            scenario_id="rate_limiter_window_counter",
            artifact_code="""from collections import defaultdict, deque
windows = defaultdict(deque)
def allow_request(user_id: str, now: int, limit: int = 5, window_seconds: int = 60) -> bool:
    queue = windows[user_id]
    while queue and now - queue[0] >= window_seconds:
        queue.popleft()
    if len(queue) >= limit:
        return False
    queue.append(now)
    return True
""",
            artifact_language="python",
            report_language="en",
        )
    finally:
        settings.SANDBOX_SERVICE_URL = original_url

    assert score == 10.0
    assert any(check["check_key"] == "runner_blocks_over_limit" for check in checks)


def test_run_sql_live_validation_in_sandbox_maps_payload(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.SANDBOX_SERVICE_URL
    settings.SANDBOX_SERVICE_URL = "http://sandbox-service:8080"

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, path: str, json: dict) -> httpx.Response:
            assert path == "/v1/sql/validate"
            assert json["scenario_id"] == "customer_revenue_rollup"
            assert json["query"] == "select 1"
            return httpx.Response(
                200,
                json={
                    "validation_score": 10.0,
                    "validation_checks": [
                        {
                            "check_key": "expected_rows",
                            "status": "passed",
                            "score": 10.0,
                            "evidence": "ok",
                        }
                    ],
                },
            )

    monkeypatch.setattr("app.ai.assessor.httpx.Client", _FakeClient)
    try:
        payload = _run_sql_live_validation_in_sandbox(
            scenario_id="customer_revenue_rollup",
            query_text="select 1",
        )
    finally:
        settings.SANDBOX_SERVICE_URL = original_url

    assert payload["validation_score"] == 10.0
    assert payload["validation_checks"][0]["check_key"] == "expected_rows"


def test_build_sql_live_validation_checks_uses_sandbox(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.SANDBOX_SERVICE_URL
    settings.SANDBOX_SERVICE_URL = "http://sandbox-service:8080"

    def _fake_sandbox(**kwargs):
        return {
            "validation_score": 10.0,
            "validation_checks": [
                {
                    "check_key": "expected_rows",
                    "status": "passed",
                    "score": 10.0,
                    "evidence": "ok",
                }
            ],
        }

    monkeypatch.setattr("app.ai.assessor._run_sql_live_validation_in_sandbox", _fake_sandbox)
    try:
        checks, score = _build_sql_live_validation_checks(
            scenario_id="customer_revenue_rollup",
            query_text="select 1",
            report_language="en",
        )
    finally:
        settings.SANDBOX_SERVICE_URL = original_url

    assert score == 10.0
    assert checks == [
        {
            "check_key": "expected_rows",
            "title": "Returns the expected result rows in the required order",
            "status": "passed",
            "score": 10.0,
            "evidence": "ok",
        }
    ]


def test_build_sql_live_validation_checks_falls_back_when_sandbox_unavailable(monkeypatch: pytest.MonkeyPatch):
    original_url = settings.SANDBOX_SERVICE_URL
    settings.SANDBOX_SERVICE_URL = "http://sandbox-service:8080"

    def _failing_sandbox(**kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr("app.ai.assessor._run_sql_live_validation_in_sandbox", _failing_sandbox)
    try:
        checks, score = _build_sql_live_validation_checks(
            scenario_id="customer_revenue_rollup",
            query_text="""SELECT
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
ORDER BY completed_revenue DESC""",
            report_language="en",
        )
    finally:
        settings.SANDBOX_SERVICE_URL = original_url

    assert score == 10.0
    assert any(check["check_key"] == "expected_rows" and check["status"] == "passed" for check in checks)
