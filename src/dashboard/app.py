import logging
from collections.abc import Mapping

from flask import Flask, current_app, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from src.admin import admin_bp
from src.dashboard.db import close_db
from src.dashboard.routes import register_routes
from src.database.schema import initialize_database
from src.notifications.routes import register_notification_routes
from src.security.auth import init_auth, safe_next
from src.security.config import SecurityConfig
from src.security.crypto import SecretBox
from src.security.csrf import BAD_ORIGIN, MISMATCH, MISSING_TOKEN, NO_SESSION_TOKEN, init_csrf
from src.security.headers import install_security_headers
from src.security.redaction import RedactingFormatter
from src.security.store import SecurityStore

logger = logging.getLogger("sentinel.dashboard")


def create_app(
    engine=None,
    config: SecurityConfig | None = None,
    store: SecurityStore | None = None,
    overrides: Mapping | None = None,
) -> Flask:
    """Build the dashboard.

    ``config`` is the single source of truth for security-relevant settings and refuses to
    be skipped (``SecurityConfig.from_env`` fails fast on unsafe configuration). ``overrides``
    only carries per-deployment view wiring such as ``FACE_SERVICE_FACTORY``; it can never
    change a security setting because those are applied from ``config`` afterwards.

    Google OAuth 2.0 / OpenID Connect is the primary authentication method for V1.
    Password-based logins are retained only for existing accounts that pre-date the migration.
    """
    config = config or SecurityConfig.from_env()  # refuses to start on unsafe config
    store = store or SecurityStore(config.database_path)

    app = Flask(__name__)
    app.debug = False  # never, regardless of FLASK_DEBUG

    initialize_database(config.database_path)

    # View wiring (e.g. FACE_SERVICE_FACTORY) is applied BEFORE the security settings so an
    # override can never weaken SECRET_KEY, cookie flags, upload limits or CSRF-related state.
    if overrides:
        app.config.update(overrides)

    app.config.update(
        SECRET_KEY=config.secret_key,
        ENGINE=engine,
        DATABASE_PATH=config.database_path,
        SNAPSHOT_DIR=config.snapshot_dir,
        SECRET_BOX=SecretBox(config.encryption_keys),
        ALLOW_FILE_SOURCES=config.allow_file_sources,
        SESSION_COOKIE_NAME="__Host-sentinel_session" if config.https else "sentinel_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.https,
        PERMANENT_SESSION_LIFETIME=config.session_absolute_seconds,
        MAX_CONTENT_LENGTH=config.max_upload_bytes,
        PROPAGATE_EXCEPTIONS=False,
        TEMPLATES_AUTO_RELOAD=False,
    )
    if config.trusted_proxies:  # only when a real reverse proxy sits in front
        n = config.trusted_proxies
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    app.logger.handlers = [handler]
    app.logger.propagate = False

    install_security_headers(app, https=config.https)
    init_auth(app, config, store)  # registered first: 401/403 before CSRF
    init_csrf(app, config.trusted_origins)
    app.teardown_appcontext(close_db)

    register_routes(app)
    register_notification_routes(app)
    _register_error_handlers(app)

    # Admin Control Center (separate blueprint, `/admin`). It reuses the same session and
    # role checks as the rest of the app: there is no second login or user table.
    app.register_blueprint(admin_bp)

    for warning in config.warnings:
        app.logger.warning(warning)
    return app

CSRF_MESSAGES = {
    NO_SESSION_TOKEN: "Your session was not available: the browser did not send the session cookie. "
                      "Check that cookies are enabled for this site, then reload and sign in again.",
    MISSING_TOKEN: "The form was submitted without its security token. Reload the page and try again.",
    MISMATCH: "This page is out of date. Reload the page and try again.",
    BAD_ORIGIN: "The request came from a different site and was blocked. Open Sentinel at its own "
                "address and try again.",
}


def _bad_origin_message() -> str:
    """Name the two addresses involved so the cause is obvious instead of a dead end."""
    origin = (request.headers.get("Origin") or "another site")[:120]
    host = (request.host or "its configured address")[:120]
    return (
        f"The request came from a different site ({origin}) and was blocked. "
        f"Sentinel is running at {host}; open that address and try again. "
        "If you reach Sentinel through a reverse proxy or tunnel, add the address you use "
        "to SENTINEL_TRUSTED_ORIGINS."
    )


def _csrf_failure_response(reason: str):
    """Answer a rejected form with a usable page instead of a bare 403.

    Nothing is authenticated here: the request is still refused with 403, the form is
    simply re-rendered with a fresh token so the user can retry.
    """
    if reason == BAD_ORIGIN:
        message = _bad_origin_message()
    else:
        message = CSRF_MESSAGES.get(reason, "The request was blocked. Reload the page and try again.")
    if request.endpoint == "auth.login":
        return render_template("login.html", error=message,
                               next=safe_next(request.values.get("next"))), 403
    if request.endpoint == "auth.setup":
        config = current_app.extensions.get("sentinel_config")
        return render_template("setup.html", error=message, needs_token=bool(
            getattr(config, "setup_token", ""))), 403
    return render_template("error.html", code=403, message=message), 403


def _register_error_handlers(app: Flask) -> None:
    messages = {400: "Bad request", 401: "Authentication required", 403: "Forbidden", 404: "Not found",
                405: "Method not allowed", 413: "Upload too large", 429: "Too many requests"}

    @app.errorhandler(HTTPException)
    def _http(exc: HTTPException):
        code = exc.code or 500
        if code == 403 and g.get("csrf_failure"):
            return _csrf_failure_response(g.csrf_failure)
        msg = messages.get(code, "Error")
        if request.path.startswith("/api/"):
            return jsonify(error=msg), code
        return render_template("error.html", code=code, message=msg), code

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.path)  # details in log only
        if request.path.startswith("/api/"):
            return jsonify(error="Internal server error"), 500
        return render_template("error.html", code=500, message="Internal server error"), 500