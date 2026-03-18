import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.company_member import CompanyMember
from app.models.user import User

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
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
