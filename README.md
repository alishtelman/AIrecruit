# AIRecruit — AI-Powered Recruiting Platform

A platform where candidates complete structured AI interviews and receive verified skill reports. Companies access a database of pre-assessed, AI-verified professionals.

---

## Product Overview

**For Candidates**
1. Register and upload your resume (PDF or DOCX)
2. Choose a target role — optionally use a company's custom interview template
3. Complete a structured AI text interview (8 questions, ~15–20 min)
4. Receive a detailed assessment report with scores, strengths, and weaknesses
5. Retake any interview to improve your score
6. Join the verified candidate database

**For Companies**
1. Register and browse AI-verified candidates
2. Filter by role, search by name/email, paginate through results
3. View detailed assessment reports and interview replays for accessible candidates
4. Create custom interview templates (public or private) with your own question sets
5. Run private employee assessments via invite links
6. Make data-driven hiring decisions

**Roadmap (post-MVP)**
- Voice and video AI interviews
- Multi-user company accounts
- HttpOnly session auth and stricter production defaults

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy (async), Alembic |
| Database | PostgreSQL 16 |
| Auth | JWT (python-jose), bcrypt (passlib) |
| AI | Groq API — Llama 3.3 70B (interviewer + assessor) |
| Frontend | Next.js 14, TypeScript, Tailwind CSS |
| Infrastructure | Docker, Docker Compose |

---

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── ai/                  # AI modules (interviewer + assessor)
│   │   │   ├── interviewer.py   # Question generation (mock → LLM)
│   │   │   └── assessor.py      # Report generation (mock → LLM)
│   │   ├── api/v1/              # REST endpoints
│   │   │   ├── auth.py          # Register, login, /me
│   │   │   ├── candidates.py    # Resume upload + profile stats
│   │   │   ├── interviews.py    # Interview flow + public templates
│   │   │   ├── company.py       # Candidate browsing + templates CRUD
│   │   │   └── reports.py       # Assessment reports
│   │   ├── core/                # Config, DB, security (JWT/bcrypt)
│   │   ├── models/              # SQLAlchemy ORM models (+ template.py)
│   │   ├── schemas/             # Pydantic request/response schemas (+ template.py)
│   │   └── services/            # Business logic layer (+ template_service.py)
│   ├── alembic/                 # Database migrations
│   │   └── versions/
│   │       └── 001_initial_schema.py
│   ├── storage/resumes/         # Uploaded resume files (local dev)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── (candidate)/     # Candidate-facing pages
│       │   │   └── candidate/
│       │   │       ├── register/
│       │   │       ├── login/
│       │   │       ├── dashboard/
│       │   │       ├── resume/
│       │   │       ├── interview/
│       │   │       │   ├── start/
│       │   │       │   └── [id]/
│       │   │       └── reports/[id]/
│       │   └── (company)/       # Company-facing pages (dashboard, templates, candidates)
│       ├── hooks/               # useAuth hook
│       └── lib/                 # API client, types, auth helpers
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Database Schema

```
users               — unified auth (role: candidate | company_admin)
candidates          — candidate profile (1:1 with users)
companies           — company profile (owner_user_id → users)
resumes             — uploaded CVs with extracted text (is_active flag)
interview_templates — custom question sets per company (is_public flag)
interviews          — interview sessions with state machine (optional template_id FK)
interview_messages  — full dialogue history (system/assistant/candidate)
assessment_reports  — structured AI assessment with scores
```

**Interview state machine:**
```
created → in_progress → completed → report_generated
                                  ↘ failed
```

---

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/candidate/register` | — | Register candidate |
| POST | `/api/v1/auth/company/register` | — | Register company |
| POST | `/api/v1/auth/login` | — | Login (all roles) |
| GET | `/api/v1/auth/me` | Bearer | Current user |
| GET | `/api/v1/auth/me/candidate` | Bearer | Candidate profile |
| GET | `/api/v1/candidate/stats` | Bearer | Resume + interview stats for dashboard |
| POST | `/api/v1/candidate/resume/upload` | Bearer | Upload PDF/DOCX resume |
| GET | `/api/v1/interviews/` | Bearer | List all candidate interviews |
| POST | `/api/v1/interviews/start` | Bearer | Start interview |
| POST | `/api/v1/interviews/{id}/message` | Bearer | Send answer, get next question |
| POST | `/api/v1/interviews/{id}/finish` | Bearer | Finish and generate report |
| POST | `/api/v1/interviews/{id}/recording` | Bearer | Upload interview recording (`video/webm` or `video/mp4`) |
| GET | `/api/v1/interviews/{id}` | Bearer | Interview details + messages |
| GET | `/api/v1/reports/{id}` | Bearer (candidate) | Candidate-owned assessment report |
| GET | `/api/v1/employee/invite/{token}` | — | Public employee assessment invite info |
| POST | `/api/v1/employee/invite/{token}/start` | Bearer (candidate) | Start invited employee assessment |
| GET | `/api/v1/company/candidates` | Bearer (company) | List verified candidates |
| GET | `/api/v1/company/candidates/{id}` | Bearer (company) | Candidate profile + all reports |
| GET | `/api/v1/company/reports/{id}` | Bearer (company) | Company-scoped report access |
| GET | `/api/v1/company/interviews/{id}/replay` | Bearer (company) | Company-scoped replay access |
| GET | `/api/v1/candidate/resume` | Bearer | Active resume info |
| GET | `/api/v1/interviews/templates/public` | — | List public interview templates |
| GET | `/api/v1/company/templates` | Bearer (company) | List company's own templates |
| POST | `/api/v1/company/templates` | Bearer (company) | Create interview template |
| DELETE | `/api/v1/company/templates/{id}` | Bearer (company) | Delete interview template |

Full interactive docs: **http://localhost:8001/docs**

---

## Security Hardening

- `POST /api/v1/employee/invite/{token}/start` now binds the invite to the authenticated candidate email and returns `403` on email mismatch.
- `GET /api/v1/company/reports/{report_id}` and `GET /api/v1/company/interviews/{interview_id}/replay` are scoped to the owning company for private employee assessments.
- Private employee assessments are excluded from the shared company candidate marketplace.
- Interview recordings accept only `video/webm` and `video/mp4` and are capped by `MAX_RECORDING_SIZE_MB`.
- Candidate login and registration redirects are sanitized to path-only, same-origin destinations.
- Backend CORS is configured through `CORS_ORIGINS`; the full audit and remediation status lives in `security_best_practices_report.md`.

---

## Local Development Setup

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2+
- Git

### 1. Clone the repository

```bash
git clone https://github.com/alishtelman/AIrecruit.git
cd AIrecruit
```

### 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and set:
```
SECRET_KEY=your-random-secret     # change before any real use
GROQ_API_KEY=gsk_...              # required for LLM interviews (free at console.groq.com)
NEXT_PUBLIC_API_URL=http://localhost:8001
APP_URL=http://localhost:3000
CORS_ORIGINS=http://localhost:3000
MAX_RECORDING_SIZE_MB=250
RESEND_API_KEY=re_...             # optional, enables email notifications
```

> **Note on ports:** If you have other services running, the defaults are:
> - Backend → `8001` (mapped from container's 8000)
> - Frontend → `3000`
> - PostgreSQL → `5433` (mapped from container's 5432)

### 3. Start all services

```bash
docker compose up --build
```

### 4. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

### 5. Open in browser

| URL | Service |
|---|---|
| http://localhost:3000 | Frontend |
| http://localhost:8001/docs | Swagger UI |
| http://localhost:8001/health | Backend health check |

---

## Testing the Full Flow

### Via Browser (Frontend)

1. Go to `http://localhost:3000` → click **I'm a Candidate**
2. Register with email + password
3. Upload your resume (PDF or DOCX)
4. Start Interview → select your role
5. Answer 8 questions in the chat UI
6. Click **Finish & Get Report** → view your assessment

### Via curl

```bash
# Register
curl -s -X POST http://localhost:8001/api/v1/auth/candidate/register \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"password123","full_name":"Dev User"}'

# Login → get token
TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"password123"}' | jq -r .access_token)

# Upload resume
curl -s -X POST http://localhost:8001/api/v1/candidate/resume/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/resume.pdf"

# Start interview
INTERVIEW=$(curl -s -X POST http://localhost:8001/api/v1/interviews/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_role":"backend_engineer"}')
INTERVIEW_ID=$(echo $INTERVIEW | jq -r .interview_id)

# Send answers (repeat 8 times)
curl -s -X POST http://localhost:8001/api/v1/interviews/$INTERVIEW_ID/message \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"I have 5 years of backend experience..."}'

# Finish and get report
curl -s -X POST http://localhost:8001/api/v1/interviews/$INTERVIEW_ID/finish \
  -H "Authorization: Bearer $TOKEN"
```

---

## Development Status

| Phase | Status | Description |
|---|---|---|
| Phase 1 | ✅ Done | Project scaffold, Docker, DB schema |
| Phase 2 | ✅ Done | JWT auth, candidate + company registration |
| Phase 3 | ✅ Done | Resume upload, text extraction |
| Phase 4 | ✅ Done | Interview engine (mock AI) |
| Phase 4.5 | ✅ Done | Working frontend UI (full candidate flow) |
| Phase 5 | ✅ Done | Real LLM integration (Groq — Llama 3.3 70B) |
| Phase 6 | ✅ Done | Company dashboard, candidate browsing |
| Phase 7 | ✅ Done | Custom interview templates, retry UX, profile page, pagination, 404/error pages |
| Phase 8 | 🔜 Next | Voice/video interviews, multi-user company accounts |

---

## Useful Commands

```bash
# Start / rebuild
docker compose up -d --build

# Container status
docker compose ps

# View logs
docker compose logs backend -f
docker compose logs frontend -f

# Run migrations
docker compose exec backend alembic revision --autogenerate -m "description"
docker compose exec backend alembic upgrade head

# Frontend checks
docker compose exec frontend npm run lint
docker compose exec frontend npm run build

# Connect to DB
docker compose exec postgres psql -U recruiting -d recruiting

# Rebuild a single service
docker compose build backend
docker compose up -d backend

# Stop everything
docker compose down
```

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `SECRET_KEY` | — | JWT signing secret (change in production) |
| `ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Token TTL |
| `GROQ_API_KEY` | — | Groq API key for interviews, assessment, STT, and TTS |
| `ANTHROPIC_API_KEY` | empty | Reserved, currently unused by the runtime |
| `RESEND_API_KEY` | empty | Optional email delivery provider key |
| `APP_URL` | `http://localhost:3000` | Frontend base URL for invite links and emails |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated backend CORS allowlist |
| `UPLOAD_DIR` | `/app/uploads` | General upload directory |
| `RESUME_STORAGE_DIR` | `/app/storage/resumes` | Resume file storage path |
| `RECORDING_STORAGE_DIR` | `/app/storage/recordings` | Interview recording storage path |
| `MAX_RESUME_SIZE_MB` | `10` | Max upload size |
| `MAX_RECORDING_SIZE_MB` | `250` | Max interview recording size |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8001` | Backend URL for frontend |
