from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.dependencies import get_current_user
from app.models.identification.users import User
from app.schemas.auth_me import (
    AuthUserOut,
    OrganizationOut,
    build_auth_user_out,
    load_org_context_for_user,
)

router = APIRouter(prefix="/users", tags=["Users"])


class MeResponse(BaseModel):
    user: AuthUserOut
    organization: OrganizationOut | None = None
    is_institution: bool = False


@router.get("/me", response_model=MeResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> MeResponse:
    """Return the current user plus organization context for client routing."""
    org_out, is_inst = await load_org_context_for_user(current_user)
    return MeResponse(
        user=build_auth_user_out(current_user),
        organization=org_out,
        is_institution=is_inst,
    )
