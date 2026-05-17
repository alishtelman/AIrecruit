import os
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.ai.assessor import LLMAssessor, MockAssessor, assessor
from app.ai.interviewer import LLMInterviewer, MockInterviewer, interviewer
from app.ai.model_preferences import resolve_llm_runtime_model
from app.ai.runtime_status import get_ai_runtime_status, set_runtime_identity
from app.core.config import settings
from app.core.rate_limit import match_rule, rate_limiter
from app.core.database import AsyncSessionLocal
from app.services.auth_service import ensure_platform_admin

cors_origins = settings.cors_origins
audit_logger = logging.getLogger("security.audit")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Recruiting Platform API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if settings.SESSION_COOKIE_SECURE:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=63072000; includeSubDomains",
        )
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if not settings.rate_limit_enabled:
        return await call_next(request)

    rule = match_rule(request.method, request.url.path)
    if rule is None:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = rate_limiter.allow(
        key=(rule.name, client_ip),
        limit=rule.limit,
        window_seconds=rule.window_seconds,
    )
    if not allowed:
        audit_logger.warning(
            "rate_limit_blocked route=%s method=%s ip=%s retry_after=%s",
            rule.name,
            request.method,
            client_ip,
            retry_after,
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please retry later."},
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: ensures CORS headers are present on unhandled 500s."""
    origin = request.headers.get("origin")
    headers = {}
    if origin and origin in cors_origins:
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        }
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers=headers,
    )


app.include_router(api_router, prefix="/api/v1")


@app.on_event("startup")
async def startup_event():
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.RESUME_STORAGE_DIR, exist_ok=True)
    os.makedirs(settings.RECORDING_STORAGE_DIR, exist_ok=True)
    if settings.platform_admin_bootstrap_enabled:
        async with AsyncSessionLocal() as db:
            await ensure_platform_admin(db)

    interviewer_provider = (
        getattr(interviewer, "provider_name", "groq")
        if isinstance(interviewer, LLMInterviewer)
        else "mock" if isinstance(interviewer, MockInterviewer) else "disabled"
    )
    assessor_provider = (
        getattr(assessor, "provider_name", "groq")
        if isinstance(assessor, LLMAssessor)
        else "mock" if isinstance(assessor, MockAssessor) else "disabled"
    )

    mock_mode_enabled = interviewer_provider == "mock" or assessor_provider == "mock"
    app_env = (settings.APP_ENV or "").strip().lower()
    if app_env == "production" and mock_mode_enabled:
        raise RuntimeError("Mock AI provider is forbidden when APP_ENV=production")

    if interviewer_provider == assessor_provider:
        active_provider = interviewer_provider
    else:
        active_provider = f"mixed({interviewer_provider},{assessor_provider})"

    model_name = resolve_llm_runtime_model(None) if active_provider not in {"mock", "disabled"} else "disabled"
    if settings.ai_provider == "openrouter":
        api_key_present = bool(settings.OPENROUTER_API_KEY)
    elif settings.ai_provider == "groq":
        api_key_present = bool(settings.GROQ_API_KEY)
    else:
        api_key_present = False
    set_runtime_identity(
        provider=active_provider,
        model=model_name,
        api_key_present=api_key_present,
        mock_enabled=mock_mode_enabled,
    )
    logger.info(
        "ai_runtime_startup active_provider=%s model_name=%s api_key_present=%s mock_mode_enabled=%s interviewer_provider=%s assessor_provider=%s",
        active_provider,
        model_name,
        api_key_present,
        mock_mode_enabled,
        interviewer_provider,
        assessor_provider,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-recruiting-backend"}


@app.get("/ai/status")
async def ai_status():
    return get_ai_runtime_status()
