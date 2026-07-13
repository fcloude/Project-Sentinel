from camera.frame import Frame

from face.face_detector import FaceDetector
from face.face_matcher import FaceMatcher
from face.face_registry import FaceRegistry


class FaceManager:

    def __init__(self):

        self.detector = FaceDetector()

        self.matcher = FaceMatcher()

        self.registry = FaceRegistry()

    def process(
        self,
        frame: Frame,
    ):

        faces = self.detector.detect(
            frame,
        )

        results = []

        for face in faces:

            result = self.matcher.match(
                face,
            )

            results.append(
                result,
            )

        return results

    def register(
        self,
        name: str,
        image_path: str,
    ) -> bool:

        return self.registry.register(
            name,
            image_path,
        )

    def remove(
        self,
        name: str,
    ):

        self.registry.remove(
            name,
        )

    def list_people(self):

        return self.registry.list_people()