"""Security response headers. No CORS headers are ever sent: the API is same-origin only."""
from __future__ import annotations

from flask import Flask, request

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)


def install_security_headers(app: Flask, *, https: bool) -> None:
    @app.after_request
    def _headers(resp):
        h = resp.headers
        h["Content-Security-Policy"] = CSP
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Cross-Origin-Resource-Policy"] = "same-origin"
        h["Server"] = "Sentinel"
        if https:
            h["Strict-Transport-Security"] = "max-age=31536000"
        if request.endpoint != "static":
            h["Cache-Control"] = "no-store"
            h["Pragma"] = "no-cache"
        return resp
