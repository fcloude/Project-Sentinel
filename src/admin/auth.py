"""Admin access control for the ``/admin`` blueprint.

The Admin Control Center is **not** a second application: it reuses the one
``SecurityStore`` (users + audit log) and the session established by
``src/security/auth.py``. There is no separate admin user table, no separate session
key and no separate login form. Signing in at ``/login`` is what grants access, and
the default-deny hook runs before every ``/admin`` endpoint.

Roles are the ones the store already supports: ``admin`` (full access) and ``viewer``
(read-only). A viewer can load no page under ``/admin`` — the panel answers 403.
"""
from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from flask import abort, current_app, g, redirect, request, url_for

from src.security.store import SecurityStore, User


def store() -> SecurityStore:
    return current_app.extensions["sentinel_store"]


def _login_redirect():
    return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))


def _current_user() -> User | None:
    return g.get("user")


def require_admin(view: Callable):
    """Allow only a signed-in user with the ``admin`` role."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        user = _current_user()
        if user is None:  # defence in depth; the global default-deny hook runs first
            return _login_redirect()
        if user.role != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapper


def require_role(*roles: str):
    """Allow only the given roles (kept for future granular roles)."""

    def decorator(view: Callable):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = _current_user()
            if user is None:
                return _login_redirect()
            if user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def audit(action: str, detail: str = "") -> None:
    """Write one audit record through the shared, redacting audit log."""
    user = _current_user()
    if user is None:
        return
    store().audit(
        action,
        user_id=user.id,
        username=user.username,
        ip=request.remote_addr,
        detail=detail,
    )
