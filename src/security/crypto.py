import base64
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class SecretDecryptionError(Exception):
    """Raised when secret decryption fails."""


def get_secret_key(database_path: str) -> str:
    """SECRET_KEY from the environment, else a random key stored next to the database.

    The file lives in data/ (git-ignored). If you lose it, saved camera
    passwords cannot be decrypted, so include it in backups.
    """
    from_env = os.getenv("SECRET_KEY", "").strip()
    if from_env:
        return from_env

    key_file = Path(database_path).parent / "secret.key"
    if key_file.exists():
        return key_file.read_text(encoding="utf8").strip()

    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    key_file.write_text(key, encoding="utf8")
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key


def get_encryption_keys() -> dict:
    """Return encryption keys for camera credentials.

    Returns a dict with the Fernet key used to encrypt/decrypt camera passwords.
    """
    from src.security.config import SecurityConfig
    config = SecurityConfig.from_env({
        "SECRET_KEY": os.getenv("SECRET_KEY", ""),
        "SENTINEL_ENCRYPTION_KEYS": os.getenv("SENTINEL_ENCRYPTION_KEYS", ""),
    })
    # In a full implementation, this would derive keys from the config
    # For now, return the secret key as the Fernet key
    fernet_key = config.secret_key
    if isinstance(fernet_key, tuple):
        fernet_key = fernet_key[0]  # Take first element if tuple
    return {"fernet_key": fernet_key}


class SecretBox:
    """Encrypts short secrets (camera URLs, channel passwords) for storage."""

    def __init__(self, secret: str | tuple[str, ...]):
        # secret can be a string or a tuple (from config encryption_keys)
        if isinstance(secret, tuple):
            secret = secret[0]  # Take first element if tuple
        raw = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"sentinel-secretbox-v1",
        ).derive(secret.encode("utf8"))
        self._fernet = Fernet(base64.urlsafe_b64encode(raw))

    def encrypt(self, text: str) -> str:
        return self._fernet.encrypt(text.encode("utf8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("ascii")).decode("utf8")
