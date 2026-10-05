from enum import Enum


class UserRole(str, Enum):
    """Allowed user roles in the platform."""

    student = "student"
    teacher = "teacher"
    parent = "parent"


class UserStatus(str, Enum):
    """User lifecycle status."""

    active = "active"
    suspended = "suspended"


class RelationshipType(str, Enum):
    """Parent-to-student relationship type."""

    mother = "mother"
    father = "father"
    guardian = "guardian"
