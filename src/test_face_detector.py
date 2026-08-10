import cv2
from pathlib import Path

from src.camera.frame import Frame
from src.face.face_detector import FaceDetector


image_path = Path(__file__).parent.parent / "8454.jpg"

image = cv2.imread(str(image_path))

if image is None:
    raise FileNotFoundError(
        f"Cannot load image: {image_path}"
    )

frame = Frame(
    source="test",
    data=image,
)

detector = FaceDetector()

faces = detector.detect(frame)

print(f"\nFaces Found: {len(faces)}\n")

for face in faces:
    print(face.bbox)