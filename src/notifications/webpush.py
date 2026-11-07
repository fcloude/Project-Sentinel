"""Phone / browser push (Web Push with VAPID).

UNTESTED against real browsers and push services: only the logic around it is
covered by tests. The actual send uses the optional `pywebpush` package:

    python -m pip install pywebpush

Push needs HTTPS (http://localhost is the one exception). See docs/PHONE_ALERTS.md.
"""

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from src.errors import UserFacingError

DEFAULT_CONTACT = "mailto:admin@example.com"  # set your real address on the Alerts page


class PushSubscriptionGone(Exception):
    """The browser unsubscribed or the subscription expired (HTTP 404/410)."""


def generate_vapid_private_pem() -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def public_key_from_pem(pem: bytes) -> str:
    """The 'applicationServerKey' browsers need: 65-byte uncompressed point, base64url."""
    key = serialization.load_pem_private_key(pem, password=None)
    raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def ensure_vapid_keys(data_dir):
    """Creates the push key pair once. Returns (path of the private key file, public key)."""
    folder = Path(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    pem_path = folder / "vapid_private.pem"

    if not pem_path.exists():
        pem_path.write_bytes(generate_vapid_private_pem())
        try:
            os.chmod(pem_path, 0o600)
        except OSError:
            pass

    return pem_path, public_key_from_pem(pem_path.read_bytes())


def pywebpush_sender(subscription, payload, pem_path, contact):
    """Sends one push message. Raises PushSubscriptionGone if the subscription is dead."""
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        raise UserFacingError(
            "Phone push needs an extra package. Run: python -m pip install pywebpush"
        ) from None

    info = {
        "endpoint": subscription["endpoint"],
        "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
    }
    claims = {"sub": contact}

    try:
        try:
            webpush(info, payload, vapid_private_key=str(pem_path), vapid_claims=claims, timeout=10)
        except TypeError:  # an older pywebpush without the timeout argument
            webpush(info, payload, vapid_private_key=str(pem_path), vapid_claims=claims)
    except WebPushException as error:
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status in (404, 410):
            raise PushSubscriptionGone() from None
        raise UserFacingError(
            f"The push service rejected the message (HTTP {status})." if status
            else "The push service could not be reached."
        ) from None
