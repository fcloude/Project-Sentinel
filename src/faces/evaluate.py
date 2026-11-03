import numpy as np


def evaluate(vectors_by_person: dict, thresholds):
    """Accuracy numbers for a consented test set (ADR-004's benchmark gate).

    For every pair of photos: same person = "genuine", different people =
    "impostor". At each threshold:
      true_accept_rate  = genuine pairs correctly accepted
      false_accept_rate = impostor pairs wrongly accepted (the dangerous one)
    """
    people = {}
    for person, vectors in vectors_by_person.items():
        normalised = []
        for vector in vectors:
            vector = np.asarray(vector, dtype=np.float32)
            norm = np.linalg.norm(vector)
            normalised.append(vector / norm if norm > 0 else vector)
        people[person] = normalised

    genuine, impostor = [], []
    names = list(people)

    for i, name in enumerate(names):
        vectors = people[name]
        for a in range(len(vectors)):
            for b in range(a + 1, len(vectors)):
                genuine.append(float(vectors[a] @ vectors[b]))
        for other in names[i + 1:]:
            for va in vectors:
                for vb in people[other]:
                    impostor.append(float(va @ vb))

    rows = []
    for threshold in thresholds:
        rows.append(
            {
                "threshold": float(threshold),
                "true_accept_rate": (
                    sum(s >= threshold for s in genuine) / len(genuine) if genuine else None
                ),
                "false_accept_rate": (
                    sum(s >= threshold for s in impostor) / len(impostor) if impostor else None
                ),
                "genuine_pairs": len(genuine),
                "impostor_pairs": len(impostor),
            }
        )
    return rows
