from datetime import timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate, get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.company import Company
from app.models.company_member import CompanyMember
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.candidate import CandidateRegisterRequest, CandidateResponse, CandidateWithUserResponse
from app.schemas.company import CompanyRegisterRequest, CompanyRegisterResponse
from app.schemas.user import LoginRequest, TokenResponse, UserResponse
from app.services.auth_service import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    login,
    register_candidate,
    register_company,
)

router = APIRouter(prefix="/auth", tags=["auth"])
audit_logger = logging.getLogger("security.audit")


def _set_auth_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=int(timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES).total_seconds()),
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )


async def _build_user_response(db: AsyncSession, user: User) -> UserResponse:
    company_member_role = None
    company_id = None
    if user.role == "company_admin":
        company_member_role = "admin"
        company = await db.scalar(select(Company).where(Company.owner_user_id == user.id))
        if company:
            company_id = company.id
    elif user.role == "company_member":
        membership = await db.scalar(
            select(CompanyMember).where(CompanyMember.user_id == user.id)
        )
        if membership:
            company_id = membership.company_id
            company_member_role = "recruiter" if membership.role == "member" else membership.role

    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        company_member_role=company_member_role,
        company_id=company_id,
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.post(
    "/candidate/register",
    response_model=CandidateWithUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def candidate_register(
    body: CandidateRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        user, candidate = await register_candidate(db, body)
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    return CandidateWithUserResponse(
        user=UserResponse.model_validate(user),
        candidate=CandidateResponse.model_validate(candidate),
    )


@router.post(
    "/company/register",
    response_model=CompanyRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def company_register(
    body: CompanyRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        user, company = await register_company(db, body)
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    return CompanyRegisterResponse(
        user_id=user.id,
        email=user.email,
        company_id=company.id,
        company_name=company.name,
    )


@router.post("/login", response_model=TokenResponse)
async def user_login(
    body: LoginRequest,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        token_response = await login(db, body.email, body.password)
        _set_auth_cookie(response, token_response.access_token)
        return token_response
    except InvalidCredentialsError:
        client_ip = request.client.host if request.client else "unknown"
        audit_logger.warning(
            "login_failed ip=%s email=%s",
            client_ip,
            body.email,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
):
    _clear_auth_cookie(response)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _build_user_response(db, current_user)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters")
    current_user.hashed_password = hash_password(body.new_password)
    await db.commit()


@router.get("/me/candidate", response_model=CandidateWithUserResponse)
async def get_me_candidate(
    user_and_candidate=Depends(get_current_candidate),
    db: AsyncSession = Depends(get_db),
):
    user, candidate = user_and_candidate
    return CandidateWithUserResponse(
        user=await _build_user_response(db, user),
        candidate=CandidateResponse.model_validate(candidate),
    )
