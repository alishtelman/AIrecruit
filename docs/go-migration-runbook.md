# Go Service Migration Runbook

This runbook records the active Go migration flow so a new Codex session can continue without rediscovering context.

## Current Branch

All Go migration work should happen on:

```bash
codex/go-service-migration
```

If a new session starts on another branch, switch first:

```bash
git switch codex/go-service-migration
```

Do not continue this migration directly on `main`.

## Migration Strategy

- Keep the public frontend contract stable. `frontend/src/lib/api.ts` should not need route changes for these slices.
- Move infrastructure-heavy work to Go first: media streaming, provider proxying, worker orchestration, sandbox/runtime services.
- Keep core AI/domain scoring in Python until there are golden tests for report payload parity.
- Avoid duplicating database schema ownership in Go unless a slice has a clear data boundary. Prefer FastAPI-owned internal endpoints when the Go service is only orchestrating existing Python business logic.
- Preserve fallback paths during migration. A Go sidecar failure should not break local development when a safe Python fallback exists.

## Implemented Slices

### `services/media`

Go sidecar for:

- `POST /v1/tts`
- `POST /v1/stt`
- `POST /v1/recordings/{recording_id}`

FastAPI still exposes the public routes:

- `POST /api/v1/tts`
- `POST /api/v1/stt`
- `POST /api/v1/interviews/{interview_id}/recording`

FastAPI keeps authentication, ownership checks, and DB updates. The Go service handles provider calls and binary/streaming file work.

### `services/resume`

Go sidecar for:

- `POST /v1/resumes`

FastAPI still exposes the public route:

- `POST /api/v1/candidate/resume/upload`

FastAPI keeps candidate authentication, previous-resume deactivation, and DB writes. The Go service validates file MIME/size, stores the file in shared resume storage, and extracts best-effort raw text. If `RESUME_SERVICE_URL` is unavailable, `resume_service.py` falls back to the previous Python PDF/DOCX parser and local file write.

### `services/report-worker`

Go worker for report-generation orchestration.

It calls:

```text
POST /api/v1/internal/report-worker/tick
X-Internal-Worker-Token: <INTERNAL_WORKER_TOKEN>
```

FastAPI still owns report generation, assessment, locking, retries, and DB writes. The Go worker only polls and triggers work.

Health endpoint:

```text
GET /health
```

The health payload includes startup time, last tick time, last successful tick, last processed interview id, and last error.

### `services/sandbox`

Go sidecar for interview sandbox execution and validation.

Current endpoints:

```text
POST /v1/coding/python
POST /v1/sql/validate
```

Current supported coding scenario:

- `rate_limiter_window_counter`
- `feature_freshness_monitor`

Current supported SQL live scenarios:

- `customer_revenue_rollup`
- `signup_funnel_rollup`
- `incident_error_budget_audit`

FastAPI/Python still owns scoring, report schema, localized check titles, and final summary shaping. The Go service runs constrained runtime checks in a separate container. If `SANDBOX_SERVICE_URL` is unavailable, the assessor falls back to the previous local subprocess/SQLite validators.

### `services/llm`

Go sidecar for platform-managed LLM provider calls.

Current endpoint:

```text
POST /v1/complete
```

Supported providers:

- `groq`
- `openai`
- `anthropic`
- `openrouter`

FastAPI/Python still owns platform settings, prompt selection, interviewer/assessor business logic, structured-output parsing, retry policy, public errors, and report/interview contracts. The Go service only normalizes outbound provider HTTP calls and provider error categories. If `LLM_SERVICE_URL` is unavailable at request time, Python logs a warning and falls back to the direct provider adapter.

OpenRouter requests set `provider.allow_fallbacks=false` to preserve the product rule that the app does not implement cross-provider fallback.

## Runtime Configuration

Important env vars:

- `MEDIA_SERVICE_URL`: when set in backend, `/tts`, `/stt`, and recording upload proxy to `services/media`.
- `RESUME_SERVICE_URL`: when set in backend, candidate resume upload file processing proxies to `services/resume`.
- `SANDBOX_SERVICE_URL`: when set in backend, coding-task runner and SQL live validation checks proxy to `services/sandbox`.
- `LLM_SERVICE_URL`: when set in backend, LLM provider HTTP calls proxy to `services/llm`; direct Python adapters remain as an availability fallback.
- `REPORT_WORKER_MODE`: `embedded` keeps old `asyncio.create_task`; `external` lets the Go worker poll.
- `INTERNAL_WORKER_TOKEN`: required for the internal report-worker endpoint.
- `REPORT_WORKER_INTERVAL_SECONDS`: Go worker idle polling interval.
- `REPORT_WORKER_REQUEST_TIMEOUT_SECONDS`: request timeout for a report-worker tick.

Docker Compose currently sets:

- backend `MEDIA_SERVICE_URL=http://media-service:8080`
- backend `RESUME_SERVICE_URL=http://resume-service:8080`
- backend `SANDBOX_SERVICE_URL=http://sandbox-service:8080`
- backend `LLM_SERVICE_URL=http://llm-service:8080`
- backend `REPORT_WORKER_MODE=${REPORT_WORKER_MODE:-embedded}`
- backend/report-worker `INTERNAL_WORKER_TOKEN=${INTERNAL_WORKER_TOKEN:-dev-internal-worker-token}`
- backend waits for healthy `media-service`
- backend waits for healthy `resume-service`
- backend waits for healthy `sandbox-service`
- backend waits for healthy `llm-service`
- report-worker waits for healthy backend
- report-worker is behind the Compose profile `workers` and is not started by default

## Non-Go Optimizations Kept In Python

### Company Marketplace Search

Do not move company marketplace/search to Go yet. The bottleneck was Python loading a broad marketplace snapshot and then applying basic filters in memory.

Current state:

- `_load_marketplace_snapshot` uses a SQL window function to select the latest marketplace report per candidate.
- Basic filters are pushed into SQL: name/email query, role, recommendation, min score, salary range, hire outcome, shortlist membership, and sort order.
- Skills filtering stays in Python because skills may come from either `CandidateSkill` rows or fallback `AssessmentReport.skill_tags`; pushing this to SQL without a parity decision could change results.

If continuing this area, add explicit tests for latest-report semantics before pushing skill filtering into SQL or adding indexes.

## Local Development Notes

The local DB may contain old `completed` or `report_processing` interviews with no report. Starting `report-worker` can process that backlog and trigger Groq calls.

Default local startup is safe and uses embedded Python scheduling:

```bash
docker compose up -d backend media-service resume-service sandbox-service llm-service frontend
```

To explicitly test the Go report worker, opt in with the `workers` profile and external worker mode:

```bash
REPORT_WORKER_MODE=external docker compose --profile workers up -d backend report-worker
```

If quota/rate limits matter, leave it stopped until explicitly testing worker behavior:

```bash
docker compose stop report-worker
```

To run it again:

```bash
REPORT_WORKER_MODE=external docker compose --profile workers up -d report-worker
```

## Validation Commands

Run these after touching Go services or Python proxy code:

```bash
docker run --rm -v "$PWD/services/media:/src" -w /src golang:1.23-alpine go test ./...
docker run --rm -v "$PWD/services/resume:/src" -w /src golang:1.23-alpine go test ./...
docker run --rm -v "$PWD/services/sandbox:/src" -w /src golang:1.23-alpine go test ./...
docker run --rm -v "$PWD/services/llm:/src" -w /src golang:1.23-alpine go test ./...
docker run --rm -v "$PWD/services/report-worker:/src" -w /src golang:1.23-alpine go test ./...
docker compose config --quiet
docker compose exec -T backend python -m pytest tests/test_resume_service_proxy.py tests/test_sandbox_runner_proxy.py tests/test_report_worker_internal.py tests/test_media_service_proxy.py tests/test_tts.py tests/test_llm_runtime.py -v
```

Build checks:

```bash
docker compose build media-service resume-service sandbox-service llm-service report-worker
docker compose --profile workers build report-worker
```

Smoke checks:

```bash
curl -fsS http://localhost:8081/health
curl -fsS http://localhost:8082/health
curl -fsS http://localhost:8083/health
curl -fsS http://localhost:8084/health
curl -fsS http://localhost:8001/health
docker compose exec -T report-worker wget -qO- http://127.0.0.1:8080/health
curl -fsS -X POST \
  -H "Content-Type: application/json" \
  --data @- \
  http://localhost:8082/v1/sql/validate <<'JSON'
{"scenario_id":"customer_revenue_rollup","query":"SELECT c.name AS customer_name, COUNT(o.id) AS completed_order_count, SUM(o.total_amount) AS completed_revenue FROM customers c JOIN orders o ON o.customer_id = c.id WHERE c.is_active = 1 AND o.status = 'completed' AND o.created_at >= '2024-03-01' AND o.created_at < '2024-04-01' GROUP BY c.id, c.name ORDER BY completed_revenue DESC"}
JSON
curl -fsS -X POST \
  -H "X-Internal-Worker-Token: dev-internal-worker-token" \
  http://localhost:8001/api/v1/internal/report-worker/tick
```

Recording upload smoke test:

```bash
curl -fsS -X POST \
  -H "Content-Type: video/webm" \
  --data-binary "recording-smoke" \
  http://localhost:8081/v1/recordings/codex-smoke-test
docker compose exec -T media-service rm -f /app/storage/recordings/codex-smoke-test.webm
```

Resume upload sidecar smoke test:

```bash
printf '%s' '%PDF-1.4
BT (Codex Resume Smoke) Tj ET
%%EOF' | curl -fsS -X POST \
  -F 'file=@-;filename=codex-smoke.pdf;type=application/pdf' \
  http://localhost:8083/v1/resumes
```

## Recommended Next Slices

1. Expand `services/sandbox` with additional deterministic assessment runtimes only when each scenario has parity tests and a clear function contract.
2. Continue company marketplace/search with SQL/index work before considering a Go rewrite; language alone will not fix poor query shape.
3. Only consider migrating AI interviewer/assessor after adding golden tests for transcript-to-report parity.

## Do Not Do

- Do not move frontend API routes or change `/api/v1` contracts unless explicitly requested.
- Do not let Go and Python both own schema migrations for the same tables without a migration-tool decision.
- Do not run `report-worker` against a shared/staging DB without confirming the backlog and Groq quota impact.
- Do not remove Python fallbacks until the Go service has production-grade healthchecks, monitoring, and deploy rollback.
