"""Regression tests for two production failures.

1. Installs created by the older schema have a ``users`` table without the columns the
   current auth layer reads (``active``/``session_epoch``/``last_login_at``). Every login
   raised ``IndexError``. Both the store and the migration runner must upgrade it in place
   without touching the existing rows or password hashes.
2. CSRF ``bad_origin`` rejections compared raw strings. ``localhost`` and ``127.0.0.1``
   (the same local server, and the exact pair recorded in the audit log) were rejected.
"""
from __future__ import annotations

import re
import sqlite3

from app_support import PASSWORD, log_in, make_security_config

from src.dashboard.app import create_app
from src.database.schema import initialize_database
from src.security import passwords
from src.security.csrf import origin_allowed
from src.security.store import SecurityStore

LEGACY_USERS = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT NOT NULL
);
"""


class FakeEngine:
    def __init__(self):
        self.running = False
        self.calls = []

    @property
    def status(self):
        return {"running": self.running, "thread_alive": self.running}

    def start(self):
        self.calls.append("start")
        self.running = True

    def stop(self):
        self.calls.append("stop")
        self.running = False

    def restart(self):
        self.calls.append("restart")
        self.running = True


def make_legacy_db(tmp_path, username="legacy", password=PASSWORD):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_USERS)
    conn.execute(
        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'admin', ?)",
        (username, passwords.hash_password(password), "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    return path


def columns(path):
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    finally:
        conn.close()


def test_store_upgrades_legacy_users_without_losing_the_account(tmp_path):
    path = make_legacy_db(tmp_path)

    store = SecurityStore(path)

    assert {"active", "session_epoch", "last_login_at"} <= columns(path)
    user = store.get_user_by_name("legacy")
    assert user is not None
    assert user.active is True
    assert user.session_epoch == 0
    # The stored hash is unchanged, so the existing password still works.
    assert passwords.verify_password(user.password_hash, PASSWORD)


def test_migration_runner_upgrades_legacy_users_before_first_use(tmp_path):
    path = make_legacy_db(tmp_path)

    initialize_database(str(path))  # the engine/tools path, which runs before the store

    assert {"active", "session_epoch", "last_login_at"} <= columns(path)
    user = SecurityStore(path).get_user_by_name("legacy")
    assert user is not None and user.active is True


def test_create_app_overrides_cannot_weaken_security_settings(tmp_path):
    config = make_security_config(tmp_path)
    app = create_app(engine=None, config=config, overrides={
        "SECRET_KEY": "attacker-chosen-key-0123456789abcdef",
        "SESSION_COOKIE_HTTPONLY": False,
        "MAX_CONTENT_LENGTH": 10**9,
    })

    assert app.config["SECRET_KEY"] == config.secret_key
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["MAX_CONTENT_LENGTH"] == config.max_upload_bytes


def test_legacy_admin_can_actually_log_in(tmp_path):
    path = make_legacy_db(tmp_path)
    app = create_app(
        engine=FakeEngine(),
        config=make_security_config(tmp_path, DATABASE_PATH=str(path)),
    )
    app.config["TESTING"] = True
    client = app.test_client()

    log_in(client, "legacy", PASSWORD)

    assert client.get("/").status_code == 200


# ---------------------------------------------------------------- origin policy


def test_origin_allowed_matches_normalized_authorities():
    request_authority = ("https", "sentinel.example.com", 443)
    assert origin_allowed("https://sentinel.example.com", (), request_authority)
    assert origin_allowed("https://sentinel.example.com:443", (), request_authority)
    assert origin_allowed("https://SENTINEL.example.com./", (), request_authority)
    assert origin_allowed("https://sentinel.example.com", ("https://sentinel.example.com:443",),
                          request_authority)


def test_origin_allowed_treats_loopback_names_as_one_server():
    request_authority = ("http", "127.0.0.1", 5000)
    assert origin_allowed("http://localhost:5000", (), request_authority)
    assert origin_allowed("http://[::1]:5000", (), request_authority)
    assert origin_allowed("http://127.0.0.1:5000", (), request_authority)
    # A different port is a different server, even on loopback.
    assert not origin_allowed("http://localhost:5001", (), request_authority)
    # A remote host is never interchangeable with loopback.
    assert not origin_allowed("https://evil.example", (), request_authority)


def test_origin_allowed_rejects_foreign_null_and_garbage():
    # null from loopback should be accepted (same machine)
    request_authority_loopback = ("http", "127.0.0.1", 5000)
    assert origin_allowed("null", (), request_authority_loopback), "null from loopback should be accepted"
    
    # null from foreign origin should be rejected
    request_authority_foreign = ("https", "evil.example.com", 443)
    for origin in ("null", "not-a-url", "", "file:///etc/passwd"):
        assert not origin_allowed(origin, (), request_authority_foreign), origin
    
    # Other origins should still be rejected as before
    for origin in ("https://evil.example", "http://127.0.0.1.evil.example:5000"):
        assert not origin_allowed(origin, (), request_authority_loopback), origin


def _page_token(html: bytes) -> str:
    match = re.search(rb'name="csrf-token" content="([^"]+)"', html) or re.search(
        rb'name="csrf_token" value="([^"]+)"', html
    )
    assert match is not None
    return match.group(1).decode()


def auth_client(tmp_path, host="localhost", **config):
    """Sign in *as that host*, so the session cookie is scoped like a real browser's."""
    engine = FakeEngine()
    app = create_app(engine=engine, config=make_security_config(tmp_path, **config))
    app.config["TESTING"] = True
    client = app.test_client()
    environ = {"HTTP_HOST": host}

    setup_page = client.get("/setup", environ_overrides=environ)
    if setup_page.status_code == 200:
        client.post("/setup", data={
            "csrf_token": _page_token(setup_page.data),
            "username": "admin", "password": PASSWORD, "confirm": PASSWORD,
        }, environ_overrides=environ)

    login_page = client.get("/login", environ_overrides=environ)
    client.post("/login", data={
        "csrf_token": _page_token(login_page.data),
        "username": "admin", "password": PASSWORD,
    }, environ_overrides=environ)

    home = client.get("/", environ_overrides=environ)
    assert home.status_code == 200
    return app, client, engine, _page_token(home.data)


def test_localhost_form_posted_to_127_is_accepted(tmp_path):
    """The exact rejection recorded in audit_log: Origin localhost, Host 127.0.0.1."""
    _, client, engine, token = auth_client(tmp_path, host="127.0.0.1:5000")

    response = client.post(
        "/engine/start",
        data={"csrf_token": token},
        headers={"Origin": "http://localhost:5000"},
        environ_overrides={"HTTP_HOST": "127.0.0.1:5000"},
    )

    assert response.status_code == 302
    assert engine.calls == ["start"]


def test_origin_with_a_different_port_is_still_rejected_and_explained(tmp_path):
    app, client, engine, token = auth_client(tmp_path, host="127.0.0.1:5000")

    response = client.post(
        "/engine/start",
        data={"csrf_token": token},
        headers={"Origin": "http://localhost:5050"},
        environ_overrides={"HTTP_HOST": "127.0.0.1:5000"},
    )

    assert response.status_code == 403
    assert b"different site" in response.data
    assert b"localhost:5050" in response.data  # names the address that was refused
    assert engine.calls == []
    details = [row["detail"] for row in app.extensions["sentinel_store"].recent_audit()
               if row["action"] == "csrf_denied"]
    assert any("origin=http://localhost:5050" in d and "host=127.0.0.1:5000" in d for d in details)


def test_foreign_origin_is_rejected_even_with_a_valid_token(tmp_path):
    _, client, engine, token = auth_client(tmp_path)

    response = client.post(
        "/engine/start",
        data={"csrf_token": token},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert engine.calls == []


def test_csrf_token_is_still_required_when_the_origin_is_allowed(tmp_path):
    _, client, engine, _ = auth_client(tmp_path)

    response = client.post(
        "/engine/start",
        headers={"Origin": "http://localhost"},
        environ_overrides={"HTTP_HOST": "localhost"},
    )

    assert response.status_code == 403
    assert engine.calls == []


def test_trusted_origin_is_compared_after_normalization(tmp_path):
    _, client, engine, token = auth_client(
        tmp_path, SENTINEL_TRUSTED_ORIGINS="https://Sentinel.Example.com/"
    )

    response = client.post(
        "/engine/start",
        data={"csrf_token": token},
        headers={"Origin": "https://sentinel.example.com:443"},
    )

    assert response.status_code == 302
    assert engine.calls == ["start"]
