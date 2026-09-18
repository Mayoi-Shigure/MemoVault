from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import re
import secrets

password_hasher = PasswordHasher()


def is_csrf_token(value):
    """Only accept the ASCII format produced by token_urlsafe(32)."""
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is not None


def get_csrf_token(session):
    """Lazily provision a token for this session when rendering a form."""
    token = session.get("csrf_token")
    if not is_csrf_token(token):
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def verify_csrf_token(session, submitted):
    # Validation must never mint a token or treat it as authentication.
    expected = session.get("csrf_token")
    return (is_csrf_token(expected) and is_csrf_token(submitted)
            and secrets.compare_digest(expected, submitted))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
