# Requirements: Project Sentinel

> Status of each requirement: **MVP** (must ship in Phase 1–4), **Post-MVP** (Phase 6+), or **Prototype** (exists today, may need fixes).

---

## 1. Functional Requirements

### 1.1 Camera Management

| ID | Requirement | Priority |
|----|-------------|----------|
| CAM-01 | Connect to a USB / built-in webcam by device index | MVP |
| CAM-02 | Connect to an RTSP/IP camera by URL | MVP |
| CAM-03 | Connect to a phone-as-camera HTTP/MJPEG stream | MVP |
| CAM-04 | Use a local video file as a camera source (testing / demo) | MVP |
| CAM-05 | Run multiple cameras concurrently | MVP |
| CAM-06 | Display a live preview of each camera in the dashboard | MVP |
| CAM-07 | Reconnect automatically after a camera goes offline | MVP |
| CAM-08 | Show per-camera connection status (Online / Reconnecting / Error) | MVP |
| CAM-09 | Validate a camera connection (test + preview frame) before saving | MVP |
| CAM-10 | Store camera credentials encrypted; never display the password in plain text | MVP |
| CAM-11 | Support ONVIF auto-discovery | Post-MVP |
| CAM-12 | Support WebRTC browser/phone capture | Post-MVP |

### 1.2 Detection Pipeline

| ID | Requirement | Priority |
|----|-------------|----------|
| DET-01 | Detect motion using frame differencing before running expensive AI | MVP |
| DET-02 | Detect persons in a frame using an ONNX-compatible, permissively licensed model | MVP |
| DET-03 | Detect and locate faces in a person crop | MVP |
| DET-04 | Generate a 128/512-float face embedding for each detected face | MVP |
| DET-05 | Match each embedding against enrolled people (in-memory matrix) | MVP |
| DET-06 | Run face recognition once per frame, not once per detected person | MVP |
| DET-07 | Apply a configurable per-camera, per-identity cooldown to suppress duplicate events | MVP |
| DET-08 | Support a configurable detection FPS cap per camera | MVP |
| DET-09 | Drop frames gracefully when the inference queue is full | MVP |
| DET-10 | Detect objects other than persons (vehicle, package, animal) | Post-MVP |

### 1.3 Face / People Management

| ID | Requirement | Priority |
|----|-------------|----------|
| PEO-01 | Enrol a person with 3–5 photos (upload or capture from camera) | MVP |
| PEO-02 | Enforce enrolment quality checks: single face, confidence ≥ 0.7, face ≥ 80 px, not blurry | MVP |
| PEO-03 | Store multiple embeddings per person with `model_id` and quality score | MVP |
| PEO-04 | Record a consent timestamp when enrolling a person | MVP |
| PEO-05 | List all enrolled people with name, photo count, last seen | MVP |
| PEO-06 | Delete a person: remove all embeddings, photos, and optionally their event history | MVP |
| PEO-07 | Unknown face inbox: save crop and embedding; deduplicate by similarity | MVP |
| PEO-08 | Unknown face inbox: "Name this person" promotes to enrolled person | MVP |
| PEO-09 | Unknown face inbox: "Dismiss" marks crop as reviewed | MVP |
| PEO-10 | Provide a threshold slider (strict / balanced / lenient) translating to cosine score | MVP |
| PEO-11 | Rebuild the in-memory FaceIndex only on enrol/delete, not every frame | MVP |
| PEO-12 | Store enrolment photos only with explicit consent (optional; documented) | MVP |

### 1.4 Events and History

| ID | Requirement | Priority |
|----|-------------|----------|
| EVT-01 | Persist every domain event (type, source, camera, person, snapshot path, timestamp) to SQLite | MVP |
| EVT-02 | Display an events timeline with thumbnails, filterable by camera, person, and type | MVP |
| EVT-03 | Save a snapshot for each relevant event (motion detected with person, unknown face) | MVP |
| EVT-04 | Paginate the event list with cursors | MVP |
| EVT-05 | Auto-delete events and snapshots older than the configured retention period (default 30 days) | MVP |
| EVT-06 | Publish live events via Server-Sent Events (SSE) to open dashboard tabs | MVP |

### 1.5 Notifications

| ID | Requirement | Priority |
|----|-------------|----------|
| NOT-01 | Deliver in-app alerts via SSE with sound | MVP |
| NOT-02 | Deliver Web Push / PWA notifications (VAPID, works while app is in background) | MVP |
| NOT-03 | Deliver email alerts via customer-configured SMTP | MVP |
| NOT-04 | Deliver alerts via configurable webhook (JSON POST) | MVP |
| NOT-05 | Deliver alerts via customer-supplied Telegram bot token | MVP (optional) |
| NOT-06 | Support notification rules: trigger type, camera filter, person filter, time window, cooldown | MVP |
| NOT-07 | Ship 3 default rules so a new install is immediately useful | MVP |
| NOT-08 | Retry failed deliveries with exponential backoff; show failures in UI | MVP |
| NOT-09 | "Send test notification" button per channel | MVP |
| NOT-10 | Optionally attach a snapshot to alerts | MVP |
| NOT-11 | Native mobile push (FCM/APNs) | Post-MVP |
| NOT-12 | SMS delivery | Post-MVP |

### 1.6 Authentication and Administration

| ID | Requirement | Priority |
|----|-------------|----------|
| AUTH-01 | First-run setup wizard creates the admin account; no default credentials | MVP |
| AUTH-02 | Login with username/password; session cookie authentication | MVP |
| AUTH-03 | Roles: `admin` (full access), `viewer` (read-only; no settings, face management) | MVP |
| AUTH-04 | "Change password" and "log out everywhere" | MVP |
| AUTH-05 | Password reset via CLI command (`sentinel reset-password`) | MVP |
| AUTH-06 | Audit log: logins, failed logins, face enrol/delete, camera add/remove, settings changes | MVP |
| AUTH-07 | "Download diagnostics" bundle with secrets stripped | MVP |

### 1.7 Privacy and Data Management

| ID | Requirement | Priority |
|----|-------------|----------|
| PRV-01 | Retention sweeper: auto-delete events and snapshots past the retention window | MVP |
| PRV-02 | "Delete all data" action clears all events, snapshots, and face data | MVP |
| PRV-03 | "Export my data" produces a downloadable archive of events and face records | MVP |
| PRV-04 | Consent flag and timestamp stored for each enrolled person | MVP |
| PRV-05 | Settings screen: configure retention period, snapshot retention per category | MVP |
| PRV-06 | Printable consent notice template for displaying to monitored persons | MVP |

### 1.8 Packaging and Licensing

| ID | Requirement | Priority |
|----|-------------|----------|
| PKG-01 | Docker image (`docker-compose up`) installs and starts the application | MVP |
| PKG-02 | Windows installer with bundled Python runtime, runs as a background service | MVP |
| PKG-03 | Licence key enforces tier limits (cameras, people) and expiry | MVP |
| PKG-04 | Licence verification works offline (Ed25519 signature against embedded public key) | MVP |

---

## 2. Non-Functional Requirements

### 2.1 Performance

| ID | Requirement | Measurement method |
|----|-------------|-------------------|
| PER-01 | Person at camera → alert delivered to phone in < 5 s on a modern laptop CPU (no GPU) | Measured end-to-end in `scripts/benchmark.py` |
| PER-02 | 4 cameras at 3 fps detection each on an Intel N100-class mini-PC | `benchmark.py` on the reference machine |
| PER-03 | FaceIndex match for 500 enrolled people in < 5 ms | Unit benchmark |
| PER-04 | Dashboard page load < 2 s on localhost | Browser DevTools / Lighthouse |
| PER-05 | Motion gate processes one frame in < 10 ms | `benchmark.py` |

### 2.2 Reliability

| ID | Requirement |
|----|-------------|
| REL-01 | Camera worker reconnects without engine restart after a camera goes offline |
| REL-02 | A failing notification channel does not affect detection, other channels, or in-app alerts |
| REL-03 | Queued notifications are delivered after a network outage ends |
| REL-04 | The engine survives a process restart (systemd / Docker restart policy) and resumes from DB config |
| REL-05 | A DB migration failure leaves the database untouched and shows a clear error |
| REL-06 | Crash-free sessions > 99% over a 24-hour continuous run with 2+ cameras |

### 2.3 Security

| ID | Requirement |
|----|-------------|
| SEC-01 | No default credentials anywhere in the application |
| SEC-02 | All routes except `/setup`, `/login` and the public liveness probes require an authenticated session |
| SEC-03 | CSRF token on every state-changing request |
| SEC-04 | Dashboard binds to `127.0.0.1` by default |
| SEC-05 | Passwords hashed with argon2id; never stored in plain text |
| SEC-06 | Camera URLs and channel credentials encrypted at rest (Fernet) |
| SEC-07 | No `pickle`; no dynamic SQL string building |
| SEC-08 | Secrets never appear in logs, diagnostics bundles, or the UI |
| SEC-09 | `pip-audit` and `bandit` produce no high or critical findings at release |

### 2.4 Usability

| ID | Requirement |
|----|-------------|
| UX-01 | A non-developer completes setup and receives a first real alert in < 15 minutes |
| UX-02 | Every empty state tells the user what to do next |
| UX-03 | Every error shows what failed and what to try |
| UX-04 | The dashboard is usable on a phone (responsive layout) |
| UX-05 | Dark mode and adequate colour contrast (WCAG AA minimum) |
| UX-06 | Keyboard-navigable UI |

### 2.5 Maintainability

| ID | Requirement |
|----|-------------|
| MNT-01 | A solo developer can understand and change any module in an afternoon |
| MNT-02 | `ruff check` and `ruff format` produce no warnings on the full codebase |
| MNT-03 | Test coverage > 80% on `pipeline/`, `faces/`, `events/`, `notifications/` |
| MNT-04 | Every schema change has a corresponding Alembic revision |
| MNT-05 | `THIRD_PARTY_LICENSES.md` is generated and kept current |

### 2.6 Privacy

| ID | Requirement |
|----|-------------|
| PRI-01 | No video, snapshot, or face data leaves the customer's machine without an explicit opt-in |
| PRI-02 | No analytics or telemetry collected without explicit opt-in |
| PRI-03 | Retention is enforced by default (default 30 days) |
| PRI-04 | Face data classified as biometric; consent tracked per person |
