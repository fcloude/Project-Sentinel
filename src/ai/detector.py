from ultralytics import YOLO

from src.ai.detection import Detection


class ObjectDetector:
    """YOLOv8 person/object detector.

    TEMPORARY: YOLOv8 is AGPL-3.0, which blocks selling the product. It is
    replaced in Phase 2 (see docs/DECISIONS.md, ADR-004).
    """

    def __init__(self):
        self.model = YOLO("yolov8n.pt")

    def detect(self, frame):
        results = self.model(frame.data, verbose=False)

        detections = []

        for result in results:
            for box in result.boxes:
                confidence = float(box.conf[0])
                if confidence < 0.5:
                    continue

                label = self.model.names[int(box.cls[0])]
                x1, y1, x2, y2 = map(int, box.xyxy[0])

                detections.append(
                    Detection(label=label, confidence=confidence, box=(x1, y1, x2, y2))
                )

        return detections
