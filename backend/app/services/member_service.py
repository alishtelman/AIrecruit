"""
Company member management service.

Invite flow:
  1. Admin calls invite_member(email, company_id)
  2. If user with that email doesn't exist → create User(role=company_member) + temp password
  3. Add CompanyMember record
  4. Return the member + temp_password (frontend shows it once)

If user already exists and is a company_member → add to this company too.
If user is a candidate or company_admin → reject (role conflict).
"""
import secrets
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.company_member import CompanyMember
from app.models.user import User


class MemberAlreadyExistsError(Exception):
    pass


class RoleConflictError(Exception):
    pass


async def invite_member(
    db: AsyncSession,
    company_id: uuid.UUID,
    email: str,
    invited_by_user_id: uuid.UUID,
) -> tuple[CompanyMember, str | None]:
    """
    Invite a user to the company.
    Returns (member, temp_password). temp_password is None if user already existed.
    """
    # Check if already a member of this company
    existing_user = await db.scalar(select(User).where(User.email == email))

    temp_password: str | None = None

    if existing_user:
        if existing_user.role in ("candidate", "company_admin"):
            raise RoleConflictError(
                f"User {email} already has role '{existing_user.role}' and cannot be a company member"
            )
        # Already a company_member — check if already in THIS company
        existing_membership = await db.scalar(
            select(CompanyMember).where(
                CompanyMember.company_id == company_id,
                CompanyMember.user_id == existing_user.id,
            )
        )
        if existing_membership:
            raise MemberAlreadyExistsError(f"{email} is already a member of this company")
        user = existing_user
    else:
        # Create new user with temporary password
        temp_password = secrets.token_urlsafe(12)
        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password=hash_password(temp_password),
            role="company_member",
        )
        db.add(user)
        await db.flush()

    member = CompanyMember(
        id=uuid.uuid4(),
        company_id=company_id,
        user_id=user.id,
        role="member",
        invited_by_user_id=invited_by_user_id,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member, temp_password


async def list_members(
    db: AsyncSession,
    company_id: uuid.UUID,
) -> list[dict]:
    """List all members of a company including the owner."""
    from app.models.company import Company

    company = await db.scalar(select(Company).where(Company.id == company_id))
    members_result = await db.execute(
        select(CompanyMember, User)
        .join(User, CompanyMember.user_id == User.id)
        .where(CompanyMember.company_id == company_id)
        .order_by(CompanyMember.created_at)
    )

    rows = []
    for member, user in members_result:
        rows.append({
            "member_id": str(member.id),
            "user_id": str(user.id),
            "email": user.email,
            "role": member.role,
            "created_at": member.created_at.isoformat(),
        })

    # Prepend owner if not already in the list
    if company and company.owner_user_id:
        owner_ids = {r["user_id"] for r in rows}
        if str(company.owner_user_id) not in owner_ids:
            owner = await db.scalar(select(User).where(User.id == company.owner_user_id))
            if owner:
                rows.insert(0, {
                    "member_id": None,
                    "user_id": str(owner.id),
                    "email": owner.email,
                    "role": "admin",
                    "created_at": company.created_at.isoformat(),
                })

    return rows


async def remove_member(
    db: AsyncSession,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
) -> None:
    """Remove a member. Admin cannot remove themselves."""
    if user_id == requesting_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove yourself from the company",
        )

    member = await db.scalar(
        select(CompanyMember).where(
            CompanyMember.company_id == company_id,
            CompanyMember.user_id == user_id,
        )
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    await db.delete(member)
    await db.commit()
