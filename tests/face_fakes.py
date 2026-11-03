"""Stand-ins for the real face models, so tests need no model files.

A "face" is a noisy coloured square on a dark background. The fake detector
finds squares; the fake embedder turns a square's average colour into a vector.
Same colour = same person.
"""

import cv2
import numpy as np

from src.faces.backends import DetectedFace

COLORS = {  # BGR
    "alice": (255, 20, 20),
    "bob": (20, 255, 20),
    "carol": (20, 20, 255),
}


def make_photo(people, face=120, blur=False, seed=7):
    rng = np.random.default_rng(seed)
    image = np.zeros((480, 640, 3), dtype=np.uint8)

    for i, name in enumerate(people):
        x, y = 30 + i * (face + 40), 100
        noise = rng.uniform(0.55, 1.0, (face, face, 1)).astype(np.float32)
        image[y:y + face, x:x + face] = (np.array(COLORS[name], dtype=np.float32) * noise).astype(np.uint8)

    if blur:
        image = cv2.GaussianBlur(image, (0, 0), 15)
    return image


def encode(image) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image)
    assert ok
    return buffer.tobytes()


class FakeDetector:
    def detect(self, image):
        mask = (image.max(axis=2) > 30).astype(np.uint8)
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        faces = []
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            if area >= 400:
                faces.append(DetectedFace((int(x), int(y), int(w), int(h)), 0.95, None))
        faces.sort(key=lambda f: f.box[0])
        return faces


class FakeEmbedder:
    def embed(self, image, face):
        x, y, w, h = face.box
        mean = image[y:y + h, x:x + w].reshape(-1, 3).astype(np.float32).mean(axis=0)
        return mean / np.linalg.norm(mean)


def fake_backends():
    return FakeDetector(), FakeEmbedder()
