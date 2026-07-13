from pathlib import Path

import cv2

from camera.frame import Frame
from face.embedding import FaceEmbedding
from face.face_detector import FaceDetector


image_path = Path(__file__).parent.parent / "8454.jpg"

image = cv2.imread(str(image_path))

frame = Frame(
    source="test",
    data=image,
)

detector = FaceDetector()

faces = detector.detect(frame)

embedding_engine = FaceEmbedding()

print(f"Faces Found: {len(faces)}")

for index, face in enumerate(faces):

    embedding = embedding_engine.generate(
        face,
    )

    print(f"\nFace {index + 1}")

    print("Embedding Length:", len(embedding))

    print("First 10 Values:")

    print(embedding[:10])

    print("Magnitude:", embedding.sum())