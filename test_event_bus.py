from src.events.event import Event
from src.events.event_bus import EventBus


def make_event(event_type="X"):
    return Event(event_type=event_type, source="test", message="hello")


def test_failing_subscriber_does_not_stop_others():
    bus = EventBus()
    received = []

    def bad(event):
        raise RuntimeError("boom")

    def good(event):
        received.append(event.event_type)

    bus.subscribe("X", bad)
    bus.subscribe("X", good)

    bus.publish(make_event("X"))  # must not raise

    assert received == ["X"]


def test_wildcard_subscriber_receives_every_event():
    bus = EventBus()
    received = []
    bus.subscribe("*", lambda e: received.append(e.event_type))

    bus.publish(make_event("A"))
    bus.publish(make_event("B"))

    assert received == ["A", "B"]
