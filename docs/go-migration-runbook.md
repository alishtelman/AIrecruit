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
- The target state is Go-owned backend services behind the same public `/api/v1` contracts, with FastAPI reduced to a compatibility gateway only during the migration.
- Keep core AI/domain scoring in Python until there are golden tests for transcript-to-report payload parity.
- Avoid duplicating database schema ownership in Go unless a slice has a clear data boundary. Prefer FastAPI-owned internal endpoints when the Go service is only orchestrating existing Python business logic.
- Preserve fallback paths during migration. A Go sidecar failure should not break local development when a safe Python fallback exists.

## Full Go Migration Roadmap

### Phase 1: Sidecars Behind FastAPI

Current phase. Add Go services behind existing FastAPI routes while keeping public `/api/v1` contracts stable and keeping safe Python fallbacks.

Exit criteria:

- Go sidecars cover media, resume file processing, sandbox/runtime checks, LLM provider HTTP calls, and report-worker orchestration.
- Each sidecar has unit tests, Compose healthchecks, and documented smoke checks.
- Backend proxy tests cover success, fallback, and error mapping.

### Phase 2: Go-Owned Internal APIs

Move from "Go sidecar as helper" to "Go service owns an internal contract" for slices with clear boundaries.

Candidates:

- `services/report-worker`: own worker polling, backlog throttling, idempotency, and safe external-worker mode.
- `services/llm`: own provider status, key availability diagnostics, timeout/retry execution, and structured output provider adapters.
- `services/sandbox`: own deterministic runners and validation fixtures for every supported executable scenario.
- `services/media` and `services/resume`: own file processing contracts with richer health/status and observability.

Exit criteria:

- FastAPI code for those areas becomes a thin auth/compatibility proxy.
- Fallback paths are explicitly feature-flagged and tested.
- Operational metrics/logging exist for each Go service.

### Phase 3: Data-Bound Go Services

Move DB-backed domains only after the data ownership boundary is explicit. Do not let Go and Python both own migrations for the same tables.

Candidate order:

- Company marketplace/search read model after SQL parity tests and index decisions.
- Report generation queue/read model after report-worker idempotency is proven.
- Candidate/company settings only after platform settings contracts are stable.

Exit criteria:

- SQL/query parity tests exist before each move.
- One migration owner is chosen for each table group.
- Public API payloads remain backward-compatible.

### Phase 4: AI/Assessment Core

Move interviewer, assessor, report shaping, and scoring last.

Required before starting:

- Golden transcript-to-report fixtures for representative roles, modules, languages, proctoring states, and provider outputs.
- Deterministic report normalization tests for every public report section.
- Clear strategy for prompts, structured-output validation, and model-provider differences.

Exit criteria:

- Go and Python produce equivalent report payloads on golden fixtures.
- Rollback can switch traffic back to Python without changing frontend contracts.

### Phase 5: FastAPI Gateway Removal

Only after phases 2-4 are stable, replace the compatibility gateway with Go-owned public `/api/v1` routes.

Exit criteria:

- Auth, CSRF/cookie behavior, rate limiting, API schemas, error shapes, and localization expectations are covered by integration tests.
- Frontend does not need route changes.
- Deployment has a rollback path to the previous gateway.

## Implemented Slices

### `services/media`

Go sidecar for:

- `GET /v1/status`
- `POST /v1/tts`
- `POST /v1/stt`
- `POST /v1/recordings/{recording_id}`

FastAPI still exposes the public routes:

- `POST /api/v1/tts`
- `POST /api/v1/stt`
- `POST /api/v1/interviews/{interview_id}/recording`

FastAPI keeps authentication, ownership checks, and DB updates. The Go service handles provider calls
and binary/streaming file work. `GET /v1/status` returns safe operational diagnostics only: TTS/STT
provider configured flags, provider/model names, upload/recording limits, recording MIME types, and
recording-storage configured/writable flags. It does not expose API keys, recording storage paths, or
candidate data.

### `services/resume`

Go sidecar for:

- `POST /v1/resumes`
- `GET /v1/status`

FastAPI still exposes the public route:

- `POST /api/v1/candidate/resume/upload`

FastAPI keeps candidate authentication, previous-resume deactivation, and DB writes. The Go service
validates file MIME/size, stores the file in shared resume storage, and extracts best-effort raw text.
`GET /v1/status` returns safe operational diagnostics only: storage configured/writable flags, size
limits, raw-text limit, and allowed MIME types. It does not expose storage paths or candidate data. If
`RESUME_SERVICE_URL` is unavailable, `resume_service.py` falls back to the previous Python PDF/DOCX
parser and local file write.

### `services/report-worker`

Go worker for report-generation orchestration.

It calls:

```text
POST /api/v1/internal/report-worker/tick?dry_run=true|false
GET /api/v1/internal/report-worker/status
X-Internal-Worker-Token: <INTERNAL_WORKER_TOKEN>
```

FastAPI still owns report generation, assessment, locking, retries, and DB writes. The Go worker only polls, inspects backlog status, and triggers work.

Health endpoint:

```text
GET /health
```

The health payload includes startup time, dry-run mode, max jobs per cycle, last tick time, last successful tick, last candidate interview id, last processed interview id, pending count, processed/error counters, and last error.

### `services/sandbox`

Go sidecar for interview sandbox execution and validation.

Current endpoints:

```text
GET /v1/status
POST /v1/coding/python
POST /v1/sql/validate
```

Current supported coding scenario:

- `rate_limiter_window_counter`
- `feature_freshness_monitor`
- `flaky_test_classifier`
- `deployment_rollout_guard`

Current supported SQL live scenarios:

- `customer_revenue_rollup`
- `signup_funnel_rollup`
- `incident_error_budget_audit`

FastAPI/Python still owns scoring, report schema, localized check titles, and final summary shaping.
The Go service runs constrained runtime checks in a separate container. `GET /v1/status` returns safe
operational diagnostics only: Python runtime availability, supported languages, supported coding/SQL
scenario ids, and timeout limits. It does not expose submitted code, SQL queries, filesystem paths, or
candidate data. If `SANDBOX_SERVICE_URL` is unavailable, the assessor falls back to the previous local
subprocess/SQLite validators.

### `services/llm`

Go sidecar for platform-managed LLM provider calls.

Current endpoint:

```text
POST /v1/complete
GET /v1/status
```

Supported providers:

- `groq`
- `openai`
- `anthropic`
- `openrouter`

FastAPI/Python still owns platform settings, prompt selection, interviewer/assessor business logic,
structured-output parsing, public errors, and report/interview contracts. The Go service normalizes
outbound provider HTTP calls, provider error categories, safe provider-key status, and executes
provider retry attempts from the platform `llm_max_retries` setting for transient failures only. After
the Go service exhausts its internal retry budget, it returns a terminal error to avoid multiplying
retries in the Python compatibility layer. Admin runtime status uses `GET /v1/status` when
`LLM_SERVICE_URL` is configured, then falls back to local env-key checks if the sidecar is unavailable
or returns an invalid status payload. If `LLM_SERVICE_URL` is unavailable at request time, Python logs
a warning and falls back to the direct provider adapter.

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
- `REPORT_WORKER_DRY_RUN`: when `true`, the Go worker selects the next candidate job without triggering report generation.
- `REPORT_WORKER_MAX_JOBS_PER_CYCLE`: caps consecutive processed jobs before the Go worker sleeps.

Docker Compose currently sets:

- backend `MEDIA_SERVICE_URL=http://media-service:8080`
- backend `RESUME_SERVICE_URL=http://resume-service:8080`
- backend `SANDBOX_SERVICE_URL=http://sandbox-service:8080`
- backend `LLM_SERVICE_URL=http://llm-service:8080`
- backend `REPORT_WORKER_MODE=${REPORT_WORKER_MODE:-embedded}`
- backend/report-worker `INTERNAL_WORKER_TOKEN=${INTERNAL_WORKER_TOKEN:-dev-internal-worker-token}`
- report-worker `REPORT_WORKER_DRY_RUN=${REPORT_WORKER_DRY_RUN:-false}`
- report-worker `REPORT_WORKER_MAX_JOBS_PER_CYCLE=${REPORT_WORKER_MAX_JOBS_PER_CYCLE:-1}`
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

To explicitly test the Go report worker, start with dry-run mode so backlog visibility does not trigger Groq calls:

```bash
REPORT_WORKER_MODE=external REPORT_WORKER_DRY_RUN=true docker compose --profile workers up -d backend report-worker
curl -fsS -H "X-Internal-Worker-Token: dev-internal-worker-token" http://localhost:8001/api/v1/internal/report-worker/status
docker compose exec -T report-worker wget -qO- http://127.0.0.1:8080/health
```

After confirming pending backlog and quota impact, disable dry-run explicitly:

```bash
REPORT_WORKER_MODE=external REPORT_WORKER_DRY_RUN=false REPORT_WORKER_MAX_JOBS_PER_CYCLE=1 docker compose --profile workers up -d backend report-worker
```

If quota/rate limits matter, leave it stopped until explicitly testing worker behavior:

```bash
docker compose stop report-worker
```

To run it again:

```bash
REPORT_WORKER_MODE=external REPORT_WORKER_DRY_RUN=true docker compose --profile workers up -d report-worker
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
curl -fsS http://localhost:8081/v1/status
curl -fsS http://localhost:8082/health
curl -fsS http://localhost:8082/v1/status
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
curl -fsS http://localhost:8083/v1/status
printf '%s' '%PDF-1.4
BT (Codex Resume Smoke) Tj ET
%%EOF' | curl -fsS -X POST \
  -F 'file=@-;filename=codex-smoke.pdf;type=application/pdf' \
  http://localhost:8083/v1/resumes
```

## Recommended Next Slices

1. Finish Phase 1 by expanding `services/sandbox` with remaining deterministic Python-compatible runners only when each scenario has a clear function contract and parity tests.
2. Harden `services/llm` into a Phase 2 internal API: provider status endpoint, structured-output adapter tests, and retry/timeout execution in Go.
3. Harden `services/report-worker`: backlog visibility, dry-run/safety guard, and external worker mode validation before making it default.
4. Add marketplace/search SQL parity tests and indexes before considering a Go-owned read model.
5. Only migrate AI interviewer/assessor/report shaping after golden transcript-to-report parity exists.

## Do Not Do

- Do not move frontend API routes or change `/api/v1` contracts unless explicitly requested.
- Do not let Go and Python both own schema migrations for the same tables without a migration-tool decision.
- Do not run `report-worker` against a shared/staging DB without confirming the backlog and Groq quota impact.
- Do not remove Python fallbacks until the Go service has production-grade healthchecks, monitoring, and deploy rollback.
