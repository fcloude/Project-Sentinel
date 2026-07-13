from datetime import datetime

from events.event import Event


class NotificationFormatter:

    @staticmethod
    def format(event: Event) -> str:

        timestamp = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        return (
            "🚨 SENTINEL ALERT\n\n"
            f"Time : {timestamp}\n\n"
            f"Event : {event.event_type}\n"
            f"Source : {event.source}\n\n"
            f"{event.message}"
        )