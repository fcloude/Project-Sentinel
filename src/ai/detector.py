from ultralytics import YOLO

from ai.detection import Detection


class ObjectDetector:

    def __init__(self):

        self.model = YOLO("yolov8n.pt")

    def detect(self, frame):

        results = self.model(frame.data)

        detections = []

        for result in results:

            for box in result.boxes:

                cls = int(box.cls[0])

                confidence = float(box.conf[0])

                label = self.model.names[cls]

                if confidence < 0.5:
                    continue

                x1, y1, x2, y2 = map(
                    int,
                    box.xyxy[0],
                )

                detections.append(
                    Detection(
                        label,
                        confidence,
                        (x1, y1, x2, y2),
                    )
                )

        return detections