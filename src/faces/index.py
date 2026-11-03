from dataclasses import dataclass

import numpy as np


@dataclass
class MatchResult:
    recognized: bool
    person_id: object
    name: str
    score: float


UNKNOWN = MatchResult(False, None, "Unknown", -1.0)


class FaceIndex:
    """Every known embedding in one matrix: matching a face is a single matrix multiply."""

    def __init__(self):
        self._state = (np.empty((0, 0), dtype=np.float32), [], [])

    def load(self, rows):
        """rows: [(person_id, name, vector)]. Swapped in at once, so readers never see half a load."""
        if not rows:
            self._state = (np.empty((0, 0), dtype=np.float32), [], [])
            return

        vectors = []
        for _, _, vector in rows:
            vector = np.asarray(vector, dtype=np.float32)
            norm = np.linalg.norm(vector)
            vectors.append(vector / norm if norm > 0 else vector)

        matrix = np.vstack(vectors)
        self._state = (matrix, [r[0] for r in rows], [r[1] for r in rows])

    def __len__(self):
        return len(self._state[1])

    def match(self, query, threshold: float, margin: float = 0.05) -> MatchResult:
        matrix, person_ids, names = self._state
        if matrix.shape[0] == 0:
            return UNKNOWN

        query = np.asarray(query, dtype=np.float32)
        if query.shape[0] != matrix.shape[1]:
            return UNKNOWN
        norm = np.linalg.norm(query)
        if norm == 0:
            return UNKNOWN
        scores = matrix @ (query / norm)

        # A person's score is their best photo.
        best = {}
        for index, score in enumerate(scores):
            person = person_ids[index]
            if person not in best or score > best[person][0]:
                best[person] = (float(score), names[index])

        ranked = sorted(best.items(), key=lambda item: item[1][0], reverse=True)
        top_id, (top_score, top_name) = ranked[0]

        if top_score < threshold:
            return MatchResult(False, None, "Unknown", top_score)

        # Two different people both scoring high means we can't be sure which one it is.
        if len(ranked) > 1 and top_score - ranked[1][1][0] < margin:
            return MatchResult(False, None, "Unknown", top_score)

        return MatchResult(True, top_id, top_name, top_score)
