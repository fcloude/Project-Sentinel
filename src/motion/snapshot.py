from datetime import datetime
from pathlib import Path

import cv2


class SnapshotSaver:
    """Saves JPEG snapshots as <data folder>/snapshots/<camera id>/<timestamp>.jpg.

    The data folder is git-ignored. Never serve these files without a login check.
    """

    def __init__(self, base_dir=None):
        if base_dir is None:
            from src.database import manager

            base_dir = Path(manager.settings.database_path).parent / "snapshots"
        self.base = Path(base_dir)

    def save(self, frame, camera_id):
        folder = self.base / str(camera_id)
        folder.mkdir(parents=True, exist_ok=True)

        path = folder / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg")

        if not cv2.imwrite(str(path), frame.data):
            return None
        return str(path)
