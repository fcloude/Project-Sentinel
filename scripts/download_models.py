#!/usr/bin/env python3
"""Downloads the two face models into the models/ folder.

    python scripts/download_models.py

Both are OpenCV Zoo models (YuNet detector, SFace recogniser), listed as
Apache-2.0. BEFORE YOU SHIP: read the LICENSE file in each model's folder of
https://github.com/opencv/opencv_zoo, and record the SHA-256 hashes printed
below in THIRD_PARTY_LICENSES.md.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.faces.backends import DETECTOR_FILE, RECOGNIZER_FILE, models_dir  # noqa: E402

BASE = "https://huggingface.co/opencv/{repo}/resolve/main/{file}"

# SHA-256 hashes listed by a THIRD-PARTY mirror of the upstream files. A
# difference is a warning, not an error: verify against the upstream repository.
MODELS = [
    (
        DETECTOR_FILE,
        BASE.format(repo="face_detection_yunet", file=DETECTOR_FILE),
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    (
        RECOGNIZER_FILE,
        BASE.format(repo="face_recognition_sface", file=RECOGNIZER_FILE),
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "sentinel-model-downloader"})
    temporary = target.with_suffix(target.suffix + ".part")

    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done * 100 // total}%  ({done // 1024} KB)", end="", flush=True)
    print()
    temporary.replace(target)


def main() -> int:
    folder = models_dir()
    folder.mkdir(parents=True, exist_ok=True)
    print(f"Models folder: {folder}\n")

    for filename, url, expected in MODELS:
        target = folder / filename

        if target.is_file():
            print(f"{filename}: already downloaded")
        else:
            print(f"{filename}: downloading...")
            try:
                download(url, target)
            except Exception as error:
                print(f"  FAILED: {error}")
                print("  Check your internet connection and try again.")
                return 1

        actual = sha256_of(target)
        status = "matches" if actual == expected else "DIFFERS FROM"
        print(f"  sha256 {actual}")
        print(f"  {status} the hash listed by a third-party mirror")
        if actual != expected:
            print("  -> Verify this file against the upstream OpenCV Zoo repository.")

    print("\nDone. Record the hashes and licence files in THIRD_PARTY_LICENSES.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
