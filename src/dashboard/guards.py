import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, g, jsonify, redirect, request, session, url_for

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def check_csrf():
    """Every state-changing request must carry the session's CSRF token."""
    if request.method in SAFE_METHODS:
        return

    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("csrf_token", "")

    if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
        abort(400, "Invalid or missing CSRF token. Reload the page and try again.")


class LoginRateLimiter:
    """Blocks an address after too many failed logins in a time window."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._failures = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key, now):
        attempts = self._failures[key]
        while attempts and now - attempts[0] > self.window:
            attempts.popleft()

    def is_blocked(self, key) -> bool:
        with self._lock:
            self._prune(key, time.monotonic())
            return len(self._failures[key]) >= self.max_attempts

    def record_failure(self, key) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now)
            self._failures[key].append(now)

    def reset(self, key) -> None:
        with self._lock:
            self._failures.pop(key, None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            if request.path.startswith("/api/"):
                return jsonify(error="Login required."), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def apply_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob: data:; "
        "style-src 'self'; script-src 'self'; frame-ancestors 'none'"
    )
    if not request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response
