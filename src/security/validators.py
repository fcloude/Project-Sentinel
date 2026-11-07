"""Input validation: person names, camera sources, image uploads, snapshot filenames."""
from __future__ import annotations

import re
import unicodedata
from ipaddress import IPv6Address, ip_address
from pathlib import Path
from urllib.parse import urlparse


class ValidationError(ValueError):
    """Input rejected. The message is safe to show to the user."""


# ---------------------------------------------------------------- person names
_NAME_RE = re.compile(r"^[^\W_][\w .'\-]{0,63}$", re.UNICODE)


def validate_person_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValidationError("Name must be text.")
    name = unicodedata.normalize("NFC", name).strip()
    if not _NAME_RE.fullmatch(name):
        raise ValidationError("Name must be 1-64 characters: letters, digits, spaces, . ' -")
    return name


# ---------------------------------------------------------------- camera sources
_ALLOWED_SCHEMES = {"rtsp", "rtsps", "http", "https"}
_FORBIDDEN_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")
_NUMERICISH_HOST = re.compile(r"(0x[0-9a-f]+|[0-9]+)(\.(0x[0-9a-f]+|[0-9]+))*", re.IGNORECASE)
_BLOCKED_HOSTNAMES = {"metadata.google.internal", "metadata", "instance-data"}


def validate_camera_source(value: str) -> str | int:
    """Return an int (USB index) or a vetted URL. Rejects file://, javascript:, shell-ish input, metadata IPs.

    Limits: this cannot defeat DNS rebinding; the route that calls it must also be admin-only."""
    if not isinstance(value, str):
        raise ValidationError("Camera source must be text.")
    value = value.strip()
    if not value or len(value) > 2048:
        raise ValidationError("Camera source is empty or too long.")
    if re.fullmatch(r"[0-9]{1,2}", value):
        return int(value)
    if _FORBIDDEN_CHARS.search(value):
        raise ValidationError("Camera URL contains forbidden characters.")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValidationError("Camera URL must start with rtsp://, rtsps://, http:// or https://")
    host = parsed.hostname
    if not host:
        raise ValidationError("Camera URL has no host.")
    try:
        parsed.port  # raises ValueError for invalid ports
    except ValueError as exc:
        raise ValidationError("Camera URL has an invalid port.") from exc
    host = host.lower()
    if host in _BLOCKED_HOSTNAMES:
        raise ValidationError("That host is not allowed.")
    if _NUMERICISH_HOST.fullmatch(host):
        try:  # only strict dotted-quad IPv4 is accepted; 2852039166 / 0xA9FEA9FE / 0251.0376... are refused
            ip = ip_address(host)
        except ValueError as exc:
            raise ValidationError("Ambiguous numeric host; use a normal IP address or hostname.") from exc
    else:
        try:
            ip = ip_address(host)
        except ValueError:
            return value  # a hostname
    if isinstance(ip, IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        raise ValidationError("That address is not allowed.")
    return value


def mask_url(url: str) -> str:
    return re.sub(r"(://)([^/\s:@]+):([^\s/]+)@", r"\1\2:***@", url)


# ---------------------------------------------------------------- image uploads
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seglen = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in _SOF:
            if i + 9 > n:
                return None
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        if seglen < 2:
            return None
        i += 2 + seglen
    return None


def validate_image_upload(data: bytes, *, max_bytes: int, max_width: int = 4096, max_height: int = 4096) -> str:
    """Check size, magic bytes and *declared* dimensions BEFORE decoding (decompression-bomb guard).
    Returns 'jpeg' or 'png'. Never trusts the client-supplied filename or Content-Type."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValidationError("Empty upload.")
    if len(data) > max_bytes:
        raise ValidationError("File is too large.")
    if data[:3] == b"\xff\xd8\xff":
        kind, dims = "jpeg", _jpeg_dimensions(bytes(data))
    elif data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and len(data) >= 24:
        kind, dims = "png", (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
    else:
        raise ValidationError("Only JPEG and PNG images are accepted.")
    if not dims or dims[0] < 1 or dims[1] < 1:
        raise ValidationError("Image dimensions could not be read.")
    if dims[0] > max_width or dims[1] > max_height:
        raise ValidationError("Image dimensions are too large.")
    return kind


# ---------------------------------------------------------------- file serving
_SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.jpg$")


def is_safe_snapshot_name(name: str) -> bool:
    return bool(_SNAPSHOT_RE.fullmatch(name)) and ".." not in name


def safe_join(base: str | Path, name: str) -> Path | None:
    """Resolve base/name and return it only if it stays inside base (path-traversal guard)."""
    base_p = Path(base).resolve()
    target = (base_p / name).resolve()
    return target if target.is_relative_to(base_p) else None
