import numpy as np


class FaceEmbedding:
    """
    Generates embeddings from InsightFace detection results.
    """

    def generate(self, face):

        embedding = np.asarray(
            face.embedding,
            dtype=np.float32,
        )

        norm = np.linalg.norm(
            embedding,
        )

        if norm > 0:
            embedding /= norm

        return embedding

    def similarity(
        self,
        embedding1,
        embedding2,
    ) -> float:

        embedding1 = embedding1 / np.linalg.norm(
            embedding1,
        )

        embedding2 = embedding2 / np.linalg.norm(
            embedding2,
        )

        return float(
            np.dot(
                embedding1,
                embedding2,
            )
        )

    def distance(
        self,
        embedding1,
        embedding2,
    ) -> float:

        return float(
            np.linalg.norm(
                embedding1 - embedding2,
            )
        )