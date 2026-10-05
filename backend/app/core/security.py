from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = "CHANGE_THIS_SECRET_LATER"
ALGORITHM = "HS256"

# bcrypt has a 72-byte limit; newer bcrypt raises if exceeded
BCRYPT_MAX_BYTES = 72

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _normalize_password_for_bcrypt(password: str) -> str:
    """
    Ensure password is a str and at most 72 bytes (UTF-8) so bcrypt never raises.
    Handles accidental non-str or oversized input without breaking normal short passwords.
    """
    if not isinstance(password, str):
        password = str(password)
    encoded = password.encode("utf-8", errors="replace")
    if len(encoded) > BCRYPT_MAX_BYTES:
        password = encoded[:BCRYPT_MAX_BYTES].decode("utf-8", errors="replace")
    return password


def hash_password(password: str) -> str:
    """Hash a plain password. Returns the hashed string. Input is normalized to bcrypt's 72-byte limit."""
    password = _normalize_password_for_bcrypt(password)
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hash. Returns True if match. Plain password is normalized to match hashing."""
    plain_password = _normalize_password_for_bcrypt(plain_password)
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_minutes: int = 60) -> str:
    """Encode a JWT access token with optional expiration. `data` is the payload (e.g. sub, email)."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Decode and validate a JWT. Returns the payload dict or None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
