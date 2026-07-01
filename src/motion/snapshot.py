import os
import cv2

from datetime import datetime


class SnapshotSaver:

    def __init__(self):

        os.makedirs(
            "snapshots",
            exist_ok=True,
        )

    def save(self, frame):

        filename = datetime.now().strftime(
            "%Y%m%d_%H%M%S.jpg"
        )

        path = os.path.join(
            "snapshots",
            filename,
        )

        cv2.imwrite(
            path,
            frame.data,
        )

        return path