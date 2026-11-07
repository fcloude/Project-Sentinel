# Changelog

All notable changes to Project Sentinel are recorded here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) — `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
Versions: [Semantic Versioning](https://semver.org/) — `MAJOR.MINOR.PATCH`.
Commits: [Conventional Commits](https://www.conventionalcommits.org/) — `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `security`.

---

## [Unreleased]

### Security
- Telegram bot token and chat ID moved from source into `.env` (Phase 0)
- `pickle.loads()` on face embeddings replaced with raw `float32` bytes (Phase 0)

### Fixed
- `src/database/migration.py` SyntaxError (SQL outside string literal) (Phase 0)
- `Event.timestamp` stored as `str`; removed erroneous `.isoformat()` call in `repository.py` (Phase 0)
- `EventBus.publish` now wraps each subscriber in `try/except` so a failed Telegram call cannot crash detection (Phase 0)

### Removed
- All `*.bak` files
- `tools/fix_imports.py`
- `telegram_test.py`
- Empty stub files: `engine/*`, `face/face_service.py`, `face/face_registration.py`, `dashboard/websocket.py`, `database/models.py`, `database/sqlite.py`, `notifications/notification_manager.py`, `config/default.py`, `ai/labels.py`, `ai/model_loader.py`, `app_logging/formatter.py`
- `src/investigation/event_repository.py` (pseudo-code, not valid Python)
- `src/ai/detection_result.py`, `src/ai/ai_interface.py` (broken, unused)

---

## [0.4.0] — prototype

### Added
- Flask web dashboard with engine start/stop/restart controls
- `/api/status` JSON endpoint
- `DashboardState` dataclass and `DashboardService`
- `DashboardService.get_dashboard_state()` for Jinja2 template rendering

### Changed
- `run.py` launches Flask app wrapping `SentinelEngine`

---

## [0.3.0] — prototype

### Added
- `InvestigationEngine`: `events_history()`, `last_seen()`, `unknown_people()`, `daily_report()`
- `ReportGenerator` and `Statistics` backed by `EventRepository` / `DetectionRepository`

---

## [0.2.0] — prototype

### Added
- `FaceManager`, `FaceRegistry`, `FaceMatcher`, `FaceDetector`, `FaceDatabase`, `FaceEmbedding` — full face recognition pipeline using InsightFace `buffalo_l`
- `RecognitionResult` dataclass
- `ObjectDetector` using YOLOv8n (`ultralytics`)
- `MotionDetector` and `SnapshotSaver`
- `EventManager`, `EventBus`, `Event`, event type constants
- `NotificationManager`, `TelegramClient`, `CooldownManager`, `NotificationFormatter`
- `SentinelEngine` integrating all of the above in a daemon thread

---

## [0.1.0] — prototype

### Added
- `USBCamera`, `MockCamera`, `CameraManager`, `CameraInterface` (ABC), `Frame` dataclass
- `DatabaseManager`, `EventRepository`, `DetectionRepository`, `SnapshotRepository`
- `app_logging` module (`get_logger`)
- `config` module with `Settings` dataclass and `load_settings()` via python-dotenv

---

## Commit Convention Reference

```
feat(scope): add multi-camera support
fix(events): isolate subscriber failures with try/except
security(auth): add CSRF token to all state-changing routes
docs(architecture): update camera worker section
chore(deps): pin ONNX Runtime to 1.18.0
refactor(faces): replace pickle with float32 blob storage
test(pipeline): add motion detection regression test
```

Scopes: `camera`, `pipeline`, `faces`, `events`, `notifications`, `auth`, `dashboard`, `db`, `config`, `docs`, `deps`, `ci`, `licensing`.

Breaking changes: add `!` after the scope — `feat(db)!: migrate to SQLAlchemy` — and add a `BREAKING CHANGE:` footer.
