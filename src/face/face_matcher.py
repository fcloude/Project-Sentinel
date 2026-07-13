import numpy as np

from face.database import FaceDatabase
from face.embedding import FaceEmbedding
from face.recognition_result import RecognitionResult


class FaceMatcher:

    def __init__(
        self,
        threshold: float = 0.50,
    ):

        self.database = FaceDatabase()
        self.embedding = FaceEmbedding()
        self.threshold = threshold

    def match(self, face):

        query_embedding = self.embedding.generate(
            face,
        )

        best_name = "Unknown"
        best_similarity = -1.0

        for name, stored_embedding in self.database.get_all_faces():

            similarity = self.embedding.similarity(
                query_embedding,
                stored_embedding,
            )

            if similarity > best_similarity:

                best_similarity = similarity
                best_name = name

        recognized = best_similarity >= self.threshold

        x1, y1, x2, y2 = map(
            int,
            face.bbox,
        )

        return RecognitionResult(
            recognized=recognized,
            name=best_name if recognized else "Unknown",
            confidence=max(best_similarity, 0.0),
            location=(x1, y1, x2, y2),
        )