import threading
import time

import cv2

from src.app_logging import get_logger
from src.ai.detector import ObjectDetector
from src.camera.camera_manager import CameraManager
from src.camera.usb_camera import USBCamera
from src.events import event_types
from src.events.event_manager import EventManager
from src.face.face_manager import FaceManager
from src.motion.detector import MotionDetector
from src.motion.snapshot import SnapshotSaver
from src.notifications.notifier import NotificationManager

logger = get_logger(__name__)


class SentinelEngine:
    def __init__(self):
        self.running = False
        self.thread = None

        # Core Components
        self.camera = CameraManager(USBCamera())
        self.events = EventManager()
        self.motion_detector = MotionDetector()
        self.snapshot_saver = SnapshotSaver()
        self.object_detector = ObjectDetector()
        self.face_manager = FaceManager()
        self.notification_manager = NotificationManager()

        # Register Event Listeners
        self._register_event_handlers()

    # --------------------------------------------------
    # Event Registration
    # --------------------------------------------------

    def _register_event_handlers(self):
        callback = self.notification_manager.notify

        self.events.subscribe(
            event_types.MOTION_DETECTED,
            callback,
        )

        self.events.subscribe(
            event_types.PERSON_DETECTED,
            callback,
        )

        self.events.subscribe(
            event_types.OBJECT_DETECTED,
            callback,
        )

        self.events.subscribe(
            event_types.FACE_RECOGNIZED,
            callback,
        )

        self.events.subscribe(
            event_types.UNKNOWN_PERSON,
            callback,
        )

    # --------------------------------------------------
    # Engine Controls
    # --------------------------------------------------

    def start(self):
        if self.running:
      
            logger.info("Sentinel Engine already running.")
            return

        logger.info("Starting Sentinel Engine...")

        self.running = True

        self.thread = threading.Thread(
            target=self.run,
            daemon=True,
            name="SentinelEngine",
        )

        self.thread.start()

    def stop(self):
        if not self.running:
            return

        logger.info("Stopping Sentinel Engine...")

        self.running = False

        if (
            self.thread
            and self.thread.is_alive()
            and threading.current_thread() != self.thread
        ):
            self.thread.join(timeout=5)

        self._cleanup()

        logger.info("Sentinel Engine stopped.")

    def restart(self):
        logger.info("Restarting Sentinel Engine...")

        self.stop()
        self.start()

    # --------------------------------------------------
    # Main Engine Loop
    # --------------------------------------------------

    def run(self):

        logger.info("Sentinel Engine running.")

        try:

            self.camera.connect()

            while self.running:

                frame = self.camera.capture_frame()

                if frame is None:
                    time.sleep(0.05)
                    continue

                motion = self.motion_detector.detect(frame)

                if motion.detected:

                    self.events.publish(
                        event_types.MOTION_DETECTED,
                        "motion",
                        f"{motion.contour_count} motion regions detected.",
                        contour_count=motion.contour_count,
                    )

                    self.snapshot_saver.save(frame)

                    detections = self.object_detector.detect(frame)

                    for detection in detections:

                        if detection.label == "person":

                            self.events.publish(
                                event_types.PERSON_DETECTED,
                                "ai",
                                "Person detected.",
                            )

                            results = self.face_manager.process(frame)

                            for result in results:

                                if result.recognized:

                                    self.events.publish(
                                        event_types.FACE_RECOGNIZED,
                                        "face",
                                        f"{result.name} recognized.",
                                    )

                                else:

                                    self.events.publish(
                                        event_types.UNKNOWN_PERSON,
                                        "face",
                                        "Unknown person detected.",
                                    )

                        else:

                            self.events.publish(
                                event_types.OBJECT_DETECTED,
                                "ai",
                                f"{detection.label} detected.",
                            )

                image = getattr(frame, "data", frame)

                cv2.imshow("Project Sentinel", image)

                key = cv2.waitKey(1) & 0xFF

                if key == ord("q"):
                    logger.info("Quit requested.")
                    self.running = False

        except Exception:
            logger.exception("Sentinel Engine crashed.")

        finally:
            self._cleanup()

    # --------------------------------------------------
    # Cleanup
    # --------------------------------------------------

    def _cleanup(self):
        try:
            self.camera.disconnect()
        except Exception:
            logger.exception("Failed to release camera.")

        cv2.destroyAllWindows()

        self.running = False

    # --------------------------------------------------
    # Status
    # --------------------------------------------------

    @property
    def status(self):
        return {
            "running": self.running,
            "thread_alive": (
                self.thread is not None
                and self.thread.is_alive()
            ),
        }


engine = SentinelEngine()


if __name__ == "__main__":

    engine.start()

    try:

        while engine.running:
            time.sleep(1)

    except KeyboardInterrupt:

        logger.info("Keyboard interrupt received.")

        engine.stop()