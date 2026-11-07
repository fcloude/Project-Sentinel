# Project Sentinel

Local-first camera monitoring with motion detection, person/face recognition and alerts.
The dashboard runs on your own machine; camera credentials, face embeddings and snapshots
stay in local files. There is no cloud account.

Python 3.11+ is required. A camera is optional for exploring the UI, but live detection
needs a real camera source.

## Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -e .
```

## Configure

```bash
cp .env.example .env
python tools/gen_secrets.py        # prints SECRET_KEY + SENTINEL_ENCRYPTION_KEYS
```

Paste both values into `.env`. The app **refuses to start** while either is missing,
too short, or a placeholder — this is deliberate, not a bug.

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | — (required) | Signs the session cookie. Generate it; never reuse an example value. |
| `SENTINEL_ENCRYPTION_KEYS` | — (required) | Fernet key(s) for camera credentials. New key first; older keys may follow after a comma for rotation. |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Bind address. A non-loopback `HOST` also needs `SENTINEL_ALLOW_LAN=true`. |
| `SENTINEL_HTTPS` | `false` | Set only when TLS terminates in front of the app. Adds `Secure` and the `__Host-` cookie prefix. |
| `SENTINEL_TRUSTED_PROXIES` | `0` | Number of reverse proxies, for correct client IPs and scheme. |
| `SENTINEL_TRUSTED_ORIGINS` | empty | Extra origins allowed to submit forms (comma-separated). |
| `DATABASE_PATH` | `data/database/sentinel.db` | SQLite database. |
| `SNAPSHOT_DIR` | `snapshots` | Event and face crops. |
| `SESSION_IDLE_MINUTES` / `SESSION_ABSOLUTE_HOURS` | `30` / `12` | Session timeouts. |
| `MAX_UPLOAD_MB` | `5` | Upload limit. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Optional Telegram alerts. Never commit them. |

## Run

```bash
python run.py
```

Then open <http://127.0.0.1:5000>. On first run you are sent to `/setup` to create the
single admin account; the wizard does not sign you in. `/setup` is one-shot and only
reachable from the local machine unless you set `SENTINEL_SETUP_TOKEN`.

`run.py` serves through `waitress`. If `waitress` is missing it warns and falls back to
Flask's development server, which must not be exposed to a network.

## Test

```bash
pip install -e ".[dev]"
pytest
```

Camera hardware, Telegram delivery and a deployed reverse proxy are **not** exercised by
the suite; those tests use fakes and mocks.

## Troubleshooting

**`POST /login` returns 403.** This is a CSRF/session rejection, not a wrong password.
The token is bound to the session cookie, so it happens when the cookie was not sent
(cookies blocked, or `SENTINEL_HTTPS=true` while browsing over plain HTTP) or when the
form came from an older session (server restarted with a new `SECRET_KEY`). The page says
which case occurred; the server log and the `audit_log` table record `csrf_denied` with
a reason (`no_session`, `mismatch`, `missing_token`, `bad_origin`).

**"The request came from a different site."** This is `bad_origin`: the browser's
`Origin` header named a different `host:port` from the one Flask received. Use one
address consistently (`localhost` and `127.0.0.1` are accepted as the same machine when
the port matches). If a reverse proxy or tunnel rewrites `Host`, either forward the
original host (`X-Forwarded-Host` + `SENTINEL_TRUSTED_PROXIES`) or add the public address
to `SENTINEL_TRUSTED_ORIGINS`. The 403 page and the log now show both addresses.

**Upgrading an existing install.** Databases created by older builds are upgraded in
place on startup: the `users` table gains the columns the auth layer needs, and existing
accounts/passwords are preserved. Back up the SQLite file first — migrations do not
create a backup automatically.

**"Refusing to start".** A required secret is missing/invalid, or `HOST` is non-loopback
without `SENTINEL_ALLOW_LAN=true`, or debug mode is enabled. The message names the fix.

## Layout

```
run.py                  entry point (validates config, builds the app, serves it)
src/dashboard/          Flask app factory, page routes, streaming, templates
src/security/           auth, CSRF, sessions, password hashing, rate limits, validation
src/admin/              /admin control center (same session and users)
src/camera/             camera abstraction, OpenCV/USB/file sources, workers
src/engine/             detection loop, cooldowns, motion + AI analysis
src/face/, src/faces/   face detection, embeddings, known/unknown people
src/notifications/      rules, channels, outbox worker, web push
src/database/           schema, repositories, migrations
tests/                  pytest suite (212 tests)
tools/                  gen_secrets.py, manage_users.py, security_scan.py
docs/                   architecture, API, schema, deployment, threat model
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components and data flow
- [docs/API_REFERENCE.md](docs/API_REFERENCE.md) — implemented routes and conventions
- [docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md) — tables and relationships
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — running as a service, TLS, LAN access
- [docs/SECURITY_GUIDELINES.md](docs/SECURITY_GUIDELINES.md) and [SECURITY.md](SECURITY.md)
- [docs/TESTING.md](docs/TESTING.md) — what the suite covers

## Limitations

- Single-tenant, single admin install. Roles are `admin` and read-only `viewer`.
- No liveness detection: photo/screen spoofing is possible. Do not market or use it as
  access control.
- Not encrypted at rest; use full-disk encryption for biometric data.
