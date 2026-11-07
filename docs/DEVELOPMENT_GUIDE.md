# Development Guide: Project Sentinel

This guide describes the repository as it is today: a Flask application served by Waitress,
raw `sqlite3`, OpenCV face models and a per-camera worker thread. There is no FastAPI, no
SQLAlchemy, no Alembic and no npm build step.

---

## 1. Getting started

```bash
python -m venv .venv
source .venv/bin/activate          # Windows Git Bash: source .venv/Scripts/activate
pip install -e ".[dev]"            # installs the app plus pytest and ruff
python tools/gen_secrets.py        # prints SECRET_KEY and SENTINEL_ENCRYPTION_KEYS
cp .env.example .env               # paste the generated values; never commit .env
python run.py                      # http://127.0.0.1:5000 -> first-run setup
pytest -q                          # 212 tests, roughly 40 s
```

`run.py` loads `.env`, initializes the database, starts the engine and serves the app with
Waitress. If Waitress is missing it falls back to Flask's development server and says so.

---

## 2. Repository layout

```
Project-Sentinel/
├── run.py                     # entry point: env, DB, engine, Waitress
├── pyproject.toml             # dependencies, pytest/ruff config
├── .env.example               # every supported variable, no secrets
├── models/                    # YuNet + SFace ONNX files (git-ignored)
├── data/                      # SQLite DB (git-ignored)
├── snapshots/                 # event JPEGs (git-ignored)
├── src/
│   ├── config/                # settings from environment
│   ├── security/              # auth store, passwords, sessions, CSRF, headers,
│   │                          # rate limits, validators, crypto, redaction
│   ├── database/              # connection manager, schema/migrations, repositories
│   ├── camera/                # source parsing/validation, capture + reconnect worker
│   ├── motion/                # frame differencing gate
│   ├── ai/                    # model loading, YuNet detection, SFace embeddings
│   ├── face/                  # enrolment/recognition service and storage
│   ├── engine/                # orchestration, dedupe, snapshot writing
│   ├── events/                # in-process event bus and SQLite event store
│   ├── notifications/         # rules, channels, dispatcher, outbox worker, web push
│   ├── dashboard/             # Flask app factory, routes, templates, static assets
│   ├── admin/                 # users, audit log, devices, configuration pages
│   └── app_logging/           # logging setup and secret redaction
├── tests/                     # pytest suite + fakes for camera/models/network
├── tools/                     # gen_secrets.py, manage_users.py, security_scan.py
└── docs/                      # see docs/README.md
```

Imports use absolute `src.` paths (`from src.security.store import SecurityStore`). The
package is installed editable, so tests and `run.py` resolve the same modules.

---

## 3. How a request flows

1. `src/dashboard/app.py:create_app()` builds the Flask app: config → security settings →
   blueprints → error handlers → headers. Test overrides are applied before the security
   settings so they cannot weaken cookies or limits.
2. `before_request` in `src/security/auth.py` loads the session, enforces idle/absolute
   timeouts and checks `session_epoch` (password change or "sign out everywhere").
3. State-changing requests pass through `src/security/csrf.py`: token from the form or
   `X-CSRF-Token`, plus an Origin check (normalized scheme/host/port).
4. Routes call repositories with short-lived `sqlite3` connections
   (`src/dashboard/db.py`, `src/database/manager.py`). Rows are converted to small
   dataclasses, not ORM objects.
5. Templates escape by default; the few `|safe` uses are for server-generated SVG/markdown.
   JavaScript reads the CSRF token from `<meta name="csrf-token">`.

Background work (camera reads, detection, outbox retries, retention) runs in daemon
threads started by `run.py`/the engine. The supported deployment is **one** web process;
in-memory rate limits and the engine assume that.

---

## 4. Common tasks

### Add a route

1. Put it in the relevant blueprint (`src/dashboard/routes.py`, `src/admin/routes.py`,
   `src/notifications/routes.py`).
2. Add `@login_required` (and `@admin_required` for admin actions); mutations also need a
   form with `{{ csrf_field() }}` or the `X-CSRF-Token` header.
3. Return a template or `jsonify`; do not leak exception text to the client.
4. Add a test in `tests/` using the `app`/`client` fixtures from `tests/app_support.py`.
   The suite never touches the real database: `DATABASE_PATH` points at `tmp_path`.

### Change the database

1. Append a new entry to `MIGRATIONS` in `src/database/schema.py` (never edit an old one).
2. Add the new column/table to the repositories that use it.
3. If auth columns change, update `ensure_user_columns()` in `src/security/store.py` too.
4. Add a migration test (see `tests/test_auth_upgrade_and_origins.py` for the pattern:
   build an old-shaped database, run the initializer, assert data survived).
5. Migrations do not back up the database; copy the file before upgrading a real install.

### Add a notification channel

Implement the channel in `src/notifications/channels.py`, register it in the dispatcher,
store credentials only through `SecretBox`, and add a delivery test with a fake transport.
Never call the network from tests.

### Face models

`src/ai/` loads `models/face_detection_yunet_2023mar.onnx` and
`models/face_recognition_sface_2021dec.onnx`. Missing models disable recognition with a
logged warning; the dashboard still runs. Tests use `tests/face_fakes.py`.

---

## 5. Verification commands

```bash
pytest -q                                   # full suite
pytest tests/test_security.py -q            # one module
pytest -q -k "csrf or origin"               # focused
ruff check .                                # lint (E9/F63/F7/F82)
python tools/security_scan.py               # static scan, exits 1 on HIGH
python tools/security_scan.py --staged      # also scans staged files and .env
python tools/manage_users.py --help         # admin recovery helpers
```

`ruff format` is **not** configured for this repository; do not reformat unrelated files.

CI (`.github/workflows/test.yml`) runs install → ruff → pytest on Python 3.12.
`.github/workflows/security.yml` runs the static scan, Bandit, `pip-audit` and Gitleaks.

---

## 6. Debugging

- Set `LOG_LEVEL=DEBUG`; logs go to stderr with secrets redacted by
  `src/app_logging/logger.py`.
- Login/CSRF problems are recorded in `audit_log` (`action='csrf_denied'`, with reason,
  origin and host) and in the server log.
- A 403 on a form usually means a missing/expired session, a stale token after a restart
  with a new `SECRET_KEY`, or a mismatched `Origin` — read the reason before changing code.
- The engine logs camera reconnects with backoff and model-load failures at startup.
- To inspect a database, use `sqlite3 data/sentinel.db` read-only queries; do not edit
  `users` rows by hand — `tools/manage_users.py` exists for password/role recovery.

---

## 7. Conventions

- Python 3.11+, 100-column lines, standard library `logging` (no `print` in `src/`).
- No bare `except:`; catch specific exceptions and log with context.
- Secrets only via environment/`SecretBox`; never in code, templates, logs or tests.
- New dependency? Justify it in `docs/DECISIONS.md` first; prefer the standard library.
- Keep documentation truthful: mark planned features as planned.
