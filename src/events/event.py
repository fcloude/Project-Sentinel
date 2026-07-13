from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass(slots=True)
class Event:

    event_type: str

    source: str

    message: str

    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat(
            timespec="seconds"
        )
    )

    event_id: str = field(
        default_factory=lambda: str(
            uuid4()
        )
    )

    metadata: dict = field(
        default_factory=dict
    )