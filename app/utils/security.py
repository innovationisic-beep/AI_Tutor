import hashlib
import hmac
import os
from base64 import urlsafe_b64decode, urlsafe_b64encode

PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 210_000
SALT_SIZE = 16


def _b64_encode(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode("utf-8")


def _b64_decode(value: str) -> bytes:
    return urlsafe_b64decode(value.encode("utf-8"))


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256."""
    if not password or len(password) < 8:
        raise ValueError("password must be at least 8 characters long")

    salt = os.urandom(SALT_SIZE)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64_encode(salt)}${_b64_encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a PBKDF2 hash."""
    try:
        scheme, iterations, salt_b64, digest_b64 = password_hash.split("$")
        if scheme != "pbkdf2_sha256":
            return False

        salt = _b64_decode(salt_b64)
        expected_digest = _b64_decode(digest_b64)
        candidate_digest = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(candidate_digest, expected_digest)
    except (ValueError, TypeError):
        return False
