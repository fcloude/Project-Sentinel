from collections import defaultdict
from typing import Callable

from events.event import Event


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable[[Event], None]) -> None:
        self._subscribers[event_type].append(callback)

    def publish(self, event: Event) -> None:
        for callback in self._subscribers[event.event_type]:
            callback(event)