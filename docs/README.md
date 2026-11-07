# Project Sentinel documentation

Project Sentinel is a local-first camera monitor: motion gate → face detection/recognition →
events → alerts. The dashboard is a server-rendered Flask app served by `waitress`, with
SQLite storage, authenticated sessions, CSRF protection and encrypted camera/channel
credentials.

**Status:** release-candidate after the 2026-11-06 audit. The implemented feature set is
listed below; planned work is marked as such and must not be treated as shipped.

## Start here

| Document | What it covers |
|----------|----------------|
| [../README.md](../README.md) | Install, configure, run, troubleshoot |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, data flow, concurrency, storage |
| [API_REFERENCE.md](API_REFERENCE.md) | Implemented routes and conventions; planned JSON API |
| [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) | Tables and relationships |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Environment, reverse proxy, service install, backup |
| [SECURITY_GUIDELINES.md](SECURITY_GUIDELINES.md) and [../SECURITY.md](../SECURITY.md) | Hardening checklist and reporting |
| [THREAT_MODEL.md](THREAT_MODEL.md) | Assets, adversaries, mitigations |
| [TESTING.md](TESTING.md) | What the pytest suite covers and what needs hardware |
| [DECISIONS.md](DECISIONS.md) | Architecture decision records |
| [DATA_FLOW.md](DATA_FLOW.md) | Detection → event → notification sequence |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | Local development workflow |
| [PHONE_ALERTS.md](PHONE_ALERTS.md) | Web Push setup |

## Implemented

- Camera registry for USB indices, RTSP/HTTP(S) URLs and (opt-in) video files; one reader
  thread per camera with reconnect/backoff.
- Motion detection plus YuNet/SFace face detection and recognition; known people,
  per-person embeddings, unknown-face inbox with promote/dismiss; strictness setting.
- Event bus, SQLite event log, in-app inbox, notification rules/cooldowns and an outbox
  worker with retries; channels: in-app, Telegram (BYO token), email/SMTP, webhook,
  Web Push (optional `pywebpush`).
- First-run admin setup, login/logout, argon2id (or scrypt) password hashing, roles
  (`admin`, read-only `viewer`), session idle/absolute timeouts, session rotation,
  default-deny authorization, login throttling, audit log.
- CSRF token on every state change plus normalized Origin checking; strict CSP and
  security headers; no CORS; encrypted camera URLs and channel credentials; authenticated
  snapshot routes with traversal guards.
- Admin pages for users, audit log, devices and read-only configuration.

## Not implemented (do not rely on it)

- Separate person/object detector (a face is the person signal).
- Liveness/anti-spoofing, 2FA, per-user data isolation, multi-tenancy.
- Continuous recording/NVR, cloud relay, mobile apps.
- Docker image, Windows installer, diagnostics bundle, automatic event retention.
- JSON CRUD API under `/api/v1` (see the "planned" half of API_REFERENCE.md).
- Licence management.

## Known limitations

- Face recognition is CPU-only and its accuracy depends on the models and footage; it is
  not suitable for access control.
- Biometric data and snapshots are not encrypted at rest; use full-disk encryption.
- Login throttling and rate limits are per process (one process is the supported model).
- Telegram, web push, SMTP and real camera hardware are not exercised by the test suite.
- A Telegram token and `.env` were committed in the project's history before the current
  cleanup. Revoke that token and purge history; see `../SECURITY_AUDIT.md` §8.
