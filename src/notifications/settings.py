"""Notification settings. Secrets come ONLY from the environment (.env), never from source code.

Importing this module never raises, so tests and the dashboard work without Telegram configured;
the client simply stays disabled until both values are set."""
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

try:
    CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0").strip() or "0")
except ValueError:
    CHAT_ID = 0

REQUEST_TIMEOUT = 10
COOLDOWN_SECONDS = 30


def telegram_enabled() -> bool:
    return bool(BOT_TOKEN) and CHAT_ID != 0
