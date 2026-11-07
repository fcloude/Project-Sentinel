# Architecture: Project Sentinel (MVP)

> Companion docs: [../ROADMAP.md](../ROADMAP.md) · [DECISIONS.md](DECISIONS.md) · [SECURITY_GUIDELINES.md](SECURITY_GUIDELINES.md) · [DATA_FLOW.md](DATA_FLOW.md)

---

## 1. Goals and Constraints

**Goals**
- Connect any camera: USB, RTSP/IP, phone stream, video file
- Detect motion → people → known/unknown faces → alert owner within ~5 s on CPU-only hardware
- Local-first: video and face data never leave the customer's machine by default
- Non-developer install in under 15 minutes

**Constraints**
- Single developer, part-time
- No GPU assumption; must run on a modern mini-PC or laptop CPU
- Only permissively licensed models and libraries (ADR-004)
- One Python process for MVP; split only if profiling demands it

---

## 2. High-Level Architecture

```mermaid
graph TD
    CAM["Camera Sources\nUSB · RTSP/IP · Phone · File"]
    CW["Camera Workers\n1 thread / camera\nauto-reconnect"]
    PL["Analysis per camera\n(shared inference lock)"]
    MG["Motion Gate"]
    FD["Face Detect + Embed\nYuNet + SFace (OpenCV)"]
    FI["FaceIndex\nin-memory matrix match"]
    EB["Event Bus"]
    ES["Event Store\nSQLite WAL"]
    NS["Notification Service\nrule engine · outbox · workers"]
    CH["Channels\nIn-app · Push · Email · Webhook · Telegram"]
    WA["Web App\nFlask + Jinja2"]
    USR["User\nbrowser / phone"]

    CAM --> CW
    CW -->|"latest frame @ detection_fps"| PL
    PL --> MG
    MG -->|motion detected| FD
    FD --> FI
    FI -->|domain events| EB
    EB --> ES
    EB --> NS
    NS --> CH
    CH --> USR
    ES --> WA
    WA --> USR
```

---

## 3. Component Responsibilities

### 3.1 Camera Layer

Each camera runs in its own `CameraWorker` thread. The worker maintains a "latest frame" slot: it reads frames continuously and always overwrites the slot, so the pipeline consumes the most recent frame even when it falls behind.

```mermaid
stateDiagram-v2
    [*] --> CONNECTING
    CONNECTING --> ONLINE: open() succeeds
    CONNECTING --> RECONNECTING: open() fails
    ONLINE --> RECONNECTING: read() fails
    RECONNECTING --> CONNECTING: backoff elapsed
    RECONNECTING --> ERROR: max_attempts exceeded
    ERROR --> CONNECTING: manual retry via UI
```

**Reliability rules:**

1. **Latest-frame slot** — always read; never queue; drop stale frames.
2. **Exponential backoff** on reconnect: 1 s → 2 → 4 … cap 30 s.
3. **Sub-stream for detection**, main stream for snapshots only.
4. **Never log the full camera URL** — it contains the password. Mask: `rtsp://user:***@host/…`.

**Camera source interface:**

```python
class CameraSource(ABC):
    def open(self) -> None: ...
    def read(self) -> Frame: ...        # raises CameraReadError
    def close(self) -> None: ...
    @property
    def status(self) -> CameraStatus: ...
```

Concrete implementations: `OpenCVSource` (USB / RTSP / HTTP / file), `FakeCamera` (loops `sample.mp4` for tests). Camera credentials are stored encrypted in the database (see §6).

---

### 3.2 Detection Pipeline

Each camera has its own `CameraAnalyzer` thread. It reads the newest frame from the camera worker at `detection_fps`, applies the motion gate, then runs face detection/embedding under one process-wide inference lock so several cameras cannot fight over the CPU. There is **no separate person/object detector** in this tree: a detected face is the signal that a person is present.

**Pipeline stages (in order):**

| Stage | Implementation | Approx cost on CPU |
|-------|---------------|-------------------|
| Motion gate | OpenCV frame diff + contour area | < 5 ms |
| Face detection | YuNet (OpenCV Zoo, Apache-2.0) | 10–30 ms |
| Embedding generation | SFace (OpenCV Zoo, Apache-2.0) | 10–20 ms |
| FaceIndex match | NumPy matrix multiply | < 1 ms |

Face recognition runs on every detected face in the frame. The per-camera cooldown (10 s motion, 30 s person/identity, 5 s snapshot) prevents duplicate events.

**Per-camera, per-identity cooldown** (default 60 s) prevents duplicate events for the same person at the same camera — separate from the notification cooldown.

---

### 3.3 Face Recognition

**Data model (simplified):**

```
people (id, name, notes, consent_at, created_at)
  │
  └── face_embeddings (id, person_id→people, model_id,
                       vector BLOB float32, quality REAL,
                       photo_path TEXT, created_at)

unknown_faces (id, camera_id, seen_at, model_id,
               vector BLOB, crop_path, status)
```

**FaceIndex** (in-memory, rebuilt on enrol/delete):

```python
class FaceIndex:
    names: list[str]
    matrix: np.ndarray        # shape (N_embeddings, 512), float32, row-normalised

    def best(self, query: np.ndarray) -> tuple[str, float]:
        """Single matrix multiply; O(N) but stays fast to tens of thousands."""
        scores = self.matrix @ (query / np.linalg.norm(query))
        i = int(scores.argmax())
        return self.names[i], float(scores[i])
```

Accepts a match if `score >= threshold` **and** margin over second-best person is sufficient.

**Enrolment quality gate:** one face per photo, detector confidence ≥ 0.7, face ≥ 80 px wide, not blurry (Laplacian variance threshold). Reject with a human-readable reason.

**Unknown-face inbox:** unknown face crops are saved with their embedding, deduplicated by similarity. The UI shows "Who is this?" → *Name* (promotes to a person) or *Dismiss*.

---

### 3.4 Event Bus

```python
class EventBus:
    def publish(self, event: Event) -> None:
        for callback in self._subscribers.get(event.event_type, []) + \
                        self._subscribers.get("*", []):
            try:
                callback(event)
            except Exception:
                logger.exception("Subscriber %r failed on %s",
                                 callback, event.event_type)
```

**Critical:** each subscriber is wrapped in `try/except`. A failing Telegram call must never stop detection. The `"*"` wildcard subscriber persists every event to the database.

---

### 3.5 Notification Service

```mermaid
graph LR
    E["Event"] --> RE["Rule Engine\ntrigger · camera filter\ntime window · cooldown"]
    RE -->|"match"| OB["Outbox\n(DB table)\nstatus: pending"]
    OB --> WP["Worker Pool"]
    WP --> C1["In-app inbox (DB)"]
    WP --> C2["Web Push"]
    WP --> C3["Email SMTP"]
    WP --> C4["Webhook"]
    WP --> C5["Telegram BYO"]
```

**Outbox schema (key fields):**

| Column | Purpose |
|--------|---------|
| `id` | UUID |
| `event_id` | FK to events |
| `channel_id` | FK to notification_channels |
| `status` | `pending`, `sent`, `failed` |
| `attempts` | retry counter |
| `last_error` | last failure message (shown in UI) |
| `next_attempt_at` | backoff timestamp |

**Retry schedule:** 30 s → 2 min → 10 min → 30 min → mark failed; the last error is shown on the Alerts page.

**Channel interface:**

```python
class NotificationChannel(ABC):
    type: ClassVar[str]
    def send(self, notification: Notification) -> None:
        ...  # raise on failure to trigger retry
```

---

### 3.6 Web Application

**Stack (implemented):** Flask + Jinja2 templates + plain CSS/JS, served by `waitress`
(`run.py`). No HTMX, Alpine.js, Tailwind or FastAPI in the current tree — earlier drafts
of this document described them as a target; they are not in use.

**Auth:** first-run setup wizard (no default password), argon2id password hash, session cookie (`HttpOnly`, `SameSite=Lax`, `Secure` on HTTPS), CSRF token on all state-changing requests, login rate-limit and lockout.

**Bind default:** `127.0.0.1`. LAN access requires an explicit opt-in toggle with a warning.

The HTTP surface is server-rendered HTML forms plus a few JSON/streaming endpoints.
There is no `/api/v1` JSON CRUD API. See [API_REFERENCE.md](API_REFERENCE.md) §1 for the
complete, implemented route table (auth, dashboard, cameras, people, unknown faces,
events, alerts, notifications, push, snapshots, admin, health).

---

## 4. Data Flow Summary

See [DATA_FLOW.md](DATA_FLOW.md) for detailed sequence diagrams. At a glance:

```
Camera frame
  → motion gate (drop if no motion)
  → face detector on motion frames (extract crops)
  → embedder (512-float vectors)
  → FaceIndex.best() → (name, score)
  → Event published to bus
  → [*] subscriber persists to DB
  → Rule engine evaluates
  → Outbox row inserted
  → Channel worker delivers
  → dashboard picks it up on its next /api/events poll
```

---

## 5. Database Schema (target)

See [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) for the full entity-relationship diagram and migration strategy.

**Tables (implemented):** `users`, `cameras`, `people`, `face_embeddings`, `unknown_faces`, `events`, `detections`, `snapshots`, `notification_channels`, `notification_rules`, `notification_outbox`, `notifications`, `push_subscriptions`, `settings`, `audit_log`.

**Key design choices:**
- SQLite in WAL mode at `DATABASE_PATH` (default `data/database/sentinel.db`).
- One `sqlite3` connection per web request or per worker thread; never shared across threads.
- Migrations are the ordered statement lists in `src/database/schema.py`, applied at startup and tracked with `PRAGMA user_version`. There is **no Alembic** and no automatic backup before a migration; `src/security/store.py` additionally adds missing auth columns in place so older installs keep working.
- `model_id` on every embedding row; vectors from different models are incomparable.
- The `license` table belongs to the deferred licensing plan and is not created.

---

## 6. Secret and Credential Storage

| Secret type | Storage | Mechanism |
|-------------|---------|-----------|
| Admin password | DB `users.password_hash` | argon2id |
| `SECRET_KEY` (session signing + encryption) | `.env` | Never in DB |
| Camera RTSP URLs with passwords | DB `cameras.source_enc` | Fernet via `SENTINEL_ENCRYPTION_KEYS` (the first key encrypts, older keys decrypt) |
| Notification channel credentials | DB `notification_channels.config_enc` | Same key set |
| Telegram bot token | `.env` or encrypted DB field | Never hardcoded |
| Licence signing key | Offline / password manager | Ed25519; public key embedded in app binary |

---

## 7. Concurrency Model

| Component | Thread/process model |
|-----------|---------------------|
| Web server | `waitress` WSGI, 8 threads (`run.py`; Flask dev server only as fallback) |
| Camera readers | 1 OS thread per camera (I/O bound) |
| Inference worker | 1–2 threads (ONNX Runtime releases GIL) |
| Notification workers | Small thread pool (5–10 workers) |
| SQLite | WAL mode; one short-lived connection per operation per thread |
| Engine lifecycle | `SentinelEngine()` created at import of `src/main.py`; models load on Start, controlled from the dashboard |

---

## 8. Error Handling and Resilience

| Failure | Behaviour |
|---------|-----------|
| Camera offline / bad frame | Worker enters `RECONNECTING`; exponential backoff; camera tile turns red; optional "camera offline" notification after N minutes |
| Model fails to load | Engine refuses to start; web app stays up; error shown in UI |
| Notification channel down | Outbox retries with backoff; failure reason visible in UI; other channels unaffected |
| Disk nearly full | Retention sweeper runs early; warning banner; stop saving snapshots below the free-space floor |
| Process crash / reboot | systemd / Docker `restart: unless-stopped` / Windows service; engine resumes from DB config |
| DB migration fails | Startup fails with the exception in the log; restore the last manual backup (migrations are not auto-backed up) |
| Subscriber exception | Caught inside `EventBus.publish`; logged; other subscribers still run |

---

## 9. Repository Layout (actual)

```
Project-Sentinel/
├── run.py                     # entry point: validate config -> create_app -> waitress
├── pyproject.toml             # dependencies, pytest/ruff config
├── .env.example
├── src/
│   ├── dashboard/             # Flask app factory, page routes, streaming, templates, static
│   ├── security/              # config, auth, CSRF, sessions, password hashing, crypto, validators
│   ├── admin/                 # /admin blueprint (same session/users as the dashboard)
│   ├── camera/                # camera interface, OpenCV/USB/file sources, worker threads
│   ├── engine/                # engine loop, per-camera analyzer, cooldowns
│   ├── motion/                # frame-difference motion detector, snapshot saver
│   ├── faces/                 # YuNet + SFace backends, FaceIndex, enrolment/unknown service
│   ├── events/                # event model, bus, queued subscribers, manager
│   ├── notifications/         # rules, channels, outbox worker, push, routes
│   ├── database/              # schema migrations, repositories
│   └── config/                # process-wide settings used by engine/scripts
├── tests/                     # pytest suite (hermetic; no camera or network)
├── tools/                     # gen_secrets.py, manage_users.py, security_scan.py
├── scripts/                   # download_models.py, benchmark_faces.py
├── docs/                      # architecture, API, schema, deployment, threat model
├── models/                    # YuNet/SFace ONNX files (git-ignored)
├── data/                      # SQLite database, VAPID key (git-ignored)
└── snapshots/                 # event and face-crop images (git-ignored)
```

Earlier drafts described a `src/sentinel/` FastAPI layout with SQLAlchemy/Alembic and
`licensing/`. That layout was never implemented and has been removed from this document.
