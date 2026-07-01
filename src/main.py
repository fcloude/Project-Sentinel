import cv2

from app_logging import get_logger

from camera.camera_manager import CameraManager
from camera.usb_camera import USBCamera

from motion.detector import MotionDetector
from motion.snapshot import SnapshotSaver

from events.event import Event
from events.event_bus import EventBus


logger = get_logger(__name__)

bus = EventBus()

detector = MotionDetector()
saver = SnapshotSaver()


def log_event(event: Event) -> None:
    logger.info("%s | %s", event.event_type, event.message)


bus.subscribe("CAMERA_CONNECTED", log_event)
bus.subscribe("CAMERA_DISCONNECTED", log_event)
bus.subscribe("MOTION_DETECTED", log_event)


def main():

    camera = CameraManager(USBCamera())

    logger.info("Starting Project Sentinel...")

    camera.connect()

    bus.publish(
        Event(
            event_type="CAMERA_CONNECTED",
            source="camera",
            message="USB Camera connected."
        )
    )

    try:

        while True:

            frame = camera.capture_frame()

            motion = detector.detect(frame)

            if motion.detected:

                bus.publish(
                    Event(
                        event_type="MOTION_DETECTED",
                        source="motion",
                        message=f"{motion.contour_count} motion regions detected."
                    )
                )

                snapshot = saver.save(frame)

                logger.info(
                    "Snapshot saved -> %s",
                    snapshot,
                )

                for x, y, w, h in motion.bounding_boxes:

                    cv2.rectangle(
                        frame.data,
                        (x, y),
                        (x + w, y + h),
                        (0, 255, 0),
                        2,
                    )

            cv2.imshow(
                "Project Sentinel",
                frame.data,
            )

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:

        camera.disconnect()

        bus.publish(
            Event(
                event_type="CAMERA_DISCONNECTED",
                source="camera",
                message="USB Camera disconnected."
            )
        )

        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

    detections = detector.detect(frame)

for detection in detections:

    x1, y1, x2, y2 = detection.box

    cv2.rectangle(
        frame.data,
        (x1, y1),
        (x2, y2),
        (255, 0, 0),
        2,
    )

    cv2.putText(
        frame.data,
        f"{detection.label} {detection.confidence:.2f}",
        (x1, y1 - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 0, 0),
        2,
    )

    if detection.label == "person":

        bus.publish(
            Event(
                event_type="PERSON_DETECTED",
                source="ai",
                message="Person detected."
            )
        )

    else:

        bus.publish(
            Event(
                event_type="OBJECT_DETECTED",
                source="ai",
                message=f"{detection.label} detected."
            )
        )