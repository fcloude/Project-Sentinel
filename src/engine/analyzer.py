import threading

from src.app_logging import get_logger
from src.engine.cooldown import Cooldown
from src.events import event_types
from src.motion.detector import MotionDetector

logger = get_logger(__name__)


class CameraAnalyzer:
    """Looks at the newest frame of ONE camera a few times per second.

    motion -> faces (a face means a person is here). Each kind of alert has a cooldown, so
    a person standing still doesn't create an event every frame.
    """

    def __init__(
        self,
        camera,
        worker,
        publish,
        get_models,
        inference_lock,
        snapshot_saver,
        fps,
    ):
        self.camera = camera
        self.worker = worker
        self.publish = publish
        self.get_models = get_models
        self.inference_lock = inference_lock
        self.snapshot_saver = snapshot_saver
        self.interval = 1.0 / max(fps, 0.2)

        self.motion = MotionDetector()  # one per camera: it remembers the previous frame
        self.motion_gate = Cooldown(10)
        self.person_gate = Cooldown(30)
        self.snapshot_gate = Cooldown(5)
        self.error_gate = Cooldown(30)

        self._thread = threading.Thread(
            target=self._run, name=f"analyzer-{camera['id']}", daemon=True
        )
        self._stop_event = threading.Event()

    def start(self):
        self._thread.start()

    def stop(self, timeout=5.0):
        self._stop_event.set()
        if self._thread.ident is not None:
            self._thread.join(timeout)

    def _run(self):
        last_seq = -1

        while not self._stop_event.wait(self.interval):
            frame, seq = self.worker.latest()
            if frame is None or seq == last_seq:
                continue
            last_seq = seq

            try:
                self._process(frame)
            except Exception:
                # One bad frame must never stop the camera's analysis.
                if self.error_gate.allowed("error"):
                    logger.exception("Analysis error on camera '%s'", self.camera["name"])

    def _process(self, frame):
        motion = self.motion.detect(frame)
        if not motion.detected:
            return

        pending = []
        unknown_to_record = []

        if self.motion_gate.allowed("motion"):
            pending.append(
                (
                    event_types.MOTION_DETECTED,
                    f"{motion.contour_count} motion region(s) detected.",
                    {"contour_count": motion.contour_count},
                )
            )

        faces = self.get_models()

        # Heavy AI runs one camera at a time so several cameras can't fight over the CPU.
        with self.inference_lock:
            results = faces.process(frame)

        if results and self.person_gate.allowed("person"):
            pending.append(
                (
                    event_types.PERSON_DETECTED,
                    f"{len(results)} person(s) detected.",
                    {"count": len(results)},
                )
            )

        for result in results:
            if result.recognized:
                if self.person_gate.allowed(("known", result.name)):
                    pending.append(
                        (
                            event_types.FACE_RECOGNIZED,
                            f"{result.name} recognized.",
                            {"name": result.name},
                        )
                    )
            elif self.person_gate.allowed("unknown"):
                pending.append((event_types.UNKNOWN_PERSON, "Unknown person detected.", {}))
                unknown_to_record.append(result)

        if not pending:
            return

        snapshot = None
        if self.snapshot_saver and self.snapshot_gate.allowed("snapshot"):
            snapshot = self.snapshot_saver.save(frame, self.camera["id"])

        record = getattr(faces, "record_unknown", None)
        if record:
            for result in unknown_to_record:
                record(self.camera["id"], result, frame)

        for event_type, message, metadata in pending:
            if snapshot:
                metadata = {**metadata, "snapshot": snapshot}
            self.publish(
                event_type,
                self.camera["name"],
                message,
                camera_id=self.camera["id"],
                **metadata,
            )
