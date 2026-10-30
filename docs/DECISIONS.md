# Architecture Decision Records

Format: Context → Decision → Options → Consequences → Action items.
Status values: **Proposed** (needs your sign-off) · **Accepted** · **Gate** (decided by a measurement in the roadmap).
Deciders: you (product owner + only developer).

| ADR | Decision | Status |
|-----|----------|--------|
| 001 | Local-first self-hosted product; cloud relay later as paid add-on | Proposed |
| 002 | Keep Flask for the MVP (FastAPI deferred) | **Accepted** (changed 2026-10-30) |
| 003 | SQLite (WAL) + small versioned migrations (SQLAlchemy/Alembic deferred) | **Accepted** (changed 2026-10-30) |
| 004 | Replace `buffalo_l` and YOLOv8 with commercially-licensable models | **Gate** (Week 5) |
| 005 | Notification channels + rules + outbox; Telegram becomes bring-your-own | Proposed |
| 006 | Camera ingestion via OpenCV/FFmpeg with reader threads (revisit later) | Proposed |
| 007 | Server-rendered UI (Jinja2 + HTMX + Alpine + Tailwind) | Proposed |
| 008 | Docker first, Windows installer second; offline-verifiable signed licence keys | Proposed |

---

## ADR-001: Local-first, self-hosted product

**Status:** Proposed

### Context
You want to sell this online. Video analytics is compute- and bandwidth-heavy, and face data is legally sensitive.

### Decision
Sell software that runs on the customer's own machine. Video and face data stay there. Optionally add a paid **cloud relay** later (remote access, push when away).

### Options Considered

| | A. Local-first | B. Cloud SaaS | C. Hybrid (A + relay) |
|---|---|---|---|
| Complexity | Medium | High | High |
| Your running cost | ~0 | Per camera per month (bandwidth + GPU/CPU) | Low (relay only) |
| Privacy / legal exposure | Customer holds their own data | You become a biometric-data processor | Mostly customer; relay carries only encrypted alerts |
| Time to first sale | Fastest | Slowest | Medium |
| Recurring revenue | Weak (licence/updates) | Strong | Medium–strong |
| Support burden | Install/hardware issues | Uptime | Both |

**Trade-off:** you give up easy recurring revenue and take on installation support in exchange for near-zero marginal cost and a clean privacy story. Frigate and Viseron prove people will self-host, but also that the free alternatives are good, so *ease of install* has to be your edge (see business doc).

### Consequences
- Easier: privacy claims, cost structure, solo operation.
- Harder: onboarding (hardware varies), updates, licence enforcement, remote access.
- Revisit: when >20% of support requests are "how do I view this away from home" → build the relay.

### Action items
1. [ ] Interview ~10 target users about where they'd run it (old laptop? mini-PC? NAS?).
2. [ ] Decide the "supported hardware" statement for v1.

---

## ADR-002: Keep Flask for the MVP (FastAPI deferred)

**Status:** Accepted (2026-10-30). **Supersedes the original recommendation to move to FastAPI.**

> **Update:** Time-to-market matters more than the small technical edge FastAPI offers. You already know Flask, it is installed, and everything the MVP needs (login, CSRF, MJPEG video, server-sent events) works on Flask with a threaded server. Werkzeug's built-in password hashing means no extra auth packages. Revisit only if we hit a concrete limit (e.g. many simultaneous live streams). The original analysis is kept below for reference.

### Context
Current dashboard is Flask with full-page form posts, polling every second, and no real-time channel. The product needs JSON APIs, live events (SSE), MJPEG streaming, input validation, and auto-generated API docs.

### Options Considered

| | Flask (keep) | FastAPI |
|---|---|---|
| Learning cost for you | None (you know it) | Low–medium (similar decorators) |
| Async / SSE / streaming | Possible, clunkier | First-class |
| Request validation | Manual / add-ons | Built in (Pydantic) |
| Auto API docs | Add-on | Built in |
| Ecosystem for auth/CSRF/templates | Mature | Mature enough (Starlette) |

### Decision
FastAPI + Jinja2 templates + Uvicorn. Flask is *viable*; this is a "slightly better fit, small switch cost" call, and the switch is cheap *now* while the dashboard is ~100 lines.

### Consequences
- Easier: live updates, typed endpoints, tests (`TestClient`), docs.
- Harder: you must learn `async`/`await` basics. Rule: keep CPU-heavy code in plain threads, not in `async def` handlers.
- Revisit: never, unless you hit a concrete limitation.

### Action items
1. [ ] Work through the official FastAPI tutorial through "Security" and "Background Tasks".
2. [ ] Port `/` and `/api/status` first as the vertical slice.

---

## ADR-003: SQLite (WAL) + small versioned migrations

**Status:** Accepted (2026-10-30). **Changed: SQLAlchemy + Alembic deferred.**

> **Update:** `src/database/schema.py` holds an ordered list of migrations. The database stores how many have run (`PRAGMA user_version`), so customers' databases upgrade in place. Rule: never edit an old migration; append a new one. This avoids learning an ORM now. Move to SQLAlchemy + Alembic if/when the schema or queries outgrow plain SQL. Original analysis kept below.

### Context
Currently two SQLite files, raw SQL strings, a migration file that doesn't compile, and connections shared across threads.

### Options Considered

| | Raw sqlite3 (current) | SQLAlchemy + Alembic on SQLite | Postgres |
|---|---|---|---|
| Install burden for customer | none | none | high (another service) |
| Schema upgrades for paying customers | manual | **Alembic migrations** | Alembic |
| Concurrency | fragile | OK with WAL + per-thread sessions | excellent |
| Future cloud/multi-site | rewrite | swap driver | native |

### Decision
SQLite in WAL mode via SQLAlchemy 2.x, with Alembic migrations from day one. One DB file in a single `data/` directory (easy backup).

### Consequences
- Easier: zero-install, one-file backup, safe upgrades.
- Harder: ORM learning curve; heavy concurrent writes (many cameras) need short transactions.
- Revisit: when adding multi-site/cloud; the ORM makes the move to Postgres mostly a config change.

### Action items
1. [ ] Delete `schema.py`, `initializer.py`, `migration.py`, `repository.py`, duplicate repos.
2. [ ] Create models for the tables in `ARCHITECTURE.md` §5; generate the first Alembic revision.
3. [ ] Add a "backup DB before migrate" step.

---

## ADR-004: Replace non-commercial / AGPL AI components

**Status:** **Gate**, decided by a benchmark in Week 5

### Context
- InsightFace's **code** is MIT, but its pretrained model packs (`buffalo_l`, `buffalo_s`, `antelopev2`) are **non-commercial research only**. Your `FaceDetector` loads `buffalo_l`.
- Ultralytics YOLOv8 code **and** weights are **AGPL-3.0**; using them in a commercial/closed-source product requires an Ultralytics **Enterprise License** (or open-sourcing the whole product under AGPL-3.0).
- Both facts checked against upstream license statements on 2026-10-29. **Re-read the current license files and get legal advice before you launch.**

### Options Considered

**Faces**

| Option | Licence | Notes |
|--------|---------|-------|
| A. Keep `buffalo_l` | Non-commercial | ❌ Cannot sell |
| B. **YuNet (detector) + SFace (recogniser)** via OpenCV | MIT / Apache-2.0 | Small (~40 MB), fast on CPU, runs through plain OpenCV; lower accuracy than ArcFace-R50 |
| C. **AuraFace** (permissive ArcFace-class recogniser) + YuNet detector | Apache-2.0 / MIT | Reported accuracy near buffalo_l on benchmarks; heavier (R100). Verify the exact model card |
| D. Negotiate a commercial licence with InsightFace | Paid | Best accuracy, cost/legal overhead |

**Objects/persons**

| Option | Licence | Notes |
|--------|---------|-------|
| A. Keep YOLOv8 | AGPL-3.0 | Needs Enterprise License or AGPL product |
| B. Ultralytics Enterprise License | Paid | Zero code change; ongoing cost |
| C. **Permissively licensed detector** (e.g. YOLOX, or an Apache-2.0 RT-DETR/SSD-MobileNet checkpoint) exported to ONNX | Apache-2.0 (verify per checkpoint) | More integration work; also removes the multi-GB PyTorch dependency, since ONNX Runtime alone is enough |
| D. Open-source the product under AGPL | AGPL | Allowed, but changes the business model (support/hosting/hardware revenue) |

### Decision (provisional)
Build a thin `Detector` / `FaceRecognizer` interface so models are swappable. Start with **YuNet + SFace** and a **permissive ONNX person detector**. In Week 5, run `scripts/benchmark.py` on your own ~50-photo test set (your family/friends, with consent) and compare accuracy + speed with C. If accuracy is unacceptable, escalate to AuraFace or a paid licence. **Do not launch with A.**

### Consequences
- Easier: legal clarity, smaller install, no PyTorch.
- Harder: you must evaluate accuracy yourself; all existing embeddings become invalid → re-enrol (acceptable at prototype stage; `model_id` column prevents silent mixing in future).
- Revisit: each time you change models, and whenever a customer reports false matches.

### Action items
1. [ ] Wrap current code behind interfaces (Phase 1).
2. [ ] Collect a consented test set; write `benchmark.py` (Phase 2).
3. [ ] Record the chosen models + licence texts in `THIRD_PARTY_LICENSES.md` shipped with the app.
4. [ ] Run `pip-licenses` on the final environment; investigate anything GPL/AGPL/NC.

---

## ADR-005: Notifications: channels + rules + outbox

**Status:** Proposed

### Context
`NotificationManager.notify` is synchronous, Telegram-only, crashes the engine on network errors, ignores snapshots, and uses a hardcoded token and chat ID. A product can't depend on one third-party app that every customer must configure with *your* bot.

### Options Considered

| | A. Telegram only | B. Build everything native (mobile app) | C. **Pluggable channels + outbox** |
|---|---|---|---|
| Time | Done | Months | ~2 weeks for 4 channels |
| Customer friction | Needs Telegram + your bot | App store, accounts | Choose any channel |
| Reliability | Poor today | n/a | Retries, visible failures |
| Cost | none | high | none |

### Decision
Channel plug-in interface; rules engine (trigger, camera, time window, cooldown, snapshot); DB-backed outbox with retrying workers. MVP channels: in-app (SSE), Web Push (PWA + VAPID), email (SMTP), webhook, and Telegram where the **customer** supplies their own bot token.

### Consequences
- Easier: adding Discord/Slack/SMS later is one small class; delivery failures become visible.
- Harder: Web Push needs HTTPS (`localhost` is exempt) and iOS only supports it for PWAs installed to the Home Screen. Document this clearly.
- Revisit: once users ask for alerts while away from home → cloud relay (ADR-001).

### Action items
1. [ ] Define `Notification`, `NotificationChannel`, rule schema.
2. [ ] Implement in-app → webhook → email → Web Push → Telegram, in that order.
3. [ ] "Send test notification" button per channel.

---

## ADR-006: Camera ingestion method

**Status:** Proposed (revisit if CPU/latency is poor)

### Options Considered

| | A. `cv2.VideoCapture` + reader thread | B. FFmpeg subprocess piping raw frames | C. go2rtc/MediaMTX sidecar restream |
|---|---|---|---|
| Complexity | Low | Medium | Medium–high (extra binary) |
| Supports USB/RTSP/HTTP/file | Yes | RTSP/HTTP/file (USB needs OS-specific input flags) | Mostly network streams |
| Hardware decode | Limited | Yes (flags) | Yes |
| Multi-consumer (detector + live view) | You fan out frames yourself | You fan out | Native |

### Decision
Start with A, with the four reliability rules in `ARCHITECTURE.md` §4.1. Write the `CameraSource` interface so B or C can replace it without touching the pipeline.

### Consequences
- Easier: one code path, works on Windows/macOS/Linux with pip-installed OpenCV.
- Harder: RTSP edge cases (H.265 on some builds, auth quirks), no hardware decode.
- Revisit: if 4 × 1080p cameras can't hold target FPS on your reference hardware.

### Action items
1. [ ] Build `OpenCVSource` + `CameraWorker` + `FakeCamera` (looping video) for tests.
2. [ ] Test against at least three real camera models/apps (webcam, phone app, one RTSP camera).

---

## ADR-007: Server-rendered UI with HTMX

**Status:** Proposed

### Options Considered

| | Jinja2 + HTMX + Alpine + Tailwind | React/Vite SPA | Desktop wrapper (Electron/Tauri) |
|---|---|---|---|
| Learning cost | Low | High (build tooling, state mgmt) | High |
| Time to polished UI | Short | Longer | Longer |
| Live updates | SSE + HTMX swaps | Any | Any |
| Mobile access | Same site, responsive | Same | Separate packaging |
| Future native shell | Can wrap later | Can wrap later | Built-in |

### Decision
Server-rendered pages with HTMX/Alpine; Tailwind for design consistency. A solo developer ships faster, and the dashboard is forms, tables, and live tiles, not a rich client app.

### Consequences
- Easier: one language, no JS build pipeline for customers or you.
- Harder: very rich interactions (e.g. drawing detection zones on video) need a bit of custom JS.
- Revisit: when the UI needs complex client state (zone editors, timeline scrubbing).

### Action items
1. [ ] Design 6 screens on paper/Figma first: Setup wizard, Dashboard, Cameras, People, Events, Settings. (Phase 4, but sketch early.)

---

## ADR-008: Packaging and licence keys

**Status:** Proposed

### Context
Customers are not developers. They need "download, run, done."

### Decision
1. **Docker image + `docker-compose.yml`** first (one command on Linux/NAS/mini-PC; also Docker Desktop on Windows/macOS). USB webcams are awkward inside Docker on Windows/macOS, so also provide:
2. **Windows installer** (bundled Python runtime, runs as a background service/tray app) as the second deliverable. This is where most non-technical buyers will be.
3. **Licence key:** a signed token (Ed25519) generated by you after purchase, containing tier, limits (cameras/people), expiry, and optionally a machine ID. The app verifies the signature **offline** using a public key embedded in the app. No licence server is needed for v1. A "licence server" or activation API can come later.
4. Payments through a **merchant of record** (Paddle / Lemon Squeezy-type service) so sales tax/VAT handling is theirs, not yours. Check payout support for your country.

### Consequences
- Easier: no server to run, works offline, honest customers pay.
- Harder: offline checks can be bypassed by determined users. That is acceptable at MVP; don't spend engineering time on DRM.
- Revisit: when piracy or seat-sharing measurably costs revenue.

### Action items
1. [ ] Dockerfile + compose file + healthcheck (Phase 5).
2. [ ] Spike Windows packaging early (Phase 3) because it's the riskiest unknown.
3. [ ] Implement `licensing/` verify function + admin script to issue keys.
