# Database Schema: Project Sentinel

**Status:** this document describes the schema the code actually creates. The authoritative
definitions are `src/database/schema.py` (application tables) and `src/security/store.py`
(users and audit log). There is no SQLAlchemy model layer, no Alembic revision tree and no
separate face database in current use.

---

## 1. Design principles

1. **One SQLite file** at `DATABASE_PATH` (default `data/database/sentinel.db`; `.env` may
   point elsewhere, e.g. `data/sentinel.db`).
2. **WAL mode** so the engine can write while the web app reads. A connection is opened per
   web request (`src/dashboard/db.py`) or per worker thread and is never shared across threads.
3. **Small ordered migrations** in `src/database/schema.py`, tracked by `PRAGMA user_version`.
   To change the schema, append a migration; never rewrite an old one.
4. **No `pickle`.** Embeddings are raw `float32` bytes. All SQL is parameterized; the only
   interpolated identifiers are fixed internal names.
5. **`model_id` on every embedding**, because vectors from different models are incomparable.
6. The `users`/`audit_log` tables are created by `SecurityStore`; it also adds missing auth
   columns in place (`active`, `session_epoch`, `last_login_at`) so legacy installs upgrade.

---

## 2. Tables

### `users` — `src/security/store.py`
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | auto-increment |
| `username` | TEXT UNIQUE NOT NULL COLLATE NOCASE | 3–32 chars, validated by the routes |
| `password_hash` | TEXT NOT NULL | argon2id when installed, otherwise scrypt |
| `role` | TEXT NOT NULL | `admin` or `viewer` (CHECK constraint) |
| `active` | INTEGER NOT NULL DEFAULT 1 | disabled accounts cannot sign in |
| `session_epoch` | INTEGER NOT NULL DEFAULT 0 | incremented to revoke all sessions |
| `created_at` | TEXT NOT NULL | UTC ISO-8601 |
| `last_login_at` | TEXT | UTC ISO-8601 |

### `audit_log` — `src/security/store.py`
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `ts` | TEXT NOT NULL | UTC ISO-8601 |
| `user_id` | INTEGER | nullable |
| `username` | TEXT | kept after user deletion |
| `action` | TEXT NOT NULL | e.g. `login_ok`, `csrf_denied`, `create_user` |
| `ip` | TEXT | remote address |
| `detail` | TEXT | redacted, max 500 chars |

Index: `idx_audit_ts`.

### `cameras`
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | display name |
| `kind` | TEXT NOT NULL | `usb`, `url`, or `file` (opt-in) |
| `source_enc` | TEXT NOT NULL | Fernet-encrypted source (URLs may contain a password) |
| `enabled` | INTEGER NOT NULL DEFAULT 1 | |
| `detection_fps` | INTEGER NOT NULL DEFAULT 3 | |
| `created_at` | TEXT NOT NULL | |

### `people`
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL UNIQUE COLLATE NOCASE | |
| `notes` | TEXT NOT NULL DEFAULT '' | |
| `consent_at` | TEXT NOT NULL | enrolment requires explicit consent |
| `created_at` | TEXT NOT NULL | |

### `face_embeddings`
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `person_id` | INTEGER NOT NULL → people(id) ON DELETE CASCADE | |
| `model_id` | TEXT NOT NULL | e.g. `sface-2021dec` |
| `vector` | BLOB NOT NULL | normalized float32 vector (128 values for SFace) |
| `quality` | REAL NOT NULL | detector confidence at enrolment |
| `created_at` | TEXT NOT NULL | |

Index: `idx_face_embeddings_person`.

### `unknown_faces`
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `camera_id` | INTEGER | nullable |
| `seen_at` | TEXT NOT NULL | updated when the same unknown is seen again |
| `model_id` | TEXT NOT NULL | |
| `vector` | BLOB NOT NULL | |
| `crop_path` | TEXT NOT NULL | under `<DATABASE_PATH parent>/unknown_faces/` |
| `seen_count` | INTEGER NOT NULL DEFAULT 1 | |

### `events`
| Column | Type | Notes |
|--------|------|-------|
| `event_id` | TEXT PRIMARY KEY | UUID |
| `event_type` | TEXT NOT NULL | `MOTION_DETECTED`, `FACE_RECOGNIZED`, … |
| `source` | TEXT NOT NULL | camera name |
| `message` | TEXT NOT NULL | human-readable |
| `timestamp` | TEXT NOT NULL | UTC ISO-8601 |

### `detections` / `snapshots`
Legacy tables from migration v1. The current engine writes `events` and saves JPEG files;
these tables are retained so older databases keep their data but are not used by new code.

- `detections(detection_id PK, person_name, known_person, confidence, camera, timestamp, snapshot_path)`
- `snapshots(snapshot_id PK, event_id FK → events, file_path, timestamp)`

### `notification_channels`
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `type` | TEXT NOT NULL | `inapp`, `webpush`, `email`, `webhook`, `telegram` |
| `name` | TEXT NOT NULL | |
| `config_enc` | TEXT NOT NULL | Fernet-encrypted JSON (SMTP creds, webhook URL/secret, bot token) |
| `enabled` | INTEGER NOT NULL DEFAULT 1 | |
| `created_at` | TEXT NOT NULL | |

### `notification_rules`
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | |
| `trigger_type` | TEXT NOT NULL | motion / person / known / unknown, depending on rules |
| `camera_id` | INTEGER | NULL = all cameras |
| `channel_ids` | TEXT NOT NULL | JSON array of channel ids |
| `start_time` / `end_time` | TEXT | optional local-time window |
| `cooldown_s` | INTEGER NOT NULL DEFAULT 60 | per rule/camera/who |
| `attach_snapshot` | INTEGER NOT NULL DEFAULT 1 | |
| `enabled` | INTEGER NOT NULL DEFAULT 1 | |

### `notification_outbox`
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `rule_id` | INTEGER | nullable |
| `channel_id` | INTEGER NOT NULL | |
| `payload` | TEXT NOT NULL | JSON notification |
| `status` | TEXT NOT NULL DEFAULT 'pending' | `pending`, `sent`, `failed` |
| `attempts` | INTEGER NOT NULL DEFAULT 0 | |
| `last_error` | TEXT | safe description, shown on the Alerts page |
| `next_attempt_at` | TEXT NOT NULL | UTC ISO-8601 |
| `created_at` | TEXT NOT NULL | |
| `sent_at` | TEXT | |

Index: `idx_outbox_due(status, next_attempt_at)`.

### `notifications` (in-app inbox)
`id, created_at, title, body, event_type, camera_id, camera_name, snapshot_path, is_read`.

### `push_subscriptions`
`id, endpoint UNIQUE, p256dh, auth, created_at`.

### `settings`
`key TEXT PRIMARY KEY, value TEXT NOT NULL` — used for `face_strictness`,
`push_contact`, `telegram_env_imported`.

### Legacy tables (not used by current code)
`admin_users` and `admin_audit_log` were created by an earlier admin module; `known_faces`
and `faces` by earlier face modules. They are left in place on existing databases rather
than deleted, so no historical data is destroyed. New code uses `users`, `audit_log`,
`people` and `face_embeddings`.

---

## 3. Migration history

| Version | Statements |
|---------|-----------|
| 1 | `events`, `detections`, `snapshots` |
| 2 | `users`, `cameras` (legacy `users` shape) |
| 3 | `people`, `face_embeddings`, `unknown_faces`, `settings` |
| 4 | notification channels/rules/outbox, `notifications`, `push_subscriptions` |
| 5 | Python step: add missing `users.active`, `users.session_epoch`, `users.last_login_at` |

`initialize_database()` applies pending versions at startup and sets `PRAGMA user_version`.
`SecurityStore` performs the same column check, so auth works even if it starts first.

---

## 4. Retention and file layout

| Data | Retention |
|------|-----------|
| Unknown-face rows and crops | 7 days (engine purge loop) |
| Sent/failed outbox rows, inbox rows | 30 days (outbox worker sweep) |
| Event rows and snapshot JPEGs | not pruned automatically — monitor disk |
| Audit log | not pruned automatically |
| Enrolled people/faces | until deleted by the owner |

Snapshots live under `SNAPSHOT_DIR`; face crops under
`<DATABASE_PATH parent>/unknown_faces/<camera id>/`. Both are served only through
authenticated routes with path-traversal checks; neither is a static directory.

---

## 5. Backup and recovery

Copy the database file while Sentinel is stopped, or copy `sentinel.db` together with its
`-wal`/`-shm` sidecars while it runs. There is no automatic pre-migration backup and no
"Export data" feature. Restoring a database requires the same `SENTINEL_ENCRYPTION_KEYS`
to decrypt camera and channel credentials. See [DEPLOYMENT.md](DEPLOYMENT.md) §5.
