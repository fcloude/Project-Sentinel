from datetime import timedelta

from flask import Flask

from src.dashboard.db import close_db
from src.dashboard.guards import apply_security_headers, check_csrf, csrf_token
from src.dashboard.routes import register_routes
from src.database import manager
from src.database.schema import initialize_database
from src.security.crypto import SecretBox, get_secret_key


def create_app(engine=None, config=None):
    app = Flask(__name__)

    settings = manager.settings
    secret = get_secret_key(settings.database_path)

    app.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.cookie_secure,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=30 * 1024 * 1024,
        ENGINE=engine,
        ALLOW_FILE_SOURCES=settings.allow_file_sources,
    )
    if config:
        app.config.update(config)

    app.config["SECRET_BOX"] = SecretBox(secret)

    initialize_database()

    app.jinja_env.globals["csrf_token"] = csrf_token
    app.before_request(check_csrf)
    app.after_request(apply_security_headers)
    app.teardown_appcontext(close_db)

    register_routes(app)
    return app
