from ultralytics import YOLO

from src.ai.detection import Detection
print("=" * 60)
print("Detection imported from:", Detection.__module__)
print("Detection file:", Detection.__module__)
print("Annotations:", Detection.__annotations__)
print("Class:", Detection)
print("=" * 60)


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
                        label=label,
                        confidence=confidence,
                        box=(x1, y1, x2, y2),
                    )
                )

        print(f"Detections found: {len(detections)}")

        return detections