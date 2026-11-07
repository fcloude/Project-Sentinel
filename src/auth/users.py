import re
from datetime import datetime, timezone

from flask import session as flask_session

from src.security.config import is_loopback


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


class UserRepository:

    def __init__(self, conn):
        self.conn = conn

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_first_admin(self, username: str, password: str):
        """Creates the admin only if no user exists yet. Returns the id or None."""
        cursor = self.conn.execute(
            """INSERT INTO users (username, password_hash, role, created_at)
            SELECT ?, ?, 'admin', ?
            WHERE NOT EXISTS (SELECT 1 FROM users)""",
            (
                _clean(username),
                generate_password_hash(password),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        return cursor.lastrowid if cursor.rowcount == 1 else None

    def get_by_id(self, user_id):
        row = self.conn.execute(
            "SELECT id, username, role, provider, provider_subject, email, email_verified FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return { "id": row[0], "username": row[1], "role": row[2], "provider": row[3], "provider_subject": row[4], "email": row[5], "email_verified": bool(row[6]) } if row else None

    def verify_external(self, provider: str, provider_subject: str) -> dict | None:
        """Verify an external identity (e.g. Google OAuth) and return user dict, or None.

        This does NOT check passwords - it trusts the OAuth provider's identity.
        """
        row = self.conn.execute(
            "SELECT id, username, role, provider, provider_subject, email, email_verified FROM users WHERE provider = ? AND provider_subject = ?",
            (provider, provider_subject),
        ).fetchone()

        if row is None:
            return None

        return {"id": row[0], "username": row[1], "role": row[2], "provider": row[3], "provider_subject": row[4], "email": row[5], "email_verified": bool(row[6])}

    def _clean(username: str) -> str:
        return (username or "").strip().lower()


class User:
    """Representation of a user in the system.

    Supports both internal (password-based) and external (Google OAuth) accounts.
    """

    def __init__(self, id: int, username: str, role: str, provider: str = "", provider_subject: str = "",
                 email: str = "", email_verified: bool = False):
        self.id = id
        self.username = username
        self.role = role
        self.provider = provider
        self.provider_subject = provider_subject
        self.email = email
        self.email_verified = email_verified