import cv2
import numpy as np
import pytest

from src.faces.backends import (
    ModelsMissingError,
    SFaceEmbedder,
    YuNetDetector,
    load_default_backends,
    rows_to_faces,
)
from src.faces.service import MAX_IMAGE_SIDE, decode_image


def test_this_opencv_has_the_face_apis():
    assert hasattr(cv2, "FaceDetectorYN")
    assert hasattr(cv2, "FaceRecognizerSF")


def test_detections_on_a_shrunken_image_are_scaled_back_up():
    row = np.zeros(15, dtype=np.float32)
    row[:4] = [10, 20, 30, 40]      # x, y, w, h on an image shrunk to half size
    row[4] = 12                     # a landmark
    row[14] = 0.95                  # score

    face = rows_to_faces([row], scale=0.5)[0]

    assert face.box == (20, 40, 60, 80)
    assert face.raw[4] == 24
    assert abs(face.score - 0.95) < 1e-6
    assert abs(face.raw[14] - 0.95) < 1e-6  # the score must NOT be scaled


def test_missing_model_files_give_a_friendly_error(tmp_path):
    with pytest.raises(ModelsMissingError) as error:
        YuNetDetector(tmp_path / "missing.onnx")
    assert "download_models" in str(error.value)

    with pytest.raises(ModelsMissingError):
        SFaceEmbedder(tmp_path / "missing.onnx")


def test_default_backends_look_in_models_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    with pytest.raises(ModelsMissingError):
        load_default_backends()


def test_decode_image_handles_bad_and_huge_input():
    assert decode_image(b"") is None
    assert decode_image(b"not an image at all") is None

    ok, buffer = cv2.imencode(".jpg", np.full((100, 5000, 3), 90, dtype=np.uint8))
    image = decode_image(buffer.tobytes())
    assert max(image.shape[:2]) == MAX_IMAGE_SIDE
