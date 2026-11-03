import numpy as np

from src.faces.index import FaceIndex


def unit(*values):
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_known_face_is_recognised():
    index = FaceIndex()
    index.load([(1, "Alice", unit(1, 0, 0)), (2, "Bob", unit(0, 1, 0))])

    match = index.match(unit(0.95, 0.1, 0), threshold=0.36)

    assert match.recognized and match.name == "Alice" and match.person_id == 1


def test_face_below_threshold_is_unknown():
    index = FaceIndex()
    index.load([(1, "Alice", unit(1, 0, 0))])

    match = index.match(unit(0, 1, 0), threshold=0.36)

    assert not match.recognized and match.name == "Unknown"


def test_a_person_is_scored_by_their_best_photo():
    index = FaceIndex()
    index.load([
        (1, "Alice", unit(1, 0, 0)),     # front-on photo
        (1, "Alice", unit(0, 0, 1)),     # side-on photo
        (2, "Bob", unit(0, 1, 0)),
    ])

    match = index.match(unit(0.1, 0, 1), threshold=0.36)

    assert match.recognized and match.name == "Alice"


def test_two_similar_people_make_the_match_ambiguous():
    index = FaceIndex()
    index.load([(1, "Alice", unit(1, 0.00, 0)), (2, "Twin", unit(1, 0.02, 0))])

    match = index.match(unit(1, 0.01, 0), threshold=0.36, margin=0.05)

    assert not match.recognized  # can't tell which one it is: better "Unknown" than a wrong name


def test_empty_index_and_bad_input_are_unknown():
    index = FaceIndex()
    assert not index.match(unit(1, 0, 0), threshold=0.3).recognized

    index.load([(1, "Alice", unit(1, 0, 0))])
    assert not index.match(unit(1, 0, 0, 0), threshold=0.3).recognized   # wrong size (old model)
    assert not index.match(np.zeros(3, dtype=np.float32), threshold=0.3).recognized
    assert len(index) == 1
