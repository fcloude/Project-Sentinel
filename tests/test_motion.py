import numpy as np

from src.camera.file_camera import FileCamera
from src.camera.frame import Frame
from src.motion.detector import MotionDetector


def test_file_camera_returns_frames(sample_video):
    camera = FileCamera(sample_video)
    camera.connect()

    frame = camera.capture_frame()

    assert frame.data is not None
    assert frame.data.shape == (240, 320, 3)
    camera.disconnect()


def test_file_camera_loops_past_end_of_video(sample_video):
    camera = FileCamera(sample_video)
    camera.connect()

    for _ in range(80):  # video has only 30 frames
        camera.capture_frame()

    camera.disconnect()


def test_motion_is_detected_in_video(sample_video):
    camera = FileCamera(sample_video)
    camera.connect()
    detector = MotionDetector()

    results = [detector.detect(camera.capture_frame()) for _ in range(20)]
    camera.disconnect()

    assert any(r.detected for r in results)


def test_still_scene_has_no_motion():
    detector = MotionDetector()
    still = Frame(source="test", data=np.zeros((240, 320, 3), dtype=np.uint8))

    results = [detector.detect(still) for _ in range(5)]

    assert not any(r.detected for r in results)
