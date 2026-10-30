import re
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128

_dummy_hash = None


def validate_username(username):
    if USERNAME_RE.match(username or ""):
        return None
    return "Username must be 3-32 characters: letters, numbers, dot, dash or underscore."


def validate_password(password):
    password = password or ""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    return None


def _fake_hash() -> str:
    # Checked when the username doesn't exist, so response time doesn't
    # reveal which usernames are real.
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = generate_password_hash("not-a-real-password")
    return _dummy_hash


def _clean(username: str) -> str:
    return (username or "").strip().lower()


class UserRepository:

    def __init__(self, conn):
        self.conn = conn

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_first_admin(self, username: str, password: str):
        """Creates the admin only if no user exists yet. Returns the id or None."""
        cursor = self.conn.execute(
            """
            INSERT INTO users (username, password_hash, role, created_at)
            SELECT ?, ?, 'admin', ?
            WHERE NOT EXISTS (SELECT 1 FROM users)
            """,
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
            "SELECT id, username, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return {"id": row[0], "username": row[1], "role": row[2]} if row else None

    def verify(self, username: str, password: str):
        row = self.conn.execute(
            "SELECT id, username, role, password_hash FROM users WHERE username = ?",
            (_clean(username),),
        ).fetchone()

        if row is None:
            check_password_hash(_fake_hash(), password or "")
            return None

        if not check_password_hash(row[3], password or ""):
            return None

        return {"id": row[0], "username": row[1], "role": row[2]}
