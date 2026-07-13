from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field


@dataclass(slots=True)
class DashboardState:

    sentinel_running: bool = False

    camera_connected: bool = False

    telegram_connected: bool = False

    motion_detection: bool = True

    face_recognition: bool = True

    object_detection: bool = True

    camera_count: int = 0

    known_faces: int = 0

    unknown_faces: int = 0

    alerts_today: int = 0

    cpu_usage: float = 0.0

    ram_usage: float = 0.0

    fps: float = 0.0

    uptime: str = "00:00:00"

    version: str = "1.0.0"

    last_event: str = "System Ready"

    extra: dict = field(
        default_factory=dict,
    )

    def to_dict(self):

        return asdict(self)