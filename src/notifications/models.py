from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Notification:
    title: str
    body: str
    event_type: str = ""
    camera_id: object = None
    camera_name: str = ""
    snapshot_path: object = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="microseconds")
    )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Notification":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)
