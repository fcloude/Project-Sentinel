# Third-party licences (DRAFT: verify before you ship)

This is the inventory a buyer's lawyer, or you, will ask for. **Every "expected" entry must be
confirmed** by reading the real licence file, and by running this on your final environment:

```
python -m pip install pip-licenses
pip-licenses --format=markdown --with-urls --with-license-file --no-license-path > THIRD_PARTY_LICENSES_GENERATED.md
```

Anything GPL, AGPL, "non-commercial" or "research only" must be removed, licensed, or isolated.
Model weights have their OWN licences, separate from code licences.

## Models (shipped or downloaded by the app)

| Component | File | Licence | Status |
|-----------|------|---------|--------|
| YuNet face detector | `face_detection_yunet_2023mar.onnx` | Apache-2.0 per OpenCV Zoo model cards seen on third-party mirrors | **Verify** in the `opencv_zoo` repository's licence files |
| SFace face recogniser | `face_recognition_sface_2021dec.onnx` | Apache-2.0 per the same sources | **Verify** as above |

SHA-256 of the files you actually ship (fill in from `python scripts/download_models.py`):

| File | SHA-256 |
|------|---------|
| face_detection_yunet_2023mar.onnx | |
| face_recognition_sface_2021dec.onnx | |

## Python dependencies (expected licences: verify)

| Package | Expected licence | Note |
|---------|------------------|------|
| opencv-python | Apache-2.0 (OpenCV) | **The wheels bundle FFmpeg (LGPL) and, in non-headless builds, Qt (LGPL).** LGPL obligations (notices, ability to replace the library) apply when you distribute. Read the package's licence notes; consider `opencv-python-headless` for installers |
| numpy | BSD-3-Clause | |
| Flask, Werkzeug, Jinja2, itsdangerous | BSD-3-Clause | |
| cryptography | Apache-2.0 OR BSD-3-Clause | |
| python-dotenv | BSD-3-Clause | |
| requests | Apache-2.0 | |
| python-telegram-bot | LGPL-3.0 | Optional channel. Used as an unmodified library; keep the licence notice with your distribution |

## Removed (do NOT ship)

| Component | Why |
|-----------|-----|
| Ultralytics YOLOv8 (`ultralytics`, `yolov8n.pt`) | AGPL-3.0: closed-source commercial use needs an Enterprise licence |
| InsightFace model packs (`buffalo_l` etc.) | Non-commercial research use only |
| PyTorch (pulled in by ultralytics) | Not needed any more; removed with it |
| onnxruntime | Was only used by InsightFace |
