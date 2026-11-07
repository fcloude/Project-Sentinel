# PROJECT_SOURCE.md — Engineering Source of Truth

> **Last updated:** 2026-11-06 · **Phase:** 0 (prototype stabilisation) · **Status:** Pre-MVP
>
> Paste or attach this file at the start of every AI/chat session so the assistant has the same context you do.

---

## 1. Product Mission

Sentinel is a **local-first AI camera monitor** sold as downloadable software. It connects to any camera, recognises multiple known people, flags unknown visitors, and delivers alerts through its own notification system. All video, snapshots, and face data remain on the customer's machine by default.

---

## 2. Product Vision

> "Any camera. Any face. Instant alert. Your data never leaves your home."

A non-technical owner should be able to: install Sentinel in under 15 minutes, point it at a camera, teach it who they know, and receive a phone alert with a photo the first time an unexpected visitor appears — without touching a command line, creating a cloud account, or configuring a Telegram bot.

---

## 3. Engineering Principles

| # | Principle | What it rules out |
|---|-----------|-------------------|
| 1 | **No secrets in source control** | Hardcoded tokens, API keys, passwords |
| 2 | **Only commercially-licensable code and model weights** | AGPL components, non-commercial research models |
| 3 | **Auth on every route; default bind `127.0.0.1`** | Open dashboards, `0.0.0.0` without an explicit opt-in |
| 4 | **No `pickle`; parameterised queries or ORM only** | Deserialization RCE vectors, SQL injection |
| 5 | **Detection must never be blocked by notification or network failures** | Synchronous Telegram calls inside the detection loop |
| 6 | **Biometric data: consent recorded, retention enforced, deletion real** | Silent accumulation of face data |
| 7 | **Every user-visible failure has a visible explanation** | Silent errors, generic "something went wrong" |

---

## 4. Technology Stack

### Target (MVP)

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Web framework | FastAPI + Uvicorn |
| Templating & UI | Jinja2 + HTMX + Alpine.js + Tailwind CSS |
| ORM & migrations | SQLAlchemy 2 + Alembic |
| Database | SQLite (WAL mode) |
| Camera capture | OpenCV (`cv2.VideoCapture`) |
| AI inference | ONNX Runtime |
| Configuration | pydantic-settings + python-dotenv |
| Testing | pytest |
| Linting / formatting | ruff |
| Container | Docker + docker-compose |

### Prototype (current, partially working)

| Layer | Technology | Status |
|-------|-----------|--------|
| Web framework | Flask | Prototype only; replace with FastAPI |
| Object detection | YOLOv8 via `ultralytics` (AGPL-3.0) | **Must be replaced before any sale** |
| Face recognition | InsightFace `buffalo_l` (non-commercial) | **Must be replaced before any sale** |
| Notifications | python-telegram-bot | Optional BYO-bot channel only |

---

## 5. System Overview

```
Cameras ──► Camera Workers (1 thread / camera)
                │
                ▼  latest frame @ detection_fps
           Pipeline
           ├─ 1. Motion gate  (cheap, per-camera state)
           ├─ 2. Person / object detector
           ├─ 3. Face detect on person crop → embedding
           └─ 4. FaceIndex.match → known / unknown
                │
                ▼  domain events
           Event Bus
           ├─► Event Store (SQLite)
           └─► Notification Service
               ├─ Rule engine
               ├─ Outbox (DB table)
               └─ Channel workers
                  ├─ In-app (SSE)
                  ├─ Web Push / PWA
                  ├─ Email (SMTP)
                  ├─ Webhook
                  └─ Telegram (BYO token)

           Web App (FastAPI + Jinja2/HTMX)
           ├─ Auth, dashboard, live view
           ├─ People & camera management
           └─ Events timeline, settings
```

Everything runs in a single Python process for MVP. Threads handle camera I/O; ONNX Runtime releases the GIL during inference.

---

## 6. Current Prototype: Module Disposition

> See `docs/ARCHITECTURE.md` for the full component design and `ROADMAP.md` for the phased plan.

### Keep (move into the new package structure)

| Prototype path | Target path | Notes |
|----------------|-------------|-------|
| `camera/camera_interface.py` | `cameras/source.py` | Rename to `CameraSource` |
| `camera/frame.py` | `cameras/frame.py` | Switch to timezone-aware UTC datetime |
| `camera/usb_camera.py` | `cameras/opencv_source.py` | Generalise to RTSP/HTTP/file |
| `events/event*.py` | `events/` | Isolate subscriber failures; add `"*"` persistence subscriber |
| `motion/detector.py` | `pipeline/motion.py` | One instance per camera |
| `face/embedding.py` | `faces/embedder.py` | Remove in-place mutation; zero-norm guard |
| `notifications/cooldown.py` | `notifications/rules.py` | Re-key to (rule, camera, person) |
| `config/loader.py`, `settings.py` | `settings.py` | Move to pydantic-settings |
| `app_logging/logger.py` | `logging.py` | Add rotation and secret redaction |

### Refactor / Replace

| Prototype path | Action |
|----------------|--------|
| `main.py` (`SentinelEngine`) | Split into `pipeline/scheduler.py` + lifecycle in `app.py` lifespan; remove `imshow` and import-time instantiation |
| `ai/detector.py` (YOLOv8, AGPL) | Replace with `PersonDetector` interface + permissive ONNX model (ADR-004) |
| `face/face_detector.py` (`buffalo_l`) | Replace with `FaceRecognizer` interface + YuNet/SFace or AuraFace (ADR-004) |
| `face/face_matcher.py`, `face_manager.py`, `face_registry.py` | Merge into `faces/` service around in-memory `FaceIndex` |
| `face/database.py` (pickle) | Delete → `people` + `face_embeddings` tables, raw `float32` bytes |
| `database/manager.py`, `repositories/*` | Replace with SQLAlchemy session + models |
| `database/migration.py`, `schema.py`, `initializer.py` | Delete → Alembic |
| `notifications/notifier.py` | Replace with rule engine + outbox + channel workers |
| `notifications/settings.py` | Delete (secrets → `.env` / encrypted DB) |
| `dashboard/routes.py`, `api.py`, `app.py` | Replace with FastAPI routers; engine as single state source |

### Delete Now

`*.bak` files · `tools/fix_imports.py` · `telegram_test.py` · `src/test_*.py` (rewrite as `tests/`) · `investigation/event_repository.py` (pseudo-code) · `ai/detection_result.py`, `ai/ai_interface.py` (broken, unused) · all empty stub files under `engine/`, `face/face_service.py`, `face/face_registration.py`, `dashboard/websocket.py`, `database/models.py`, `database/sqlite.py`, `notifications/notification_manager.py`, `config/default.py`, `ai/labels.py`, `ai/model_loader.py`, `app_logging/formatter.py`

---

## 7. Development Standards

- **Layout:** `src/sentinel/<domain>/`; tests mirror the tree under `tests/`.
- **Style:** `ruff` for lint and format; type hints on all public functions; docstrings explain *why*.
- **Commits:** Conventional Commits (`feat(camera): …`, `fix(events): …`).
- **Branches:** `feat/…`, `fix/…`; `main` is always releasable.
- **Errors:** raise typed domain exceptions; handle at boundaries (worker loop, API handler); never `except: pass`.
- **Logging:** `logger = get_logger(__name__)`; no `print` statements; never log credentials, camera URLs with passwords, or face data.
- **Config:** environment variables for secrets/paths; database for user-editable settings.
- **Time:** store UTC ISO-8601; convert to local time only at the UI layer.
- **IDs:** UUID strings for events; integers for configuration tables.
- **Tests:** every new module ships with tests using the `FakeCamera` and a temporary database; no test touches the real database or real network.
- **Migrations:** every schema change = new Alembic revision; never edit a committed revision.

---

## 8. Known Limitations (prototype)

| # | Limitation | Phase to fix |
|---|-----------|-------------|
| L-1 | Telegram bot token and chat ID hardcoded in source | **Phase 0 (immediate)** |
| L-2 | Dashboard has no login; binds to `0.0.0.0`; no CSRF | Phase 1 |
| L-3 | `pickle.loads()` used for face embeddings (RCE risk) | Phase 0 |
| L-4 | `src/database/migration.py` does not compile (`SyntaxError`) | Phase 0 |
| L-5 | Events are never persisted; investigation reads empty tables | Phase 1 |
| L-6 | InsightFace `buffalo_l` and YOLOv8 are not commercially licensed | Phase 2 (gate) |
| L-7 | One failing Telegram call stops the entire detection loop | Phase 0 |
| L-8 | `cv2.imshow` runs inside the engine thread (breaks headless) | Phase 1 |
| L-9 | `SentinelEngine` and models instantiate at import time | Phase 1 |
| L-10 | No face deduplication; pipeline runs face detection once per person detection, not once per frame | Phase 2 |
| L-11 | Two separate SQLite databases (`sentinel.db` in CWD vs `data/database/sentinel.db`) | Phase 1 |
| L-12 | No liveness / anti-spoofing (a printed photo can fool the matcher) | Disclose; fix post-MVP |

---

## 9. Open Decisions

- [ ] Target niche: home / small business / regional (decide after user interviews)
- [ ] Face recognition model: YuNet+SFace vs AuraFace vs paid licence (ADR-004 gate, Week 5 benchmark)
- [ ] Person detector model: permissive ONNX checkpoint choice
- [ ] Supported OS list for v1 (Windows + Docker/Linux minimum)
- [ ] Product name and trademark check
- [ ] Pricing model and tiers
- [ ] Proprietary EULA vs AGPL-3.0

---

## 10. Glossary

| Term | Meaning |
|------|---------|
| Embedding | 128/512-float vector encoding a face; similar faces → high cosine similarity |
| Cosine similarity | Dot product of two unit vectors; range −1…1; higher = more similar |
| Motion gate | Cheap frame-diff check that skips expensive AI when nothing moves |
| Sub-stream | Low-resolution stream most IP cameras expose alongside the main stream; preferred for detection |
| Outbox | Database table of pending notifications that workers deliver with retry and backoff |
| Channel | A delivery path for an alert (in-app, push, email, webhook, Telegram) |
| FaceIndex | In-memory matrix of all enrolled embeddings enabling batch cosine matching |
| MoR | Merchant of Record — a payment provider that handles sales tax/VAT as the legal seller |
| BYO | Bring Your Own (e.g. BYO Telegram bot token — customer supplies their own) |
