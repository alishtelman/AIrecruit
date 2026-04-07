import uuid
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.company_member import CompanyMember
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _normalize_origin(value: str) -> str | None:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _enforce_cookie_csrf(request: Request, session_token: str | None, bearer_token: str | None) -> None:
    # Bearer transport is considered explicit API authentication and does not
    # rely on browser cookie semantics. CSRF validation is for cookie-only auth.
    if request.method.upper() not in UNSAFE_METHODS or not session_token or bearer_token:
        return

    origin_header = request.headers.get("origin")
    referer_header = request.headers.get("referer")
    source = origin_header or referer_header
    normalized_source = _normalize_origin(source) if source else None
    if normalized_source is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")

    trusted = {origin.rstrip("/") for origin in settings.csrf_trusted_origins}
    if normalized_source not in trusted:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    session_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    bearer_token = credentials.credentials if (credentials and settings.allow_bearer_auth) else None
    if not session_token and not bearer_token:
        raise credentials_exception

    _enforce_cookie_csrf(request, session_token=session_token, bearer_token=bearer_token)

    user_id: str | None = None

    # Prefer explicit Authorization header when it is valid, but do not block
    # cookie sessions when a stale/invalid bearer is present.
    if bearer_token:
        try:
            bearer_payload = decode_access_token(bearer_token)
            user_id = bearer_payload.get("sub")
        except JWTError:
            user_id = None

    if user_id is None and session_token:
        try:
            session_payload = decode_access_token(session_token)
            user_id = session_payload.get("sub")
        except JWTError:
            user_id = None

    if user_id is None:
        raise credentials_exception

    user = await db.scalar(select(User).where(User.id == uuid.UUID(user_id)))
    if user is None or not user.is_active:
        raise credentials_exception
    return user


async def get_current_candidate(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, Candidate]:
    if current_user.role != "candidate":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Candidate access required")
    candidate = await db.scalar(select(Candidate).where(Candidate.user_id == current_user.id))
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate profile not found")
    return current_user, candidate


async def get_current_company_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Only the company owner (company_admin role) can access."""
    if current_user.role != "company_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company admin access required")
    return current_user


async def get_current_company(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, Company]:
    """Any company user (admin or invited member) can access."""
    if current_user.role not in ("company_admin", "company_member"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Company access required")

    if current_user.role == "company_admin":
        company = await db.scalar(select(Company).where(Company.owner_user_id == current_user.id))
    else:
        # company_member — find their company via CompanyMember table
        membership = await db.scalar(
            select(CompanyMember).where(CompanyMember.user_id == current_user.id)
        )
        if membership is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of any company")
        company = await db.scalar(select(Company).where(Company.id == membership.company_id))

    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company profile not found")
    return current_user, company


async def get_current_company_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, Company, str]:
    user, company = await get_current_company(current_user=current_user, db=db)
    if current_user.role == "company_admin":
        return user, company, "admin"

    membership = await db.scalar(
        select(CompanyMember).where(
            CompanyMember.user_id == current_user.id,
            CompanyMember.company_id == company.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this company")

    role = "recruiter" if membership.role == "member" else membership.role
    return user, company, role


async def get_current_company_recruiter(
    context: tuple[User, Company, str] = Depends(get_current_company_context),
) -> tuple[User, Company, str]:
    if context[2] not in ("admin", "recruiter"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Recruiter or admin access required",
        )
    return context
