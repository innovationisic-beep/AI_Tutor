"""
Create a user with role=admin (for bootstrapping). Not for public registration.

Usage (from the `backend` directory):
  python create_admin.py

Environment:
  ADMIN_EMAIL     default: admin@example.com
  ADMIN_PASSWORD  required for production; default dev password if unset
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Resolve package root when run as `python create_admin.py`
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

    email = os.getenv("ADMIN_EMAIL", "admin@example.com").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "changeme_admin_1").strip()
    if len(password) < 8:
        print("ADMIN_PASSWORD must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

    repo = UserRepository()
    svc = AuthService(repo)
    existing = await repo.get_by_email(email)
    if existing is not None:
        print(f"User already exists for email={email!r} (id={existing.id}).")
        return

    user = await svc.create_system_user(email=email, password=password, role="admin")
    print(f"Created admin user id={user.id} email={email!r}")


if __name__ == "__main__":
    asyncio.run(main())
