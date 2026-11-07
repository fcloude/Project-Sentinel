import logging
from pathlib import Path

import requests

from src.notifications import settings

logger = logging.getLogger(__name__)


class TelegramClient:
    """Never raises and never logs the bot token.

    requests' exception messages contain the full URL (which contains the token), so we log only the
    exception CLASS NAME. Redirects are not followed."""

    def __init__(self, token: str | None = None, chat_id: int | None = None, timeout: float | None = None):
        self._token = settings.BOT_TOKEN if token is None else token
        self._chat_id = settings.CHAT_ID if chat_id is None else chat_id
        self._timeout = settings.REQUEST_TIMEOUT if timeout is None else timeout
        self._warned = False

    def __repr__(self) -> str:
        return f"TelegramClient(enabled={self.enabled})"

    @property
    def enabled(self) -> bool:
        return bool(self._token) and self._chat_id != 0

    def _post(self, method: str, **kwargs) -> bool:
        if not self.enabled:
            if not self._warned:
                logger.warning("Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID); alerts disabled.")
                self._warned = True
            return False
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        try:
            response = requests.post(url, timeout=(5, self._timeout), allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            logger.warning("Telegram %s failed: %s", method, type(exc).__name__)
            return False
        if response.status_code != 200:
            logger.warning("Telegram %s returned HTTP %s", method, response.status_code)
            return False
        return True

    def send_message(self, text: str) -> bool:
        return self._post("sendMessage", data={"chat_id": self._chat_id, "text": text[:4000]})

    def send_photo(self, image_path, caption: str = "") -> bool:
        path = Path(image_path)
        if not path.is_file():
            return False
        with path.open("rb") as photo:
            return self._post("sendPhoto", data={"chat_id": self._chat_id, "caption": caption[:1000]},
                              files={"photo": photo})
