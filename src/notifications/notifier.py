from events.event import Event

from notifications.client import (
    TelegramClient,
)

from notifications.cooldown import (
    CooldownManager,
)

from notifications.formatter import (
    NotificationFormatter,
)

from notifications.settings import (
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