from src.events.event import Event

from src.notifications.client import (
    TelegramClient,
)

from src.notifications.cooldown import (
    CooldownManager,
)

from src.notifications.formatter import (
    NotificationFormatter,
)

from src.notifications.settings import (
    COOLDOWN_SECONDS,
)


class NotificationManager:

    def __init__(self):

        self.client = TelegramClient()

        self.cooldown = CooldownManager(
            COOLDOWN_SECONDS,
        )

    def notify(
        self,
        event: Event,
    ):

        if not self.cooldown.allowed(
            event.event_type,
        ):

            return

        message = NotificationFormatter.format(
            event,
        )

        self.client.send_message(
            message,
        )

    def notify_photo(
        self,
        event: Event,
        image_path,
    ):

        if not self.cooldown.allowed(
            event.event_type,
        ):

            return

        message = NotificationFormatter.format(
            event,
        )

        self.client.send_photo(
            image_path,
            message,
        )