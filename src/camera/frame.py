from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

import numpy as np


@dataclass(slots=True)
class Frame:
    frame_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)

    source: str = ""

    data: np.ndarray | None = None