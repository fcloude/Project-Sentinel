# PROJECT_SOURCE.md: Source of Truth

Keep this file current. When you start a new AI/chat session about the project, paste or attach this file first so the assistant has the same context you do.

**Last updated:** 2026-10-29 · **Phase:** 0 (stop the bleeding) · **Version:** prototype v0.x

---

## 1. One-paragraph product definition

Sentinel is a **local-first AI camera monitor** sold as downloadable software. It connects to any camera, recognises multiple known people, flags unknown visitors, and alerts the owner through its own notification system. Data never leaves the customer's machine. Target buyers: *(choose after user interviews: home / small business / …)*.

## 2. Non-negotiables

1. No secrets in source control, ever.
2. Only commercially-licensable code **and model weights** ship in the product.
3. Auth on every route; default bind `127.0.0.1`.
4. No `pickle`. No raw SQL string-building. Parameterised queries or ORM only.
5. Detection must never be blocked by notification/network failures.
6. Biometric data: consent recorded, retention enforced, deletion real.
7. Every user-visible failure has a visible explanation.

## 3. Tech stack (target)

Python 3.11+ · Flask (ADR-002) · Jinja2 + plain JS (HTMX later if needed) · SQLite (WAL) + versioned migrations in `database/schema.py` (ADR-003) · cryptography (Fernet) for stored secrets · OpenCV (capture/motion) · ONNX Runtime (models) · pydantic-settings · pytest + ruff · Docker.

## 4. Current prototype → target: file-by-file disposition

**Keep (move/rename into the new package)**

| Current | Becomes | Notes |
|---------|---------|-------|
| `camera/camera_interface.py` | `cameras/source.py` | Rename `CameraInterface` → `CameraSource`; add `open/read/close` |
| `camera/camera_exceptions.py` | `cameras/errors.py` | Keep |
| `camera/camera_types.py` | `cameras/kinds.py` | Drives the Add Camera form |
| `camera/frame.py` | `cameras/frame.py` | Switch to timezone-aware `datetime` |
| `camera/usb_camera.py` | `cameras/opencv_source.py` | Generalise to RTSP/HTTP/file |
| `camera/camera_manager.py` | `cameras/registry.py` + `worker.py` | Manager becomes registry of workers |
| `events/event.py`, `event_bus.py`, `event_types.py`, `event_manager.py` | `events/` | Isolate subscriber failures; add `"*"` persistence subscriber |
| `motion/detector.py`, `motion_result.py` | `pipeline/motion.py` | One instance per camera |
| `face/embedding.py` | `faces/embedder.py` | Remove in-place mutation; guard zero norm |
| `face/recognition_result.py` | `faces/results.py` | Keep |
| `notifications/cooldown.py` | `notifications/rules.py` | Re-key to (rule, camera, person) |
| `notifications/formatter.py`, `client.py` | `notifications/channels/telegram.py` | Becomes **one optional** channel using the user's own token |
| `config/loader.py`, `settings.py` | `settings.py` | Move to `pydantic-settings` |
| `app_logging/logger.py` | `logging.py` | Add rotation + secret redaction |
| `dashboard/static/css`, `templates/index.html` | `web/` | Rebuild with HTMX/Tailwind; reuse ideas, not markup |

**Refactor / replace**

| Current | Action |
|---------|--------|
| `main.py` (`SentinelEngine`) | Split into `pipeline/scheduler.py` + lifecycle in `app.py` lifespan. Remove `imshow`, import-time instantiation |
| `ai/detector.py` (YOLOv8, AGPL) | Replace with `PersonDetector` interface + permissive ONNX model (ADR-004) |
| `face/face_detector.py` (`buffalo_l`, non-commercial) | Replace with `FaceRecognizer` interface + YuNet/SFace (or AuraFace) (ADR-004) |
| `face/face_matcher.py`, `face_manager.py`, `face_registry.py` | Merge into `faces/` service around an in-memory `FaceIndex`; one detector instance |
| `face/database.py` (pickle, own DB) | Delete → `people` + `face_embeddings` tables, raw `float32` bytes |
| `database/manager.py`, `repositories/*`, `repository.py` | Replace with SQLAlchemy session + models |
| `database/migration.py`, `migrations` import, `schema.py`, `initializer.py` | Delete → Alembic |
| `investigation/*` | Rebuild on top of the new `events` store; `statistics.py` and `report_generator.py` become the daily digest |
| `motion/snapshot.py` | Unique filenames (event id), configured directory, retention, authenticated serving |
| `notifications/notifier.py` | Replace with rule engine + outbox + channel workers |
| `notifications/settings.py` | Delete (secrets → env / encrypted DB) |
| `notifications/bot.py`, `handlers.py`, `commands.py` | Optional: later a Telegram *command* bot channel; real `/status` data |
| `dashboard/routes.py`, `api.py`, `app.py`, `services/`, `models/` | Replace with FastAPI routers; one source of state (the engine) |
| `dashboard/static/js/app.js` | Delete (HTMX + SSE) |
| `camera/mock_camera.py` | Replace with `FileCamera` (loops `sample.mp4`) |
| `run.py` | Becomes `sentinel` CLI entry point (`sentinel run`, `sentinel reset-password`) |

**Delete now**

`*.bak` (all) · `tools/fix_imports.py` · `telegram_test.py` · `test_insightface.py` (move to `scripts/`) · `src/test_*.py` (rewrite as `tests/`) · `investigation/event_repository.py` (pseudo-code) · `ai/detection_result.py`, `ai/ai_interface.py` (broken, unused) · empty stubs: `engine/*`, `face/face_service.py`, `face/face_registration.py`, `dashboard/websocket.py`, `database/models.py`, `database/sqlite.py`, `notifications/notification_manager.py`, `config/default.py`, `ai/labels.py`, `ai/model_loader.py`, `app_logging/formatter.py`, `dashboard/templates/{cameras,events,faces,settings}.html` (empty; rebuild)

## 5. Conventions

- **Layout:** `src/sentinel/<domain>/`, tests in `tests/` mirroring the tree.
- **Style:** `ruff` (lint + format), type hints on public functions, docstrings explain *why*.
- **Commits:** Conventional Commits. **Branches:** `feat/…`, `fix/…`; `main` always releasable.
- **Errors:** raise typed exceptions inside the domain; handle at the boundary (worker loop, API handler); never `except: pass`.
- **Logging:** `logger = get_logger(__name__)`; no `print`; never log credentials, URLs with passwords, or face data.
- **Config:** env for secrets/paths; DB for user-editable settings.
- **Time:** store UTC ISO-8601; convert at the UI.
- **IDs:** UUID strings for events, integers for config tables.
- **Tests:** every new module ships with tests using the fake camera + temp DB; no tests touch the real DB or real network.
- **Migrations:** every schema change = new Alembic revision; never edit an old one.

## 6. Glossary

| Term | Meaning |
|------|---------|
| Embedding | 128/512-number vector representing a face; same person → similar vectors |
| Cosine similarity | How similar two embeddings are (−1…1). Higher = more alike |
| Threshold | Minimum similarity to call it a match; tuned per install |
| Motion gate | Cheap check that skips AI when nothing moves |
| Sub-stream | Low-resolution stream most IP cameras provide; ideal for detection |
| Outbox | DB table of pending notifications that workers deliver and retry |
| Channel | A way to deliver an alert (in-app, push, email, webhook, Telegram) |
| MoR | Merchant of record: a payment provider that handles tax/VAT as the seller |

## 7. Open questions (decide, then record in `docs/DECISIONS.md`)

- [ ] Target niche (home / small business / …)
- [ ] Final face + person models (Week 5 benchmark)
- [ ] Supported OS list for v1 (Windows + Docker/Linux?)
- [ ] Product name (trademark check)
- [ ] Pricing model and tiers
- [ ] Proprietary EULA vs AGPL

## 8. Decision log pointers

ADR-001 local-first · 002 FastAPI · 003 SQLite+Alembic · 004 model licensing gate · 005 notification outbox · 006 camera ingestion · 007 HTMX UI · 008 packaging & licence keys → see [docs/DECISIONS.md](docs/DECISIONS.md).
