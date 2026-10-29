from collections import defaultdict

from src.app_logging import get_logger
from src.events.event import Event

logger = get_logger(__name__)


class EventBus:

    def __init__(self):
        self._subscribers = defaultdict(list)

    def subscribe(self, event_type, callback):
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type, callback):
        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)

    def publish(self, event: Event):
        callbacks = [
            *self._subscribers.get(event.event_type, []),
            *self._subscribers.get("*", []),
        ]

        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                logger.exception(
                    "Subscriber %r failed on %s", callback, event.event_type
                )