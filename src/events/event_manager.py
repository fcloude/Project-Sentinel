from events.event import Event
from events.event_bus import EventBus


class EventManager:

    def __init__(self):

        self.bus = EventBus()

    def subscribe(
        self,
        event_type,
        callback,
    ):

        self.bus.subscribe(
            event_type,
            callback,
        )

    def publish(
        self,
        event_type,
        source,
        message,
        **metadata,
    ):

        event = Event(
            event_type=event_type,
            source=source,
            message=message,
            metadata=metadata,
        )

        self.bus.publish(
            event,
        )

        return event