#!/usr/bin/env python3
"""Measures face accuracy and speed on YOUR consented test photos (ADR-004 gate).

Put photos in one folder per person (only people who agreed):

    test_photos/
        alice/1.jpg 2.jpg 3.jpg ...
        bob/1.jpg 2.jpg 3.jpg ...

Run:

    python scripts/benchmark_faces.py test_photos

For each threshold you get:
  true accept  : same person correctly recognised
  false accept : DIFFERENT people wrongly treated as the same person (the dangerous one)
Pick the strictness whose false-accept rate you can live with, and publish the numbers.
"""

import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.faces.backends import load_default_backends  # noqa: E402
from src.faces.evaluate import evaluate  # noqa: E402

EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1

    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"Folder not found: {root}")
        return 1

    detector, embedder = load_default_backends()

    vectors, detect_ms, embed_ms, skipped = {}, [], [], 0

    for person_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for photo in sorted(person_dir.iterdir()):
            if photo.suffix.lower() not in EXTENSIONS:
                continue
            image = cv2.imread(str(photo))
            if image is None:
                skipped += 1
                continue

            started = time.perf_counter()
            faces = detector.detect(image)
            detect_ms.append((time.perf_counter() - started) * 1000)

            if not faces:
                skipped += 1
                continue

            face = max(faces, key=lambda f: f.box[2] * f.box[3])
            started = time.perf_counter()
            vector = embedder.embed(image, face)
            embed_ms.append((time.perf_counter() - started) * 1000)

            vectors.setdefault(person_dir.name, []).append(vector)

    people = {name: v for name, v in vectors.items() if v}
    print(f"People: {len(people)}   Photos used: {sum(len(v) for v in people.values())}   "
          f"Skipped (unreadable or no face): {skipped}")

    if len(people) < 2:
        print("Need at least 2 people with photos to measure false accepts.")
        return 1

    if detect_ms:
        print(f"Detection: {sum(detect_ms) / len(detect_ms):.0f} ms/photo   "
              f"Embedding: {sum(embed_ms) / len(embed_ms):.0f} ms/face\n")

    print("threshold   true accept   false accept")
    for row in evaluate(people, [0.20, 0.25, 0.30, 0.363, 0.40, 0.45, 0.50, 0.55, 0.60]):
        tar, far = row["true_accept_rate"], row["false_accept_rate"]
        print(f"  {row['threshold']:.3f}      "
              f"{(tar * 100 if tar is not None else float('nan')):6.1f}%      "
              f"{(far * 100 if far is not None else float('nan')):6.2f}%")

    print("\nBuilt-in strictness: strict 0.45 | balanced 0.363 | lenient 0.30")
    return 0


if __name__ == "__main__":
    sys.exit(main())
