from pathlib import Path

import cv2

from camera.frame import Frame
from face.database import FaceDatabase
from face.embedding import FaceEmbedding
from face.face_detector import FaceDetector


class FaceRegistry:

    def __init__(self):

        self.detector = FaceDetector()

        self.embedding = FaceEmbedding()

        self.database = FaceDatabase()

    def register(
        self,
        name: str,
        image_path: str,
    ) -> bool:

        image = cv2.imread(image_path)

        if image is None:

            raise FileNotFoundError(
                image_path,
            )

        frame = Frame(
            source=image_path,
            data=image,
        )

        faces = self.detector.detect(
            frame,
        )

        if len(faces) == 0:

            return False

        face = max(
            faces,
            key=lambda f: (
                f.bbox[2] - f.bbox[0]
            ) * (
                f.bbox[3] - f.bbox[1]
            ),
        )

        embedding = self.embedding.generate(
            face,
        )

        self.database.add_face(
            name,
            embedding,
        )

        return True

    def remove(
        self,
        name: str,
    ):

        self.database.delete_face(
            name,
        )

    def list_people(self):

        return [
            name
            for name, _
            in self.database.get_all_faces()
        ]