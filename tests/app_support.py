"""Helpers for building a test app.

Tests never read the developer's ``.env``: they pass an explicit ``SecurityConfig`` built
from a fixed, non-secret test key, a temporary database and a temporary snapshot folder.

Google OAuth 2.0 / OpenID Connect is required for the V1 public product. Tests provide
dummy values that satisfy the config validation without using real Google credentials.
"""

from __future__ import annotations

import dataclasses
import re

from cryptography.fernet import Fernet

from src.database import manager
from src.security.config import SecurityConfig

SECRET_KEY = "pytest-secret-key-0123456789-abcdefghijklmnop"
PASSWORD = "correct-horse-battery"


def make_security_config(tmp_path, encryption_key: str | None = None, **overrides) -> SecurityConfig:
    env = {
        "SECRET_KEY": SECRET_KEY,
        "SENTINEL_ENCRYPTION_KEYS": encryption_key or Fernet.generate_key().decode(),
        "DATABASE_PATH": str(tmp_path / "data" / "test.db"),
        "SNAPSHOT_DIR": str(tmp_path / "snapshots"),
        "ALLOW_FILE_SOURCES": "true",
        # Google OAuth required for V1 public product - dummy values for testing
        "GOOGLE_OAUTH_CLIENT_ID": "test-google-client-id",
        "GOOGLE_OAUTH_CLIENT_SECRET": "test-google-client-secret",
        "GOOGLE_OAUTH_REDIRECT_URI": "http://localhost/auth/google-callback",
        **overrides,
    }
    return SecurityConfig.from_env(env)


def use_temporary_database(tmp_path, monkeypatch, **overrides):
    """Point the process-wide settings (repositories, engine, face service) at tmp_path too."""
    test_settings = dataclasses.replace(
        manager.settings,
        database_path=str(tmp_path / "data" / "test.db"),
        allow_file_sources=True,
        **overrides,
    )
    monkeypatch.setattr(manager, "settings", test_settings)
    return test_settings


def csrf_token(client, path: str = "/") -> str:
    """Read the CSRF token from whichever page is rendering it.

    Pages using ``base.html`` expose it as a ``<meta>`` tag; the standalone login/setup
    forms carry it as a hidden field.
    """
    html = client.get(path, follow_redirects=True).get_data(as_text=True)
    match = re.search(r'name="csrf-token" content="([^"]+)"', html) or re.search(
        r'name="csrf_token" value="([^"]+)"', html
    )
    if match is None:
        raise AssertionError(f"No CSRF token on {path}")
    return match.group(1)


def register(client, username: str = "admin", password: str = PASSWORD, path: str = "/setup"):
    """Create the first admin. The setup wizard deliberately does not sign the user in."""
    return client.post(
        path,
        data={
            "username": username,
            "password": password,
            "confirm": password,
            "csrf_token": csrf_token(client, path),
        },
    )


def sign_in(client, username: str = "admin", password: str = PASSWORD):
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf_token(client, "/login")},
    )


def log_in(client, username: str = "admin", password: str = PASSWORD) -> None:
    """Sign in, creating the first admin first if the install is still empty."""
    if client.get("/setup").status_code == 200:
        register(client, username, password)
    sign_in(client, username, password)


def google_sign_in(client):
    """Initiate Google OAuth sign-in and return the redirect response.

    The user is redirected to Google's consent screen. After the user approves,
    they are redirected back to the Google callback endpoint.
    """
    return client.get("/google-login")