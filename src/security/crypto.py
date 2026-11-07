import base64
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
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
    """Encrypts short secrets (camera URLs, channel passwords) for storage.

    Supports key rotation: if multiple keys are provided (as a tuple or list),
    the decrypt method will try each key until one succeeds.
    """

    def __init__(self, secret: str | tuple[str, ...] | list):
        # secret can be a string, tuple, or list (from config or test)
        if isinstance(secret, (tuple, list)):
            self._keys = list(secret)  # Store all keys for rotation
        else:
            self._keys = [secret]  # Single key

    @classmethod
    def generate_key(cls) -> str:
        """Generate a new SecretBox key from a secret string."""
        return secrets.token_urlsafe(48)

    def _get_fernet(self, key: str) -> Fernet:
        """Create a Fernet instance from a key string."""
        raw = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"sentinel-secretbox-v1",
        ).derive(key.encode("utf8"))
        return Fernet(base64.urlsafe_b64encode(raw))

    def encrypt(self, text: str) -> str:
        """Encrypt text using the first key."""
        fernet = self._get_fernet(self._keys[0])
        return fernet.encrypt(text.encode("utf8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        """Decrypt token, trying each key in order (key rotation support).

        Tries each stored key until decryption succeeds. Raises
        SecretDecryptionError if no key can decrypt the token.
        """
        for key in self._keys:
            try:
                fernet = self._get_fernet(key)
                return fernet.decrypt(token.encode("ascii")).decode("utf8")
            except InvalidToken:
                continue
        raise SecretDecryptionError("Failed to decrypt camera source")

    def rotate(self, token: str) -> str:
        """Rotate the encryption key for a given token.

        Decrypts the token with any available key to get the plaintext,
        then re-encrypts it with the FIRST key in the key list (the new
        rotation key), returning a new token that can be decrypted with
        that key alone.

        Returns the original token unchanged if there's only one key.
        """
        if len(self._keys) <= 1:
            return token

        # First, decrypt the token with any available key to get the plaintext
        plaintext = None
        for key in self._keys:
            try:
                fernet = self._get_fernet(key)
                plaintext = fernet.decrypt(token.encode("ascii")).decode("utf8")
                break
            except InvalidToken:
                continue

        if plaintext is None:
            # Couldn't decrypt - return original
            return token

        # Re-encrypt with the FIRST key in the list (the new rotation key)
        fernet = self._get_fernet(self._keys[0])
        return fernet.encrypt(plaintext.encode("utf8")).decode("ascii")