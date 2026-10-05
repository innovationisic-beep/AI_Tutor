from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, model_validator

from app.repositories.user_repository import UserRepository, get_user_repository
from app.schemas.auth_me import (
    AuthUserOut,
    OrganizationOut,
    build_auth_user_out,
    load_org_context_for_user,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


class RegisterRequest(BaseModel):
    """Public student registration: personal learning or join a school via invite."""

    account_type: Literal["individual", "organization"] = "individual"
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8)
    grade: Optional[str] = None
    interests: Optional[str] = None
    preferred_teaching_style: Optional[
        Literal["visual", "practical", "theory", "mixed"]
    ] = None
    invite_code: Optional[str] = None
    class_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_by_account_type(self) -> RegisterRequest:
        if self.account_type == "individual":
            if self.grade is None or not str(self.grade).strip():
                raise ValueError("grade is required for individual signup")
            if self.preferred_teaching_style is None:
                raise ValueError(
                    "preferred_teaching_style is required for individual signup"
                )
        else:
            if self.invite_code is None or not str(self.invite_code).strip():
                raise ValueError("invite_code is required for school signup")
            if self.class_id is None or not str(self.class_id).strip():
                raise ValueError("class_id is required for school signup")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterResponse(BaseModel):
    id: str


class LoginResponse(BaseModel):
    token: str
    access_token: str
    token_type: str = "bearer"
    user: AuthUserOut
    organization: OrganizationOut | None = None
    is_institution: bool = False


@router.post("/register", response_model=RegisterResponse)
async def register(
    body: RegisterRequest,
    user_repository: UserRepository = Depends(get_user_repository),
) -> RegisterResponse:
    """Register a new student (individual org or school via invite)."""
    auth_service = AuthService(user_repository)
    try:
        if body.account_type == "individual":
            style = body.preferred_teaching_style
            if style is None:
                raise HTTPException(
                    status_code=400,
                    detail="preferred_teaching_style is required for individual signup",
                )
            user = await auth_service.register_student_individual(
                full_name=body.name,
                email=body.email,
                password=body.password,
                grade=body.grade or "",
                interests=body.interests,
                preferred_teaching_style=style,
            )
        else:
            user = await auth_service.register_student_with_invite(
                full_name=body.name,
                email=body.email,
                password=body.password,
                invite_code=body.invite_code or "",
                class_id=body.class_id or "",
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RegisterResponse(id=str(user.id))


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    user_repository: UserRepository = Depends(get_user_repository),
) -> LoginResponse:
    """Authenticate and return a token plus user id and role."""
    auth_service = AuthService(user_repository)
    user = await auth_service.authenticate_user(email=body.email, password=body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access_token = auth_service.generate_token(user)
    org_out, is_inst = await load_org_context_for_user(user)
    return LoginResponse(
        token=access_token,
        access_token=access_token,
        token_type="bearer",
        user=build_auth_user_out(user),
        organization=org_out,
        is_institution=is_inst,
    )
