from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.app_logging import get_logger
from src.events.event import Event
from src.events.event_bus import EventBus

logger = get_logger(__name__)


class EventManager:
    """
    Central event service for Project Sentinel.

    Responsibilities:
        • Subscribe callbacks to events
        • Publish events
        • Act as the single interface to EventBus
    """

    def __init__(self) -> None:
        self.bus = EventBus()

    # --------------------------------------------------
    # Subscription
    # --------------------------------------------------

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[Event], None],
    ) -> None:
        """
        Register a callback for an event type.
        """

        logger.debug("Subscribing '%s' to '%s'",
                     callback.__name__,
                     event_type)

        self.bus.subscribe(
            event_type,
            callback,
        )

    # --------------------------------------------------
    # Publishing
    # --------------------------------------------------

    def publish(
        self,
        event_type: str,
        source: str,
        message: str,
        **metadata: Any,
    ) -> Event:
        """
        Create and publish an event.

        Returns
        -------
        Event
            The created event instance.
        """

        event = Event(
            event_type=event_type,
            source=source,
            message=message,
            metadata=metadata,
        )

        logger.debug(
            "Publishing event '%s' from '%s'",
            event_type,
            source,
        )

        self.bus.publish(event)

        return event

    # --------------------------------------------------
    # Utility
    # --------------------------------------------------

    def unsubscribe(
        self,
        event_type: str,
        callback: Callable[[Event], None],
    ) -> None:
        """
        Remove a callback from an event type.
        """

        if hasattr(self.bus, "unsubscribe"):
            self.bus.unsubscribe(
                event_type,
                callback,
            )

    def clear(self) -> None:
        """
        Remove every registered listener.
        """

        if hasattr(self.bus, "clear"):
            self.bus.clear()