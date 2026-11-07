"""Password hashing + policy. argon2id when argon2-cffi is installed, scrypt otherwise."""
from __future__ import annotations

import secrets

from werkzeug.security import check_password_hash, generate_password_hash

try:  # preferred
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

    _ph: PasswordHasher | None = PasswordHasher()
except ImportError:  # pragma: no cover - depends on environment
    _ph = None

MIN_LENGTH = 10
MAX_LENGTH = 128

_COMMON = frozenset({
    "password", "password1", "passw0rd", "1234567890", "12345678910", "qwertyuiop",
    "qwerty12345", "iloveyou12", "administrator", "letmein123", "welcome123",
    "sentinel123", "projectsentinel", "admin12345", "changeme123",
})


class PasswordPolicyError(ValueError):
    """The password does not meet the policy (message is safe to show the user)."""


def check_policy(password: str, username: str = "") -> None:
    if not isinstance(password, str):
        raise PasswordPolicyError("Invalid password.")
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"Password must be at most {MAX_LENGTH} characters.")
    low = password.lower()
    if low in _COMMON or (username and low == username.lower()):
        raise PasswordPolicyError("That password is too easy to guess.")
    if len(set(password)) < 5:
        raise PasswordPolicyError("Password is too repetitive.")


def hash_password(password: str, *, enforce_policy: bool = True, username: str = "") -> str:
    if enforce_policy:
        check_policy(password, username)
    if _ph is not None:
        return _ph.hash(password)
    return generate_password_hash(password, method="scrypt")


def verify_password(stored: str, password: str) -> bool:
    if not isinstance(stored, str) or not isinstance(password, str) or len(password) > MAX_LENGTH:
        return False
    try:
        if stored.startswith("$argon2"):
            return _ph is not None and bool(_ph.verify(stored, password))
        return check_password_hash(stored, password)
    except Exception:  # mismatch, malformed hash, etc. -> never raise to caller
        return False


def needs_rehash(stored: str) -> bool:
    if _ph is None:
        return False
    if not stored.startswith("$argon2"):
        return True
    try:
        return _ph.check_needs_rehash(stored)
    except Exception:
        return True


# Verified against when the username does not exist, so response time doesn't reveal valid usernames.
DUMMY_HASH = hash_password(secrets.token_urlsafe(18), enforce_policy=False)
