from collections import defaultdict

from events.event import Event


class EventBus:

    def __init__(self):

        self._subscribers = defaultdict(list)

    def subscribe(
        self,
        event_type,
        callback,
    ):

        if callback not in self._subscribers[event_type]:

            self._subscribers[event_type].append(
                callback
            )

    def unsubscribe(
        self,
        event_type,
        callback,
    ):

        if callback in self._subscribers[event_type]:

            self._subscribers[event_type].remove(
                callback
            )

    def publish(
        self,
        event: Event,
    ):

        for callback in self._subscribers.get(
            event.event_type,
            [],
        ):

            callback(
                event,
            )

        for callback in self._subscribers.get(
            "*",
            [],
        ):

            callback(
                event,
            )