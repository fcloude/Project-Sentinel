"""The two face models, both run by plain OpenCV (no PyTorch, no AGPL code).

  * YuNet  : finds faces       (face_detection_yunet_2023mar.onnx)
  * SFace  : face -> 128 numbers (face_recognition_sface_2021dec.onnx)

Both are OpenCV Zoo models listed under Apache-2.0. Read the LICENSE file in
each model's folder of the opencv_zoo repository before you ship, and record
the files' SHA-256 hashes in THIRD_PARTY_LICENSES.md.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src.errors import UserFacingError

MODEL_ID = "sface-2021dec"  # saved with every embedding; vectors from different models can't be compared
DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"


class ModelsMissingError(UserFacingError):
    pass


def models_dir() -> Path:
    configured = os.getenv("MODELS_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "models"


def _require(path) -> Path:
    path = Path(path)
    if not path.is_file():
        raise ModelsMissingError(
            "Face recognition models are missing. Run: python scripts/download_models.py"
        )
    return path


@dataclass
class DetectedFace:
    box: tuple  # (x, y, width, height) in the ORIGINAL image
    score: float
    raw: object = None  # YuNet's 15-number row, in original-image pixels (needed for alignment)


def rows_to_faces(rows, scale: float):
    """YuNet rows found on a shrunken image -> faces in original-image pixels."""
    faces = []
    for row in rows:
        row = np.array(row, dtype=np.float32)
        row[:14] /= scale  # box + 5 landmark points; the score (last value) stays as is
        x, y, w, h = row[:4]
        faces.append(DetectedFace((int(x), int(y), int(w), int(h)), float(row[14]), row))
    return faces


class YuNetDetector:

    def __init__(self, model_path, score_threshold=0.7, nms_threshold=0.3, max_width=640):
        path = _require(model_path)
        self.max_width = max_width
        self._detector = cv2.FaceDetectorYN.create(
            str(path), "", (320, 320), score_threshold, nms_threshold, 5000
        )

    def detect(self, image):
        height, width = image.shape[:2]
        scale = min(1.0, self.max_width / width)  # detect on a smaller copy: faster

        small = image
        if scale < 1.0:
            small = cv2.resize(image, (int(width * scale), int(height * scale)))

        small_height, small_width = small.shape[:2]
        self._detector.setInputSize((small_width, small_height))
        _, rows = self._detector.detect(small)

        if rows is None:
            return []
        return rows_to_faces(rows, scale)


class SFaceEmbedder:

    def __init__(self, model_path):
        path = _require(model_path)
        self._recognizer = cv2.FaceRecognizerSF.create(str(path), "")

    def embed(self, image, face: DetectedFace):
        aligned = self._recognizer.alignCrop(image, face.raw)
        vector = np.asarray(self._recognizer.feature(aligned), dtype=np.float32).reshape(-1).copy()
        norm = np.linalg.norm(vector)
        return vector / norm if norm > 0 else vector


def load_default_backends():
    folder = models_dir()
    return YuNetDetector(folder / DETECTOR_FILE), SFaceEmbedder(folder / RECOGNIZER_FILE)
