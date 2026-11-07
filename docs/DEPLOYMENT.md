# Deployment: Project Sentinel

Project Sentinel is a single-process, local-first Flask application served by
`waitress`. There is no container image, installer, cloud component or external
database in the current tree. This document describes what the code actually does;
planned packaging is marked **Not implemented**.

See also: [ARCHITECTURE.md](ARCHITECTURE.md), [SECURITY_GUIDELINES.md](SECURITY_GUIDELINES.md),
[TESTING.md](TESTING.md).

---

## 1. Requirements

| Item | Requirement |
|------|-------------|
| Python | 3.11 or newer (3.12 recommended) |
| Disk | ~1 GB for the environment, models and Python packages; snapshots grow with use |
| OS | Windows 10/11, macOS 13+, or Linux with a supported OpenCV build |
| Camera | Optional. USB, RTSP/HTTP(S) URL, or a video file (`ALLOW_FILE_SOURCES=true`) |
| Network | Loopback only by default. LAN exposure requires a reverse proxy and explicit opt-in |

The face models (YuNet + SFace) are downloaded by `python scripts/download_models.py`
into `models/`. Without them the dashboard still runs; starting the engine reports a
friendly "models are missing" error.

---

## 2. Install and run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
python tools/gen_secrets.py        # prints SECRET_KEY and SENTINEL_ENCRYPTION_KEYS
# Paste both values into .env, then:
python run.py
```

Open <http://127.0.0.1:5000>. The first visit redirects to `/setup` to create the one
admin account. The wizard does **not** sign you in; use `/login` afterwards.

`run.py` validates the configuration first and refuses to start on unsafe settings.
It serves with `waitress` (8 threads). If `waitress` is not installed it logs a warning
and falls back to Flask's development server, which must not be exposed to a network.

---

## 3. Configuration

All values are read by `src/security/config.py` from the environment (`.env` is loaded
by `python-dotenv`). Secrets are never printed by the app.

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | — (**required**) | Signs the session cookie. Minimum 32 characters; placeholders are rejected. |
| `SENTINEL_ENCRYPTION_KEYS` | — (**required**) | One or more Fernet keys, comma-separated. The first encrypts; older keys may follow for rotation. |
| `HOST` | `127.0.0.1` | Bind address. A non-loopback address also requires `SENTINEL_ALLOW_LAN=true`. |
| `PORT` | `5000` | Listen port. |
| `SENTINEL_ALLOW_LAN` | `false` | Explicit confirmation for a non-loopback `HOST`. |
| `SENTINEL_HTTPS` | `false` | Set only when TLS terminates in front of the app. Adds `Secure` and the `__Host-` cookie prefix. |
| `SENTINEL_TRUSTED_PROXIES` | `0` | Number of reverse proxies, for correct client IP/scheme via `ProxyFix`. |
| `SENTINEL_TRUSTED_ORIGINS` | empty | Extra origins allowed to submit forms (comma-separated full origins). |
| `SENTINEL_SETUP_TOKEN` | empty | Allows first-run setup from a non-loopback address when set. |
| `DATABASE_PATH` | `data/database/sentinel.db` | SQLite file. The parent directory is created. |
| `SNAPSHOT_DIR` | `snapshots` | Event/face crop images. Never served as static files. |
| `SESSION_IDLE_MINUTES` | `30` | Idle timeout. |
| `SESSION_ABSOLUTE_HOURS` | `12` | Absolute session lifetime. |
| `MAX_UPLOAD_MB` | `5` | Maximum request body size. |
| `LOG_LEVEL` | `INFO` | Console log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `ALLOW_FILE_SOURCES` | `false` | Enables video-file cameras (demo/testing). |
| `MODELS_DIR` | `<repo>/models` | Where the YuNet/SFace ONNX files are read from. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Optional. Imported once into an encrypted Telegram alert channel when the Alerts page is first opened. |

`RETENTION_DAYS`, `LOG_FILE`, `CAMERA_SOURCE`, `COOKIE_SECURE` and `HTTPS` appear in
older notes but are **not read** by the current code. Use the names above.

---

## 4. Reverse proxy and remote access

Keep `HOST=127.0.0.1` and reach Sentinel over a VPN/Tailscale, or put a TLS reverse
proxy in front. Never port-forward the dashboard directly.

A correct nginx setup forwards both the scheme and the original host:

```nginx
server {
    listen 443 ssl;
    server_name sentinel.example.com;
    ssl_certificate     /etc/ssl/sentinel.crt;
    ssl_certificate_key /etc/ssl/sentinel.key;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Host  $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For   $remote_addr;
    }
}
```

Set `HOST=0.0.0.0`, `SENTINEL_ALLOW_LAN=true`, `SENTINEL_HTTPS=true` and
`SENTINEL_TRUSTED_PROXIES=1`. Caddy's `reverse_proxy localhost:5000` already forwards
the original host and scheme.

If the proxy rewrites `Host` (some tunnels and dev previews do), the browser's `Origin`
no longer matches the request host and CSRF correctly rejects the form with
`bad_origin`. Add the public address to `SENTINEL_TRUSTED_ORIGINS`, for example
`SENTINEL_TRUSTED_ORIGINS=https://sentinel.example.com`. The 403 page and the server
log now name both addresses.

`127.0.0.1` and `localhost` are treated as the same authority when the scheme and port
match; that is the same local server reached by two names.

---

## 5. Database, backup and upgrade

- One SQLite file at `DATABASE_PATH`, in WAL mode.
- Schema migrations are the small ordered list in `src/database/schema.py`, applied
  automatically when the app starts. `PRAGMA user_version` records progress. There is
  **no Alembic** and no automatic pre-migration backup.
- `src/security/store.py` also ensures the auth columns exist, so databases created by
  older builds are upgraded in place (existing users and password hashes are kept).

A consistent backup while Sentinel is stopped:

```bash
cp data/sentinel.db backups/sentinel-$(date +%Y%m%d).db
cp -r snapshots backups/snapshots-$(date +%Y%m%d)
```

While the app is running, copy `sentinel.db` together with `sentinel.db-wal` and
`sentinel.db-shm`, or use `sqlite3 data/sentinel.db ".backup backups/copy.db"`.
Store `.env` separately: it contains the key that decrypts camera and channel
credentials. Restoring a database without the matching `SENTINEL_ENCRYPTION_KEYS`
leaves those values unreadable.

**Retention is limited:** unknown-face crops are purged after 7 days and finished
outbox/inbox rows after 30 days. Event rows and snapshot files are **not** automatically
pruned; monitor disk usage.

### Password reset / user management

```bash
python tools/manage_users.py list
python tools/manage_users.py reset-password <username>
python tools/manage_users.py create <username> admin|viewer
python tools/manage_users.py disable <username>
```

Passwords are read interactively by `getpass`.

---

## 6. Running as a service

**Linux (systemd):**

```ini
[Unit]
Description=Project Sentinel
After=network.target

[Service]
WorkingDirectory=/opt/sentinel
EnvironmentFile=/opt/sentinel/.env
ExecStart=/opt/sentinel/.venv/bin/python /opt/sentinel/run.py
Restart=on-failure
User=sentinel

[Install]
WantedBy=multi-user.target
```

**Windows (NSSM):**

```powershell
nssm install SentinelService "C:\opt\sentinel\.venv\Scripts\python.exe" "C:\opt\sentinel\run.py"
nssm set SentinelService AppDirectory "C:\opt\sentinel"
nssm start SentinelService
```

The engine does not auto-start with the web process; press **Start** on the dashboard
(or call `POST /engine/start`). Cameras are read from the database at engine start.

---

## 7. Health checks and logs

| Endpoint | Auth | Returns |
|----------|------|---------|
| `GET /healthz` | public | `{"status": "ok"}` |
| `GET /api/health` | public | `{"status": "ok"}` |
| `GET /api/status` | login required | engine running/loading/error and per-camera state |

Logs go to standard output only (`LOG_LEVEL`), redacted by `RedactingFormatter`.
Configure collection in systemd (`journalctl -u sentinel -f`) or NSSM/Docker.

---

## 8. Not implemented in this tree

Do not plan around these without building them first:

- Dockerfile / `docker-compose.yml` and a published image.
- Windows installer, tray icon, Windows service registration script.
- Diagnostics bundle download, low-disk guard, log file rotation, nightly retention job.
- Automatic database backup before migrations.
- Multi-tenant hosting, per-user row isolation, 2FA, liveness detection.

For the current security posture and remaining risks, read
[SECURITY_GUIDELINES.md](SECURITY_GUIDELINES.md) and [../SECURITY.md](../SECURITY.md).
