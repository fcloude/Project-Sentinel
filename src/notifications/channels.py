import hashlib
import hmac
import json
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

import requests

from src.camera.url_utils import mask_url
from src.errors import UserFacingError
from src.notifications.webpush import PushSubscriptionGone

REQUEST_TIMEOUT = 10
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{20,}$")
CHAT_ID_RE = re.compile(r"^(-?\d{3,20}|@[A-Za-z0-9_]{4,})$")
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


# ---------------------------------------------------------------------------
# What each channel type needs (drives the "Add channel" forms)
# ---------------------------------------------------------------------------

CHANNEL_TYPES = {
    "inapp": {"label": "In-app", "fields": [], "builtin": True},
    "telegram": {
        "label": "Telegram (your own bot)",
        "help": "Create a bot with @BotFather, send it a message, then paste its token and your chat ID.",
        "fields": [
            {"name": "bot_token", "label": "Bot token", "kind": "password", "required": True},
            {"name": "chat_id", "label": "Chat ID", "kind": "text", "required": True,
             "placeholder": "123456789"},
        ],
    },
    "email": {
        "label": "Email",
        "help": "Use your own mail account's SMTP settings (for Gmail, use an app password).",
        "fields": [
            {"name": "host", "label": "SMTP server", "kind": "text", "required": True,
             "placeholder": "smtp.example.com"},
            {"name": "port", "label": "Port", "kind": "number", "required": True, "default": "587"},
            {"name": "security", "label": "Security", "kind": "select",
             "choices": [("starttls", "STARTTLS (usually port 587)"),
                         ("ssl", "SSL/TLS (usually port 465)"),
                         ("none", "None (not recommended)")]},
            {"name": "username", "label": "Username (optional)", "kind": "text"},
            {"name": "password", "label": "Password (optional)", "kind": "password"},
            {"name": "from_addr", "label": "From address", "kind": "text", "required": True},
            {"name": "to_addrs", "label": "Send to (comma-separated)", "kind": "text", "required": True},
        ],
    },
    "webhook": {
        "label": "Webhook",
        "help": "Sentinel POSTs JSON to this address. Works with Home Assistant, n8n, Slack/Discord relays, ntfy and more.",
        "fields": [
            {"name": "url", "label": "Address (http:// or https://)", "kind": "text", "required": True},
            {"name": "secret", "label": "Signing secret (optional)", "kind": "password"},
        ],
    },
    "webpush": {"label": "Phone / browser push", "fields": [], "builtin": True},
}


def _clean(form, name) -> str:
    return (form.get(name) or "").strip()


def validate_channel(type_, form):
    """Form values -> (config, None) or (None, friendly error)."""
    if type_ == "telegram":
        token, chat = _clean(form, "bot_token"), _clean(form, "chat_id")
        if not TOKEN_RE.match(token):
            return None, "That doesn't look like a Telegram bot token (it looks like 123456789:AAH...)."
        if not CHAT_ID_RE.match(chat):
            return None, "Chat ID must be a number (or @channelname)."
        return {"bot_token": token, "chat_id": chat}, None

    if type_ == "email":
        host, security = _clean(form, "host"), _clean(form, "security") or "starttls"
        try:
            port = int(_clean(form, "port") or "587")
        except ValueError:
            return None, "Port must be a number."
        if not HOST_RE.match(host):
            return None, "Enter the mail server's name, for example smtp.example.com."
        if not 1 <= port <= 65535:
            return None, "Port must be between 1 and 65535."
        if security not in ("starttls", "ssl", "none"):
            return None, "Choose a security option."
        from_addr = _clean(form, "from_addr")
        to_addrs = [a.strip() for a in _clean(form, "to_addrs").split(",") if a.strip()]
        if not EMAIL_RE.match(from_addr):
            return None, "The From address isn't a valid email address."
        if not to_addrs or len(to_addrs) > 10 or not all(EMAIL_RE.match(a) for a in to_addrs):
            return None, "Enter 1-10 valid email addresses to send to, separated by commas."
        username, password = _clean(form, "username"), form.get("password") or ""
        if bool(username) != bool(password):
            return None, "Enter both a username and a password, or neither."
        return {
            "host": host, "port": port, "security": security,
            "username": username, "password": password,
            "from_addr": from_addr, "to_addrs": to_addrs,
        }, None

    if type_ == "webhook":
        url, secret = _clean(form, "url"), form.get("secret") or ""
        try:
            parts = urlsplit(url)
            _ = parts.port
        except ValueError:
            return None, "That address is not valid."
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname or len(url) > 2048:
            return None, "Address must start with http:// or https://"
        if len(secret) > 200:
            return None, "The signing secret is too long."
        return {"url": url, "secret": secret}, None

    return None, "Unknown channel type."


def summarize(type_, config) -> str:
    """One line for the UI. Never reveals secrets."""
    if type_ == "inapp":
        return "Shown on the Notifications page"
    if type_ == "webpush":
        return "All phones and browsers that enabled push"
    if not config:
        return ""
    if type_ == "telegram":
        return f"Chat {config.get('chat_id', '?')}"
    if type_ == "email":
        return f"{', '.join(config.get('to_addrs', []))} via {config.get('host', '?')}"
    if type_ == "webhook":
        signed = " (signed)" if config.get("secret") else ""
        return mask_url(config.get("url", "")) + signed
    return ""


# ---------------------------------------------------------------------------
# The channels
# ---------------------------------------------------------------------------

def _check(response):
    if not 200 <= response.status_code < 300:
        raise requests.exceptions.HTTPError(response=response)


class InAppChannel:
    def __init__(self, repo):
        self.repo = repo

    def send(self, notification):
        self.repo.add_inbox(notification)


class TelegramChannel:
    def __init__(self, config, post=requests.post):
        self.token = config["bot_token"]
        self.chat_id = config["chat_id"]
        self.post = post

    def _url(self, method):
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def send(self, notification):
        text = f"🚨 {notification.title}\n{notification.body}"
        snapshot = notification.snapshot_path

        if snapshot and Path(snapshot).is_file():
            with open(snapshot, "rb") as photo:
                response = self.post(
                    self._url("sendPhoto"),
                    data={"chat_id": self.chat_id, "caption": text[:1000]},
                    files={"photo": photo},
                    timeout=REQUEST_TIMEOUT,
                )
        else:
            response = self.post(
                self._url("sendMessage"),
                data={"chat_id": self.chat_id, "text": text},
                timeout=REQUEST_TIMEOUT,
            )
        _check(response)


class WebhookChannel:
    def __init__(self, config, post=requests.post):
        self.url = config["url"]
        self.secret = config.get("secret") or ""
        self.post = post

    def send(self, notification):
        body = json.dumps(
            {
                "title": notification.title,
                "message": notification.body,
                "event_type": notification.event_type,
                "camera": notification.camera_name,
                "camera_id": notification.camera_id,
                "time": notification.created_at,
            }
        ).encode("utf8")

        headers = {"Content-Type": "application/json", "User-Agent": "Sentinel"}
        if self.secret:
            digest = hmac.new(self.secret.encode("utf8"), body, hashlib.sha256).hexdigest()
            headers["X-Sentinel-Signature"] = f"sha256={digest}"

        response = self.post(
            self.url, data=body, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=False
        )
        _check(response)


def default_smtp_factory(security, host, port, context):
    if security == "ssl":
        return smtplib.SMTP_SSL(host, port, timeout=15, context=context)
    return smtplib.SMTP(host, port, timeout=15)


class EmailChannel:
    def __init__(self, config, smtp_factory=default_smtp_factory):
        self.config = config
        self.smtp_factory = smtp_factory

    def send(self, notification):
        cfg = self.config

        message = EmailMessage()
        message["Subject"] = f"[Sentinel] {notification.title}"
        message["From"] = cfg["from_addr"]
        message["To"] = ", ".join(cfg["to_addrs"])
        message.set_content(
            f"{notification.body}\n\nCamera: {notification.camera_name or '-'}\n"
            f"Time: {notification.created_at}"
        )

        snapshot = notification.snapshot_path
        if snapshot and Path(snapshot).is_file():
            message.add_attachment(
                Path(snapshot).read_bytes(), maintype="image", subtype="jpeg", filename="snapshot.jpg"
            )

        context = ssl.create_default_context()
        with self.smtp_factory(cfg["security"], cfg["host"], cfg["port"], context) as server:
            if cfg["security"] == "starttls":
                server.starttls(context=context)
            if cfg.get("username"):
                server.login(cfg["username"], cfg["password"])
            server.send_message(message)


class WebPushChannel:
    """Sends to every subscribed phone/browser. Dead subscriptions are removed."""

    def __init__(self, repo, push):
        self.repo = repo
        self.push = push  # object with: pem_path, contact, sender

    def send(self, notification):
        subscriptions = self.repo.list_push_subscriptions()
        if not subscriptions:
            raise UserFacingError(
                "No phone or browser has enabled push yet. Open the Alerts page on the device "
                "and press 'Enable push on this device'."
            )

        payload = json.dumps(
            {"title": notification.title, "body": notification.body, "url": "/notifications"}
        )

        delivered, last_error = 0, None
        for subscription in subscriptions:
            try:
                self.push.sender(subscription, payload, self.push.pem_path, self.push.contact)
                delivered += 1
            except PushSubscriptionGone:
                self.repo.delete_push_subscription(subscription["endpoint"])
            except Exception as error:
                last_error = error

        if delivered == 0 and last_error is not None:
            raise last_error


def build_channel(type_, config, repo=None, push=None):
    if type_ == "inapp":
        return InAppChannel(repo)
    if type_ == "telegram":
        return TelegramChannel(config)
    if type_ == "email":
        return EmailChannel(config)
    if type_ == "webhook":
        return WebhookChannel(config)
    if type_ == "webpush":
        return WebPushChannel(repo, push)
    raise UserFacingError("Unknown channel type.")
