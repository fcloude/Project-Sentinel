"""Masks credentials in log output (URLs with passwords, Telegram bot tokens, key=value secrets)."""
from __future__ import annotations

import logging
import re

_URL_CREDS = re.compile(r"(://)([^/\s:@]+):([^\s/]+)@")
_TELEGRAM = re.compile(r"(?:bot)?\d{6,12}:[A-Za-z0-9_-]{30,}")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KEYVAL = re.compile(
    r"(?i)(\b[\w-]*(?:password|passwd|pwd|secret|token|api[_-]?key|authorization)[\w-]*)"
    r"([\"']?\s*[:=]\s*[\"']?)([^\s\"',;&]+)"
)


def redact(text: str) -> str:
    text = _URL_CREDS.sub(r"\1\2:***@", text)
    text = _TELEGRAM.sub("***", text)
    text = _BEARER.sub("Bearer ***", text)
    text = _KEYVAL.sub(r"\1\2***", text)
    return text


class RedactingFormatter(logging.Formatter):
    """Redacts the *fully formatted* record, including tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
