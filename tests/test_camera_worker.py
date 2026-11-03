import time

import numpy as np

from src.camera.camera_exceptions import CameraCaptureError, CameraConnectionError
from src.camera.camera_interface import CameraInterface
from src.camera.frame import Frame
from src.camera.worker import ONLINE, STOPPED, CameraWorker


def wait_for(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class FlakySource(CameraInterface):
    """Fails to connect, or drops after a few frames, on demand."""

    def __init__(self, fail_connect=False, drop_after=None):
        self.fail_connect = fail_connect
        self.drop_after = drop_after
        self.reads = 0
        self.connected = False

    def connect(self):
        if self.fail_connect:
            raise CameraConnectionError("Unable to open the camera.")
        self.connected = True
        return True

    def disconnect(self):
        self.connected = False

    def is_connected(self):
        return self.connected

    def capture_frame(self):
        if self.drop_after is not None and self.reads >= self.drop_after:
            raise CameraCaptureError("Unable to read a frame.")
        self.reads += 1
        time.sleep(0.005)
        return Frame(source="fake", data=np.full((20, 30, 3), 7, dtype=np.uint8))


def make_worker(factory, **kwargs):
    options = dict(backoff_initial=0.01, backoff_max=0.05, read_failure_sleep=0.001)
    options.update(kwargs)
    return CameraWorker(1, "Test cam", factory, **options)


def test_worker_reconnects_after_failed_connects_and_a_dropped_stream():
    state = {"connects": 0}

    def factory():
        state["connects"] += 1
        n = state["connects"]
        # connects 1 and 2 fail; connect 3 streams 3 frames then drops; connect 4+ is healthy
        return FlakySource(fail_connect=n <= 2, drop_after=3 if n == 3 else None)

    worker = make_worker(factory)
    worker.start()

    assert wait_for(lambda: state["connects"] >= 4 and worker.status()["state"] == ONLINE)
    assert wait_for(lambda: worker.status()["frames"] > 10)

    worker.stop()
    assert worker.status()["state"] == STOPPED
    assert not worker.is_alive()


def test_worker_keeps_only_the_newest_frame():
    worker = make_worker(lambda: FlakySource())
    worker.start()

    assert wait_for(lambda: worker.latest()[0] is not None)
    _, seq1 = worker.latest()
    assert wait_for(lambda: worker.latest()[1] > seq1)

    worker.stop()


def test_worker_status_reports_error_without_leaking_details():
    worker = make_worker(lambda: FlakySource(fail_connect=True))
    worker.start()

    assert wait_for(lambda: worker.status()["error"] is not None)
    status = worker.status()
    assert status["state"] != ONLINE
    assert "rtsp" not in str(status)

    worker.stop()


def test_latest_jpeg_is_encoded_once_per_frame():
    worker = make_worker(lambda: FlakySource(drop_after=1), max_read_failures=1000)
    worker.start()

    assert wait_for(lambda: worker.latest()[0] is not None)
    time.sleep(0.05)

    first, seq1 = worker.latest_jpeg()
    second, seq2 = worker.latest_jpeg()

    assert first[:2] == b"\xff\xd8"
    assert seq1 == seq2
    assert first is second  # same cached bytes, not re-encoded

    worker.stop()
