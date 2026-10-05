from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from beanie.odm.fields import PydanticObjectId

from app.core.security import decode_access_token
from app.models.identification.users import User
from app.repositories.user_repository import UserRepository, get_user_repository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    user_repository: UserRepository = Depends(get_user_repository),
) -> User:
    """Extract and validate JWT, then return the current authenticated user."""
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    user_id_str = payload.get("user_id")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    try:
        user_id = PydanticObjectId(user_id_str)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def get_current_teacher_or_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Require teacher or platform admin for content management routes."""
    if user.role not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teacher or admin access required",
        )
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Require admin for global catalog routes."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


async def get_current_organization(
    user: User = Depends(get_current_user),
) -> User:
    """Require organization (tenant admin) role for org panel routes."""
    if user.role != "organization":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization access required",
        )
    return user


async def get_current_for_org_structure_read(
    user: User = Depends(get_current_user),
) -> User:
    """Read org class/subject structure: org admins, teachers, students, and platform admins."""
    if user.role not in ("organization", "teacher", "student", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed to read organization structure",
        )
    return user
