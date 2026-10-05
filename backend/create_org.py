"""
Create a user with role=organization (tenant admin bootstrap). Not for public registration.

Usage (from the `backend` directory):
  python create_org.py

Environment:
  ORG_ADMIN_EMAIL     default: org@example.com
  ORG_ADMIN_PASSWORD  default dev password if unset (min 8 chars)

Note: `create_system_user` provisions a personal workspace organization for this user
(same pattern as create_admin for admin). To attach a user to an existing tenant
`Organization` document, use the API or extend AuthService with an optional org id.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


async def main() -> None:
    from app.core.config import Settings
    from app.core.database import connect_to_mongo
    from app.repositories.user_repository import UserRepository
    from app.services.auth_service import AuthService

    settings = Settings()
    await connect_to_mongo(mongodb_url=settings.MONGODB_URL)

    email = os.getenv("ORG_ADMIN_EMAIL", "org@example.com").strip().lower()
    password = os.getenv("ORG_ADMIN_PASSWORD", "12345678").strip()
    if len(password) < 8:
        print("ORG_ADMIN_PASSWORD must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

    repo = UserRepository()
    svc = AuthService(repo)
    existing = await repo.get_by_email(email)
    if existing is not None:
        print(f"User already exists for email={email!r} (id={existing.id}).")
        return

    user = await svc.create_system_user(
        email=email,
        password=password,
        role="organization",
    )
    print(f"Created organization-role user id={user.id} email={email!r}")


if __name__ == "__main__":
    asyncio.run(main())
