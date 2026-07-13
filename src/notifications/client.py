from pathlib import Path

import requests

from notifications.settings import (
    API_URL,
    CHAT_ID,
    REQUEST_TIMEOUT,
)


class TelegramClient:

    def send_message(
        self,
        text: str,
    ) -> None:

        requests.post(
            f"{API_URL}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": text,
            },
            timeout=REQUEST_TIMEOUT,
        )

    def send_photo(
        self,
        image_path,
        caption="",
    ) -> None:

        image_path = Path(image_path)

        if not image_path.exists():

            return

        with image_path.open(
            "rb"
        ) as photo:

            requests.post(
                f"{API_URL}/sendPhoto",
                data={
                    "chat_id": CHAT_ID,
                    "caption": caption,
                },
                files={
                    "photo": photo,
                },
                timeout=REQUEST_TIMEOUT,
            )