#!/usr/bin/env python3
"""Print fresh secrets to paste into .env. Prints only; writes nothing to disk, logs nothing."""
import secrets

from cryptography.fernet import Fernet

print("# Paste these into your .env (never commit .env):")
print(f"SECRET_KEY={secrets.token_urlsafe(48)}")  # sentinel-ok
print(f"SENTINEL_ENCRYPTION_KEYS={Fernet.generate_key().decode()}")
print("# Rotation: put the NEW key first, keep the old one after a comma until all data is re-encrypted.")
