"""User model and role type (re-export for a stable import path)."""

from app.models.identification.users import User, UserRole

__all__ = ["User", "UserRole"]
