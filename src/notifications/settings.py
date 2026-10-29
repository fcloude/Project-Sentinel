import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
REQUEST_TIMEOUT = 10
COOLDOWN_SECONDS = 30