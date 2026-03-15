from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_candidate, get_current_user
from app.core.database import get_db
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
    db: AsyncSession = Depends(get_db),
):
    try:
        return await login(db, body.email, body.password)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.get("/me/candidate", response_model=CandidateWithUserResponse)
async def get_me_candidate(
    user_and_candidate=Depends(get_current_candidate),
):
    user, candidate = user_and_candidate
    return CandidateWithUserResponse(
        user=UserResponse.model_validate(user),
        candidate=CandidateResponse.model_validate(candidate),
    )
