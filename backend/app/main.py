import os
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.rate_limit import match_rule, rate_limiter
from app.core.database import AsyncSessionLocal
from app.services.auth_service import ensure_platform_admin

cors_origins = settings.cors_origins
audit_logger = logging.getLogger("security.audit")

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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-recruiting-backend"}
