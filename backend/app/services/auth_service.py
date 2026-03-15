import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password, create_access_token
from app.models.company import Company
from app.models.user import User
from app.models.candidate import Candidate
from app.schemas.candidate import CandidateRegisterRequest
from app.schemas.company import CompanyRegisterRequest
from app.schemas.user import TokenResponse


class EmailAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


async def register_candidate(
    db: AsyncSession,
    data: CandidateRegisterRequest,
) -> tuple[User, Candidate]:
    # Check email uniqueness
    existing = await db.scalar(select(User).where(User.email == data.email))
    if existing:
        raise EmailAlreadyExistsError(data.email)

    user = User(
        id=uuid.uuid4(),
        email=data.email,
        hashed_password=hash_password(data.password),
        role="candidate",
    )
    db.add(user)
    await db.flush()  # get user.id before creating candidate

    candidate = Candidate(
        id=uuid.uuid4(),
        user_id=user.id,
        full_name=data.full_name,
    )
    db.add(candidate)
    await db.commit()
    await db.refresh(user)
    await db.refresh(candidate)
    return user, candidate


async def register_company(
    db: AsyncSession,
    data: CompanyRegisterRequest,
) -> tuple[User, Company]:
    existing = await db.scalar(select(User).where(User.email == data.email))
    if existing:
        raise EmailAlreadyExistsError(data.email)

    user = User(
        id=uuid.uuid4(),
        email=data.email,
        hashed_password=hash_password(data.password),
        role="company_admin",
    )
    db.add(user)
    await db.flush()

    company = Company(
        id=uuid.uuid4(),
        owner_user_id=user.id,
        name=data.company_name,
    )
    db.add(company)
    await db.commit()
    await db.refresh(user)
    await db.refresh(company)
    return user, company


async def login(
    db: AsyncSession,
    email: str,
    password: str,
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError()
    if not user.is_active:
        raise InvalidCredentialsError()

    token = create_access_token(subject=str(user.id), role=user.role)
    return TokenResponse(access_token=token)
