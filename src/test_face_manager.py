from pathlib import Path

import cv2

from camera.frame import Frame
from face.face_manager import FaceManager


manager = FaceManager()

image_path = Path(__file__).parent.parent / "8454.jpg"

manager.register(
    "Aryan",
    str(image_path),
)

image = cv2.imread(
    str(image_path),
)

frame = Frame(
    source="test",
    data=image,
)

results = manager.process(
    frame,
)

print()

print("=" * 50)

print("Face Manager Test")

print("=" * 50)

for result in results:

    print()

    print("Recognized :", result.recognized)

    print("Name       :", result.name)

    print("Confidence :", round(result.confidence, 4))

    print("Location   :", result.location)

print()

print("Known People:")

for person in manager.list_people():

    print("-", person)

print()

print("=" * 50)

print("SUCCESS")

print("=" * 50)