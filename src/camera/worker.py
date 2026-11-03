import threading
import time

import cv2

from src.app_logging import get_logger
from src.camera.camera_exceptions import CameraCaptureError, CameraError

logger = get_logger(__name__)

CONNECTING = "connecting"
ONLINE = "online"
RECONNECTING = "reconnecting"
STOPPED = "stopped"


class CameraWorker:
    """Owns ONE camera: reads frames nonstop, keeps only the newest, reconnects forever.

    Reading continuously matters: network cameras buffer video, so a slow
    reader falls further and further behind real time.

    Error text never includes the camera address (it can contain a password).
    """

    def __init__(
        self,
        camera_id,
        name,
        source_factory,
        *,
        backoff_initial=1.0,
        backoff_max=30.0,
        max_read_failures=5,
        read_failure_sleep=0.05,
        pace_fps=None,
    ):
        self.camera_id = camera_id
        self.camera_name = name
        self.source_factory = source_factory
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max
        self.max_read_failures = max_read_failures
        self.read_failure_sleep = read_failure_sleep
        self.pace_fps = pace_fps  # only for video files, which would otherwise play at full speed

        self._thread = threading.Thread(
            target=self._run, name=f"camera-{camera_id}", daemon=True
        )
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._frame = None
        self._seq = 0
        self._jpeg = None
        self._jpeg_seq = -1
        self._frames = 0
        self._last_frame_time = None
        self._cam_state = CONNECTING
        self._last_error = None

    # ---- lifecycle ----------------------------------------------------

    def start(self):
        self._thread.start()

    def stop(self, timeout=5.0):
        self._stop_event.set()
        if self._thread.ident is not None:
            self._thread.join(timeout)

    @property
    def stopped(self):
        return self._stop_event.is_set()

    def is_alive(self):
        return self._thread.is_alive()

    # ---- what other threads can read -----------------------------------

    def latest(self):
        """(newest frame or None, sequence number)."""
        with self._lock:
            return self._frame, self._seq

    def latest_jpeg(self, max_width=640, quality=70):
        """(JPEG bytes or None, sequence number). Encoded once per frame, shared by viewers."""
        with self._lock:
            frame, seq = self._frame, self._seq
            if frame is None:
                return None, seq
            if self._jpeg_seq == seq:
                return self._jpeg, seq

        image = frame.data
        height, width = image.shape[:2]
        if width > max_width:
            image = cv2.resize(image, (max_width, int(height * max_width / width)))

        ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            return None, seq

        jpeg = buffer.tobytes()
        with self._lock:
            self._jpeg, self._jpeg_seq = jpeg, seq
        return jpeg, seq

    def status(self):
        with self._lock:
            age = None
            if self._last_frame_time is not None:
                age = round(time.monotonic() - self._last_frame_time, 1)
            return {
                "id": self.camera_id,
                "name": self.camera_name,
                "state": self._cam_state,
                "error": self._last_error,
                "frames": self._frames,
                "frame_age": age,
            }

    # ---- the thread -----------------------------------------------------

    def _set_state(self, state, error=None):
        with self._lock:
            self._cam_state = state
            self._last_error = error

    def _publish(self, frame):
        with self._lock:
            self._frame = frame
            self._seq += 1
            self._frames += 1
            self._last_frame_time = time.monotonic()

    def _run(self):
        delay = self.backoff_initial
        first = True

        try:
            while not self._stop_event.is_set():
                self._set_state(CONNECTING if first else RECONNECTING, self._last_error)
                first = False
                source = None

                try:
                    source = self.source_factory()
                    source.connect()
                    self._set_state(ONLINE)
                    delay = self.backoff_initial
                    self._read_loop(source)
                except CameraError as error:
                    self._set_state(RECONNECTING, str(error))
                except Exception as error:
                    logger.error(
                        "Camera '%s': unexpected %s", self.camera_name, type(error).__name__
                    )
                    self._set_state(
                        RECONNECTING, f"Unexpected error ({type(error).__name__})"
                    )
                finally:
                    if source is not None:
                        try:
                            source.disconnect()
                        except Exception:
                            pass

                if self._stop_event.wait(delay):
                    break
                delay = min(delay * 2, self.backoff_max)
        finally:
            self._set_state(STOPPED)

    def _read_loop(self, source):
        failures = 0
        interval = 1.0 / self.pace_fps if self.pace_fps else 0

        while not self._stop_event.is_set():
            started = time.monotonic()

            try:
                frame = source.capture_frame()
            except CameraCaptureError:
                failures += 1
                if failures >= self.max_read_failures:
                    raise
                self._stop_event.wait(self.read_failure_sleep)
                continue

            failures = 0
            self._publish(frame)

            if interval:
                remaining = interval - (time.monotonic() - started)
                if remaining > 0:
                    self._stop_event.wait(remaining)
