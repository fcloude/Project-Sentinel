from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = ("rtsp", "rtsps", "http", "https")
KINDS = ("usb", "url", "file")


def mask_url(url: str) -> str:
    """Hides passwords (and query strings) so URLs are safe to show or log."""
    try:
        parts = urlsplit(url)
        if parts.username is None and parts.password is None and not parts.query:
            return url

        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host += f":{parts.port}"

        user = parts.username or ""
        if parts.password is not None:
            netloc = f"{user}:***@{host}"
        elif user:
            netloc = f"{user}@{host}"
        else:
            netloc = host

        query = "***" if parts.query else ""
        return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))
    except ValueError:
        return "<invalid address>"


def validate_source(kind: str, source: str, allow_file: bool = False):
    """Returns (clean_source, None) or (None, friendly_error)."""
    source = (source or "").strip()

    if kind == "usb":
        if not source.isdigit() or int(source) > 9:
            return None, "USB camera number must be a single digit from 0 to 9."
        return str(int(source)), None

    if kind == "url":
        if len(source) > 2048:
            return None, "That address is too long."
        try:
            parts = urlsplit(source)
            _ = parts.port  # raises ValueError on a bad port
        except ValueError:
            return None, "That address is not valid."
        if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.hostname:
            return None, (
                "Address must start with rtsp://, rtsps://, http:// or https://, "
                "for example rtsp://192.168.1.20:554/stream1"
            )
        return source, None

    if kind == "file":
        if not allow_file:
            return None, "Video-file cameras are disabled."
        path = Path(source)
        if not path.is_file():
            return None, "That video file does not exist."
        return str(path), None

    return None, "Unknown camera type."


def capture_source(kind: str, source: str):
    """What to hand to OpenCV: an int for USB, a string otherwise."""
    return int(source) if kind == "usb" else source
