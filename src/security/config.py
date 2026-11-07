"""Security configuration. Fails fast (refuses to start) on unsafe settings.

Google OAuth 2.0 / OpenID Connect configuration is required for the public V1 product.
Without these values the app will refuse to start, forcing the operator to configure
Google OAuth before any public deployment.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address

from cryptography.fernet import Fernet

load_dotenv()


class SecurityConfigError(RuntimeError):
    """Raised at startup when the configuration is missing or unsafe."""


_TRUE = {"1", "true", "yes", "on"}
_PLACEHOLDERS = {
    "changeme", "change-me", "change_me", "secret", "password", "your-secret-key",
    "replace-me", "replace_me", "dev", "development", "test", "default",
}


def _flag(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = env.get(name)
    return default if value is None else value.strip().lower() in _TRUE


def is_loopback(host: str) -> bool:
    host = (host or "").strip().strip("[]")
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _int(env: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SecurityConfigError(f"{name} must be an integer.") from exc
    if not lo <= value <= hi:
        raise SecurityConfigError(f"{name} must be between {lo} and {hi}.")
    return value


@dataclass(frozen=True)
class SecurityConfig:
    secret_key: str
    encryption_keys: tuple[str, ...]
    host: str
    port: int
    allow_lan: bool
    https: bool
    session_idle_seconds: int
    session_absolute_seconds: int
    max_upload_bytes: int
    trusted_origins: tuple[str, ...]
    trusted_proxies: int
    setup_token: str
    database_path: str
    snapshot_dir: str
    # Google OAuth 2.0 / OpenID Connect configuration
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    # Whether Google OIDC is the primary auth method (password-based logins are still
    # supported for existing accounts, but new sign-ups use Google)
    google_oidc_primary: bool = True
    # Whether video-file cameras are enabled (demo feature)
    allow_file_sources: bool = False
    # Warnings generated during config validation (e.g. LAN without HTTPS)
    warnings: tuple[str, ...] = ()

    def __repr__(self) -> str:  # never print secrets
        return f"SecurityConfig(host={self.host!r}, port={self.port}, https={self.https}, allow_lan={self.allow_lan})"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SecurityConfig:
        env = os.environ if env is None else env

        # --- debug mode is never allowed (Werkzeug debugger == remote code execution)
        if _flag(env, "DEBUG") or _flag(env, "FLASK_DEBUG"):
            raise SecurityConfigError(
                "Debug mode is not allowed. Remove DEBUG/FLASK_DEBUG and use LOG_LEVEL=DEBUG for verbose logs."
            )

        # --- session signing key
        secret = env.get("SECRET_KEY", "")
        if len(secret) < 32:
            raise SecurityConfigError("SECRET_KEY is missing or shorter than 32 characters. Run: python tools/gen_secrets.py")
        if secret.strip().lower() in _PLACEHOLDERS or len(set(secret)) < 8:
            raise SecurityConfigError("SECRET_KEY looks like a placeholder. Generate a real one: python tools/gen_secrets.py")

        # --- encryption keys (first = primary, others = old keys kept for rotation)
        raw_keys = [k.strip() for k in env.get("SENTINEL_ENCRYPTION_KEYS", "").split(",") if k.strip()]
        if not raw_keys:
            raise SecurityConfigError("SENTINEL_ENCRYPTION_KEYS is missing. Run: python tools/gen_secrets.py")
        for key in raw_keys:
            try:
                Fernet(key.encode())
            except (ValueError, TypeError) as exc:
                raise SecurityConfigError("SENTINEL_ENCRYPTION_KEYS contains an invalid Fernet key.") from exc

        # --- network exposure
        host = env.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
        allow_lan = _flag(env, "SENTINEL_ALLOW_LAN")
        https = _flag(env, "SENTINEL_HTTPS")
        warnings: list[str] = []
        if not is_loopback(host):
            if not allow_lan:
                raise SecurityConfigError(
                    f"HOST={host} exposes the dashboard to the network. Set SENTINEL_ALLOW_LAN=true to confirm you intend this."
                )
            if not https:
                warnings.append(
                    "LAN access is enabled without HTTPS: passwords and session cookies travel in clear text. "
                    "Put a TLS reverse proxy (Caddy/nginx) in front and set SENTINEL_HTTPS=true."
                )
        port = _int(env, "PORT", 5000, 1, 65535)

        origins = tuple(o.strip().rstrip("/") for o in env.get("SENTINEL_TRUSTED_ORIGINS", "").split(",") if o.strip())

        # --- Google OAuth 2.0 / OpenID Connect configuration ---
        # These are REQUIRED for the public V1 product. The app will not start without them.
        google_client_id = env.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        google_client_secret = env.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        google_redirect_uri = env.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()

        if not google_client_id:
            raise SecurityConfigError("GOOGLE_OAUTH_CLIENT_ID is required. Configure it in .env or environment variables.")
        if not google_client_secret:
            raise SecurityConfigError("GOOGLE_OAUTH_CLIENT_SECRET is required. Configure it in .env or environment variables.")
        if not google_redirect_uri:
            raise SecurityConfigError("GOOGLE_OAUTH_REDIRECT_URI is required. Configure it in .env or environment variables.")

        return cls(
            secret_key=secret,
            encryption_keys=tuple(raw_keys),
            host=host,
            port=port,
            allow_lan=allow_lan,
            https=https,
            session_idle_seconds=_int(env, "SESSION_IDLE_MINUTES", 30, 1, 1440) * 60,
            session_absolute_seconds=_int(env, "SESSION_ABSOLUTE_HOURS", 12, 1, 720) * 3600,
            max_upload_bytes=_int(env, "MAX_UPLOAD_MB", 5, 1, 50) * 1024 * 1024,
            trusted_origins=origins,
            trusted_proxies=_int(env, "SENTINEL_TRUSTED_PROXIES", 0, 0, 5),
            setup_token=env.get("SENTINEL_SETUP_TOKEN", "").strip(),
            database_path=env.get("DATABASE_PATH", "data/database/sentinel.db"),
            snapshot_dir=env.get("SNAPSHOT_DIR", "snapshots"),
            google_client_id=google_client_id,
            google_client_secret=google_client_secret,
            google_redirect_uri=google_redirect_uri,
            # Password-based login is retained only for existing accounts; new users use Google OAuth
            google_oidc_primary=True,
            warnings=tuple(warnings),
        )