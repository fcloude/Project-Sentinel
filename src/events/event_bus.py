import logging
from collections import defaultdict

from src.events.event import Event

logger = logging.getLogger(__name__)


class EventBus:
    """Subscribers are isolated: one failing subscriber can never stop detection or the other subscribers."""

    def __init__(self):
        self._subscribers = defaultdict(list)

    def subscribe(self, event_type, callback):
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type, callback):
        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)

    def clear(self):
        self._subscribers.clear()

    def publish(self, event: Event):
        callbacks = [*self._subscribers.get(event.event_type, ()), *self._subscribers.get("*", ())]
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                logger.exception("Subscriber %r failed on %s", callback, event.event_type)
