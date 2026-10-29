import cv2
import numpy as np
import pytest


@pytest.fixture
def sample_video(tmp_path):
    """Makes a tiny video: a white square moving across a dark background."""
    path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 15, (320, 240)
    )

    for i in range(30):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        x = 10 + i * 8
        frame[90:150, x : x + 60] = 255
        writer.write(frame)

    writer.release()
    return str(path)
