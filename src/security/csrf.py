"""CSRF protection: per-session token (header or form field) + Origin check on state-changing requests.

A rejected login used to surface as a bare ``403 Forbidden``. The token lives in the
session cookie, so the usual causes are a cookie the browser did not send (blocked
cookie, ``Secure`` cookie over plain HTTP, cleared data) or a page rendered before the
session was rotated (log out, password change, restart with a new ``SECRET_KEY``).

Each rejection now records a reason, is written to the audit log and is logged — including
the two authorities involved for ``bad_origin`` — and the app can answer the login/setup
form with a fresh token instead of a dead end.

Origin comparison is done on a normalized ``(scheme, host, port)`` triple rather than raw
strings, so ``https://example.com`` and ``https://example.com:443`` agree. ``localhost``,
``127.0.0.1`` and ``::1`` are accepted as the same authority **only** when both sides are
loopback and the scheme/port match: that is one local server reached by two names, which is
common on local-first installs and cannot be forged by a remote site.
"""

from __future__ import annotations

import hmac
import secrets
from ipaddress import ip_address
from urllib.parse import urlsplit

from flask import Flask, abort, current_app, g, request, session

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SESSION_KEY = "_csrf"

# Why the request was rejected. Kept short because it is stored in the audit log.
BAD_ORIGIN = "bad_origin"        # Origin header from an untrusted site
NO_SESSION_TOKEN = "no_session"  # the session cookie is missing/expired/blocked  # sentinel-ok
MISSING_TOKEN = "missing_token"  # a session exists but the request carried no token  # sentinel-ok
MISMATCH = "mismatch"            # the token does not belong to this session

_DEFAULT_PORTS = {"http": 80, "https": 443}


def get_token() -> str:
    token = session.get(SESSION_KEY)
    if not token:
        token = session[SESSION_KEY] = secrets.token_urlsafe(32)
    return token


def _authority(value: str) -> tuple[str, str, int] | None:
    """``scheme://host[:port]`` -> ``(scheme, host, port)`` with defaults applied."""
    try:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        return None
    if not scheme or not host:
        return None
    if port is None:
        port = _DEFAULT_PORTS.get(scheme)
        if port is None:
            return None
    return scheme, host, port


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _request_authority() -> tuple[str, str, int] | None:
    return _authority(f"{request.scheme}://{request.host}")


def origin_allowed(origin: str, trusted: tuple[str, ...], request_authority=None) -> bool:
    """Is ``origin`` the same authority as this request (or an explicitly trusted one)?"""
    if origin == "null":
        # ``Origin: null`` is rejected to prevent circumvention.
        # Browsers send this when the origin is unknown or for file:// URLs,
        # and it should not be trusted for cross-origin requests.
        # Same-origin requests with a proper Origin header are still allowed.
        return False
    candidate = _authority(origin)
    if candidate is None:
        return False
    if any(_authority(entry) == candidate for entry in trusted):
        return True

    expected = request_authority if request_authority is not None else _request_authority()
    if expected is None:
        return False
    if candidate == expected:
        return True
    # One local server reached as localhost and 127.0.0.1/::1. Same scheme and port,
    # both loopback: it is the same machine and cannot be a remote cross-site request.
    return (
        candidate[0] == expected[0]
        and candidate[2] == expected[2]
        and _is_loopback(candidate[1])
        and _is_loopback(expected[1])
    )


def _reject(reason: str) -> None:
    """Record why CSRF validation failed, then refuse the request."""
    g.csrf_failure = reason
    # Host and Origin are not secrets, and are what actually explains a bad_origin
    # rejection. Keep them short so a hostile header can't flood the log.
    origin = (request.headers.get("Origin") or "-")[:120]
    host = (request.host or "-")[:120]
    current_app.logger.warning(
        "CSRF rejected (%s) on %s %s [origin=%s host=%s]",
        reason, request.method, request.path, origin, host,
    )
    store = current_app.extensions.get("sentinel_store")
    if store is not None:
        user = g.get("user")
        store.audit(
            "csrf_denied",
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None),
            ip=request.remote_addr,
            detail=f"{reason} {request.method} {request.path} origin={origin} host={host}",
        )
    abort(403)


def init_csrf(app: Flask, trusted_origins: tuple[str, ...] = ()) -> None:
    app.jinja_env.globals["csrf_token"] = get_token

    @app.before_request
    def _csrf_protect():
        if request.method in SAFE_METHODS:
            return None
        origin = request.headers.get("Origin")
        if origin and not origin_allowed(origin, trusted_origins):
            _reject(BAD_ORIGIN)
        expected = session.get(SESSION_KEY)
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
        if not expected:
            _reject(NO_SESSION_TOKEN)
        if not supplied:
            _reject(MISSING_TOKEN)
        if not hmac.compare_digest(str(expected), str(supplied)):
            _reject(MISMATCH)
        return None