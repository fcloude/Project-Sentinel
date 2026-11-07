"""SQLite store for users, roles and the audit log. One short-lived connection per operation
(never share a connection across threads).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.security.redaction import redact

logger = logging.getLogger(__name__)

# Columns the auth layer needs on ``users``. Older builds created the table without
# ``active``/``session_epoch``/``last_login_at``, which made every login raise IndexError.
# Adding a column preserves the existing rows (and password hashes).
_REQUIRED_USER_COLUMNS = {
    "active": "INTEGER NOT NULL DEFAULT 1",
    "session_epoch": "INTEGER NOT NULL DEFAULT 0",
    "last_login_at": "TEXT",
}

# Google authentication columns
_GOOGLE_USER_COLUMNS = {
    "provider": "TEXT NOT NULL DEFAULT ''",
    "provider_subject": "TEXT NOT NULL DEFAULT ''",
    "email": "TEXT COLLATE NOCASE",
    "email_verified": "INTEGER NOT NULL DEFAULT 0",
}

# All possible user columns, in order. New installs get all of them; legacy databases
# get the missing ones added idempotently.
_ALL_USER_COLUMNS = [
    "id",
    "username",
    "password_hash",
    "role",
    "created_at",
    "active",
    "session_epoch",
    "last_login_at",
    "provider",
    "provider_subject",
    "email",
    "email_verified",
]


def ensure_user_columns(conn: sqlite3.Connection) -> None:
    """Idempotently add columns that a legacy ``users`` table may be missing.

    Called by :class:`SecurityStore` (so auth works even before migrations run) and by
    ``initialize_database`` (so an upgraded install converges on the current schema).
    The column names are the fixed constants above, never user input.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    # Add required auth columns first
    for name, ddl in _REQUIRED_USER_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")  # sentinel-ok: fixed constants
            logger.info("Migrated users table: added column %s", name)

    # Add Google authentication columns
    for name, ddl in _GOOGLE_USER_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")  # sentinel-ok: fixed constants
            logger.info("Migrated users table: added column %s (Google auth)", name)


_SCHEMA = """CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
    active INTEGER NOT NULL DEFAULT 1,
    session_epoch INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user_id INTEGER,
    username TEXT,
    action TEXT NOT NULL,
    ip TEXT,
    detail TEXT
);CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""



@dataclass(frozen=True, slots=True)
class User:
    """Representation of a user in the system.

    Supports both internal (password-based) and external (Google OAuth) accounts.
    """

    id: int
    username: str
    password_hash: str  # empty string for externally-authenticated accounts
    role: str
    active: bool
    session_epoch: int

    # Google OAuth fields (empty/absent for password-based accounts)
    provider: str = ""
    provider_subject: str = ""
    email: str = ""
    email_verified: bool = False


def _row_to_user(row: sqlite3.Row | None) -> User | None:
    if row is None:
        return None
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        role=row["role"],
        active=bool(row["active"]),
        session_epoch=row["session_epoch"],
        provider=row["provider"] if "provider" in row else "",
        provider_subject=row["provider_subject"] if "provider_subject" in row else "",
        email=row["email"] if "email" in row else "",
        email_verified=bool(row["email_verified"] if "email_verified" in row else 0),
    )


class SecurityStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = str(path)
        parent = Path(self.path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with self._tx() as conn:
            conn.executescript(_SCHEMA)
            ensure_user_columns(conn)
        for target, mode in ((parent, 0o700), (Path(self.path), 0o600)):
            try:
                os.chmod(target, mode)  # no-op / ignored on Windows
            except OSError:
                pass

    @contextmanager
    def _tx(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------ users
    def count_users(self) -> int:
        with self._tx() as c:
            return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def get_user(self, user_id: int) -> User | None:
        with self._tx() as c:
            return _row_to_user(c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def get_user_by_name(self, username: str) -> User | None:
        with self._tx() as c:
            return _row_to_user(c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())

    def list_users(self) -> list[User]:
        with self._tx() as c:
            return [_row_to_user(r) for r in c.execute("SELECT * FROM users ORDER BY id").fetchall()]  # type: ignore[misc]

    def create_first_admin(self, username: str, password_hash: str) -> User | None:
        """Atomic: succeeds only if the users table is empty (two simultaneous setups can't both win)."""
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO users (username, password_hash, role, created_at) "
                "SELECT ?, ?, 'admin', ? WHERE NOT EXISTS (SELECT 1 FROM users)",
                (username, password_hash, datetime.now(timezone.utc).isoformat()),
            )
            if cur.rowcount != 1:
                return None
        return self.get_user_by_name(username)

    def create_user(self, username: str, password_hash: str, role: str) -> User:
        if role not in ("admin", "viewer"):
            raise ValueError("Invalid role.")
        with self._tx() as c:
            c.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, role, datetime.now(timezone.utc).isoformat()),
            )
        return self.get_user_by_name(username)  # type: ignore[return-value]

    def set_password(self, user_id: int, password_hash: str) -> None:
        """Changes the hash AND invalidates every existing session of that user."""
        with self._tx() as c:
            c.execute(
                "UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1 WHERE id = ?",
                (password_hash, user_id),
            )

    def update_hash(self, user_id: int, password_hash: str) -> None:
        """Transparent re-hash after login (algorithm upgrade). Does NOT invalidate sessions."""
        with self._tx() as c:
            c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))

    def revoke_sessions(self, user_id: int) -> None:
        with self._tx() as c:
            c.execute("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?", (user_id,))

    def set_active(self, user_id: int, active: bool) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE users SET active = ?, session_epoch = session_epoch + 1 WHERE id = ?",
                (1 if active else 0, user_id),
            )

    def delete_user(self, user_id: int) -> None:
        """Remove a user. The audit log keeps their username for accountability."""
        with self._tx() as c:
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def record_login(self, user_id: int) -> None:
        with self._tx() as c:
            c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), user_id))

    # ------------------------------------------------------------ Google auth

    def find_by_external_id(self, provider: str, provider_subject: str) -> User | None:
        """Find a user by their external provider + subject ID.

        Returns the user record if found, or None if no matching account exists.
        """
        with self._tx() as c:
            row = c.execute(
                "SELECT * FROM users WHERE provider = ? AND provider_subject = ?",
                (provider, provider_subject),
            ).fetchone()
            return _row_to_user(row) if row else None

    def find_by_email(self, email: str) -> User | None:
        """Find a user by email address.

        Returns the user record if found, or None. Note: email addresses are NOT
        assumed immutable — the same email could be re-registered under a different
        provider. This method just locates existing accounts.
        """
        with self._tx() as c:
            row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            return _row_to_user(row) if row else None

    def upsert_by_google(self, provider_subject: str, email: str, email_verified: bool, name: str) -> User:
        """Link or create a user account using Google OAuth data.

        Policy:
        - If a user already exists with the same ``provider_subject``, return it
          (no automatic email-based linking — the caller must decide if linking is wanted).
        - If a user exists with the same ``email`` but a different ``provider_subject``,
          return the existing record (do not auto-link).
        - If no matching account exists, create a new one with the given email and name.
        """
        # 1. Try to find by provider_subject first (the primary external identity)
        user = self.find_by_external_id("google", provider_subject)
        if user is not None:
            # Update email info in case it changed
            if user.email != email or user.email_verified != email_verified:
                with self._tx() as c:
                    c.execute(
                        "UPDATE users SET email = ?, email_verified = ? WHERE id = ?",
                        (email, 1 if email_verified else 0, user.id),
                    )
            return user

        # 2. Try to find by email — if another user has this email under a different provider,
        #    we do NOT auto-link. Just return the existing user (or None if no email match).
        by_email = self.find_by_email(email)
        if by_email is not None:
            # Email exists under a different provider; do not auto-link.
            # Update the provider_subject on this existing record if it's currently empty.
            if not by_email.provider_subject and provider_subject:
                with self._tx() as c:
                    c.execute(
                        "UPDATE users SET provider = 'google', provider_subject = ? WHERE id = ?",
                        (provider_subject, by_email.id),
                    )
            return by_email

        # 3. No matching account exists — create a new one
        # Generate a username from the email local part (or use the name if available)
        username = email.split("@")[0] if email else name or "google-user"
        # Ensure uniqueness at the application level (the DB may have a UNIQUE index,
        # but we handle gracefully for legacy databases)
        base_username = username
        counter = 1
        while self.get_user_by_name(username):
            username = f"{base_username}{counter}"
            counter += 1

        # Try to create the user; if email uniqueness fails, append a suffix
        try:
            new_user = self.create_user(username, "", "viewer")  # password_hash empty for external
        except sqlite3.IntegrityError:
            # Email already exists; try with a suffix
            username = f"{base_username}{counter}"
            counter += 1
            new_user = self.create_user(username, "", "viewer")

        # Now set the Google fields
        with self._tx() as c:
            c.execute(
                "UPDATE users SET provider = 'google', provider_subject = ?, email = ?, email_verified = ? WHERE id = ?",
                (provider_subject, email, 1 if email_verified else 0, new_user.id),
            )
        return new_user

    # ------------------------------------------------------------ audit log
    def audit(self, action: str, *, user_id: int | None = None, username: str | None = None,
              ip: str | None = None, detail: str = "") -> None:
        """Never raises: an audit failure must not break the request. Never put secrets in `detail`."""
        try:
            with self._tx() as c:
                c.execute(
                    "INSERT INTO audit_log (ts, user_id, username, action, ip, detail) VALUES (?, ?, ?, ?, ?, ?)",
                    (datetime.now(timezone.utc).isoformat(), user_id, (username or "")[:64] or None,
                     action[:64], (ip or "")[:64] or None, redact(detail)[:500]),
                )
        except Exception:
            logger.exception("Failed to write audit log entry")

    def recent_audit(self, limit: int = 100) -> list[sqlite3.Row]:
        with self._tx() as c:
            return c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()