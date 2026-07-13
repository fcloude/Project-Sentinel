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
from src.notifications.notification_manager import NotificationManager

logger = get_logger(__name__)


class SentinelEngine:
    def __init__(self):
        self.running = False
        self.thread = None

        self.camera = CameraManager(USBCamera())
        self.events = EventManager()
        self.motion_detector = MotionDetector()
        self.snapshot_saver = SnapshotSaver()
        self.object_detector = ObjectDetector()
        self.face_manager = FaceManager()
        self.notification_manager = NotificationManager()

        self.events.subscribe(self.notification_manager.notify)

    # --------------------------------------------------
    # Engine Controls
    # --------------------------------------------------

    def start(self):
        if self.running:
            logger.info("Sentinel Engine is already running.")
            return

        logger.info("Starting Sentinel Engine...")

        self.running = True

        self.thread = threading.Thread(
            target=self.run,
            name="SentinelEngine",
            daemon=True,
        )

        self.thread.start()

    def stop(self):
        if not self.running:
            return

        logger.info("Stopping Sentinel Engine...")

        self.running = False

        if (
            self.thread is not None
            and self.thread.is_alive()
            and threading.current_thread() != self.thread
        ):
            self.thread.join(timeout=5)

        try:
            self.camera.release()
        except Exception as e:
            logger.exception("Failed to release camera: %s", e)

        cv2.destroyAllWindows()

        logger.info("Sentinel Engine stopped.")

    def restart(self):
        logger.info("Restarting Sentinel Engine...")

        self.stop()
        self.start()

    # --------------------------------------------------
    # Main Loop
    # --------------------------------------------------

    def run(self):
        logger.info("Sentinel Engine Running.")

        try:
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

                            results = self.face_manager.recognize(frame)

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

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    logger.info("Quit requested from OpenCV window.")
                    self.running = False

        except Exception:
            logger.exception("Unexpected error inside Sentinel Engine.")

        finally:
            try:
                self.camera.release()
            except Exception:
                pass

            cv2.destroyAllWindows()

            self.running = False

            logger.info("Sentinel Engine exited.")

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