"""Username/password accounts.

Deliberately dependency-free: password hashing is stdlib `hashlib.scrypt` and
session tokens are stdlib `secrets.token_urlsafe`. No passlib, no bcrypt, no JWT
library -- the whole auth surface here is register/login/logout plus an opaque
bearer token, which the standard library covers outright.
"""
import hashlib
import hmac
import os
import re
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import AuthToken, User, get_db

# scrypt cost. ~16 MB and ~100 ms per hash -- deliberate, and the reason this
# runs only on register/login and never on a per-request path.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,30}$")
MIN_PASSWORD_LEN = 8


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    return f"scrypt${salt.hex()}${_derive(password, salt).hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split("$")
    except (ValueError, AttributeError):
        return False
    if scheme != "scrypt":
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    return hmac.compare_digest(_derive(password, salt).hex(), hash_hex)


def validate_credentials(username: str, password: str) -> None:
    """Raise 400 if the username/password don't meet the minimum rules."""
    if not username or not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-30 characters, letters/digits/underscore/hyphen only",
        )
    if not password or len(password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters",
        )


def issue_token(db: Session, user: User) -> str:
    # ponytail: tokens never expire; add an expires_at column plus a cleanup job
    # if session hijack ever becomes a real concern for this site.
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(token=token, user_id=user.id))
    db.commit()
    return token


def token_from_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _lookup(db: Session, authorization: Optional[str]) -> Optional[User]:
    token = token_from_header(authorization)
    if not token:
        return None
    row = db.query(AuthToken).filter(AuthToken.token == token).first()
    if not row:
        return None
    return db.query(User).filter(User.id == row.user_id).first()


def optional_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """The signed-in user, or None. Used by the rating routes so anonymous rating keeps working."""
    return _lookup(db, authorization)


def current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """The signed-in user, or 401."""
    user = _lookup(db, authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
