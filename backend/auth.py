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
from datetime import datetime, timedelta
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

# How long a session lives without being used. Sliding, not absolute: _lookup
# pushes it out as the token is used, so an active user is never signed out and
# an abandoned session dies 90 days after its last request.
TOKEN_TTL = timedelta(days=90)

# Refresh at most once a day per token. _lookup runs on every authenticated
# request, so an unconditional UPDATE there would put a write on every read.
_REFRESH_AFTER = timedelta(days=1)


def _digest(token: str) -> str:
    """The value stored in auth_tokens. Never store the token itself.

    A plain SHA-256 is the right primitive here, and deliberately not the scrypt
    above: these tokens are 256 bits of `secrets.token_urlsafe` entropy, so there
    is no dictionary to run and nothing for a KDF's cost to buy. Passwords are
    low-entropy and human-chosen, which is what scrypt exists for. This also runs
    on every authenticated request, where a 100 ms hash would be untenable.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
    """Mint a session token. Only its digest is persisted."""
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(
        token=_digest(token),
        user_id=user.id,
        expires_at=datetime.utcnow() + TOKEN_TTL,
    ))
    db.commit()
    # The plaintext leaves here once, in the login response, and thereafter
    # lives only in the client's localStorage. Nothing server-side can recover
    # it -- which is the whole point, and why a lost token means signing in
    # again rather than a lookup.
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
    row = db.query(AuthToken).filter(AuthToken.token == _digest(token)).first()
    if not row:
        return None

    # Fail closed on a missing expiry. Rows predating the expires_at migration
    # are deleted by it (see init_db), so a NULL here means something wrote a
    # row outside issue_token -- treat it as unusable rather than as eternal.
    now = datetime.utcnow()
    if row.expires_at is None or row.expires_at <= now:
        return None

    # Slide the window. Committing on a read path is deliberate and safe here:
    # _lookup is reached either through a FastAPI dependency, before any route
    # body has queued work on this session, or from a route that has only read
    # so far. The guard keeps it to one write per token per day.
    full_ttl = now + TOKEN_TTL
    if full_ttl - row.expires_at > _REFRESH_AFTER:
        row.expires_at = full_ttl
        db.add(row)
        db.commit()

    return db.query(User).filter(User.id == row.user_id).first()


def purge_expired_tokens(db: Session) -> int:
    """Delete sessions that have already lapsed. Housekeeping only.

    _lookup rejects an expired row regardless, so this reclaims space rather
    than enforcing anything. Wired to the scheduler in main.on_startup.
    """
    deleted = db.query(AuthToken).filter(
        AuthToken.expires_at <= datetime.utcnow()
    ).delete(synchronize_session=False)
    db.commit()
    return deleted


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
