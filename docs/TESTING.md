# Testing: Project Sentinel

This document describes the test suite that actually exists in `tests/`. Everything here
runs with `pytest` and needs no camera, network access or Telegram account.

## 1. Principles

- **Hermetic.** Tests never read the developer's `.env` and never touch the real
  database. `tests/app_support.py` builds an explicit `SecurityConfig` from a fixed test
  key, a temporary SQLite file and a temporary snapshot directory.
- **Fakes over hardware.** `FileCamera`, the fakes in `tests/face_fakes.py` and patched
  `requests` stand in for cameras, models and Telegram.
- **Regression first for security.** `tests/test_security.py` asserts the security
  properties directly (CSRF, sessions, roles, path traversal, redaction), so a change
  that weakens one of them fails the suite.

## 2. Running

```bash
pip install -e ".[dev]"
pytest                     # whole suite (212 tests, ~40 s on a laptop)
pytest -x                  # stop at the first failure
pytest tests/test_security.py -q
pytest -k csrf
```

`pyproject.toml` already sets `testpaths = ["tests"]` and `pythonpath = ["."]`. The
web-platform dependencies (pytest-asyncio, httpx, faker, freezegun, respx, SQLAlchemy)
are **not** used by this project.

## 3. Fixtures and helpers

| Helper | Purpose |
|--------|---------|
| `conftest.py::sample_video` | Writes a tiny MJPG clip with a moving square for camera/engine tests. |
| `tests/app_support.make_security_config(tmp_path, **env)` | Builds a `SecurityConfig` from an explicit mapping (no `.env`). |
| `tests/app_support.use_temporary_database(tmp_path, monkeypatch)` | Repoints the process-wide database settings at `tmp_path`. |
| `tests/app_support.csrf_token(client, path)` | Reads the token from the page's `<meta name="csrf-token">` or hidden `csrf_token` field. |
| `tests/app_support.register/sign_in/log_in` | First-run setup and login helpers. |
| `tests/face_fakes.py` | Deterministic detector/embedder doubles. |

Typical app test:

```python
from app_support import PASSWORD, csrf_token, log_in, make_security_config
from src.dashboard.app import create_app

def test_dashboard_requires_login(tmp_path):
    app = create_app(engine=None, config=make_security_config(tmp_path))
    app.config["TESTING"] = True
    client = app.test_client()

    log_in(client)                                   # creates the admin, then signs in
    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    assert client.get("/").status_code == 302
```

## 4. What each file covers

| File | Tests | Covers |
|------|------:|--------|
| `test_security.py` | 53 | Config validation, password policy/hashing, rate limits, redaction, validators (URLs/images/paths), crypto + key rotation, face DB without pickle, app startup, setup wizard, login/logout, session timeouts and epochs, roles, CSRF (+ rejection reasons), headers, error handling, size limits, XSS escaping, scanner |
| `test_auth_upgrade_and_origins.py` | 12 | Legacy `users` table upgraded in place (store and migration runner, existing password still works), full login on an upgraded install, security overrides cannot weaken settings, CSRF origin normalization + loopback aliases + foreign/`null` rejection |
| `test_dashboard_auth.py` | 13 | First-run redirect, setup one-shot, login/logout, rate limit, engine controls, security headers, escaped event text |
| `test_notify_pipeline.py` | 20 | Event → rule matching → outbox → worker delivery, cooldowns, retries |
| `test_notify_routes.py` | 15 | `/alerts` and `/notifications` pages, channel/rule CRUD, viewer restrictions |
| `test_notify_rules_and_channels.py` | 13 | Rule evaluation, channel types, formatter output |
| `test_people_routes.py` | 12 | People page, enrolment upload validation, unknown-face promotion/dismissal, settings |
| `test_face_service.py` | 12 | Enrolment outcomes, strictness, unknown capture, reload |
| `test_engine.py` | 12 | Engine start/stop, motion gating, event publishing, cooldowns |
| `test_streaming_and_repo.py` | 7 | MJPEG frame generator, camera repository, snapshot handling |
| `test_crypto_and_urls.py` | 8 | SecretBox rotation, camera URL validation/masking, hardened camera-URL validator (SSRF/metadata hosts) |
| `test_cameras.py` | 7 | Camera registry routes, source validation, delete |
| `test_faces_index.py` | 5 | Embedding index behaviour |
| `test_faces_backends.py` | 5 | Backend selection and failure paths |
| `test_queued_subscriber.py` | 4 | Bounded async event queue |
| `test_motion.py` | 4 | Motion detector on synthetic frames |
| `test_camera_worker.py` | 4 | Worker lifecycle and reconnect behaviour |
| `test_event_store.py` | 2 | Event persistence |
| `test_event_bus.py` | 2 | Subscriber isolation |
| `test_evaluate.py` | 2 | Recognition threshold evaluation |

## 5. Security-specific assertions worth knowing

- `test_every_registered_route_is_covered` walks `app.url_map` and fails if a route is
  reachable without a session.
- `test_csrf_required_and_origin_checked` covers missing, wrong and foreign-`Origin`
  submissions.
- `test_csrf_rejection_is_classified_logged_and_audited` asserts a rejection is logged and
  written to `audit_log` as `csrf_denied`.
- `test_login_without_session_cookie_explains_reason_and_allows_retry` reproduces the
  reported `POST /login 403` and proves the retry then succeeds.
- `test_snapshot_route` feeds traversal payloads (`..%2F`, `%00`, `.env`) and expects 404.
- `test_audit_log_has_no_secrets` greps the audit rows for the submitted password.

## 6. Not covered (needs hardware, credentials or a host)

These are **not** verified by the suite and must be exercised manually:

- Real USB/IP/RTSP camera capture and reconnection.
- Face model accuracy on real footage (only fakes and thresholds are tested).
- Telegram delivery, web-push delivery to a real browser, and notification retries
  against the live APIs (the network layer is mocked).
- Production deployment: reverse proxy, TLS certificates, waitress under load, OS
  service installation, Windows file permissions.
- Email/SMTP channels, if enabled in a deployment.

## 7. CI

`.github/workflows/` runs the suite on push. The project's own acceptance bar before a
release: `pytest` green, `python tools/security_scan.py` clean, and the manual checklist
in [SECURITY_GUIDELINES.md](SECURITY_GUIDELINES.md) reviewed.
