# Data Flow: Project Sentinel

> This document traces data from camera capture through detection, persistence, and notification delivery, and from user interaction back through the system. Use it alongside [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Camera Input and Frame Lifecycle

```mermaid
sequenceDiagram
    participant HW as Camera Hardware
    participant CW as CameraWorker (thread)
    participant FS as Frame Slot
    participant SC as Scheduler

    loop Read continuously
        CW->>HW: read()
        HW-->>CW: raw frame bytes
        CW->>CW: wrap in Frame(id, ts, source, data)
        CW->>FS: overwrite latest frame
    end

    loop Every 1/detection_fps seconds
        SC->>FS: take latest frame
        FS-->>SC: Frame
        SC->>SC: enqueue for pipeline
    end
```

**Key properties:**
- The CameraWorker thread reads at the camera's native FPS (e.g. 25 fps).
- The scheduler samples at `detection_fps` (default 3 fps) to keep CPU usage bounded.
- If the pipeline queue is full, the frame is dropped — no memory growth.
- Each `Frame` carries a UUID, UTC timestamp, camera source identifier, and the raw NumPy array.

---

## 2. Detection Pipeline

```mermaid
flowchart TD
    F[Frame from Scheduler] --> MG{Motion gate\nframe diff > threshold?}
    MG -- No motion --> DISC[Discard frame]
    MG -- Motion detected --> PD[Person Detector\nONNX inference]
    PD -- No persons --> EVT_M[Publish MOTION_DETECTED\nif motion cooldown allows]
    PD -- Person crops --> FD[Face Detector\nper crop]
    FD -- No faces in crop --> EVT_P[Publish PERSON_DETECTED]
    FD -- Face bounding boxes --> EMB[Embedder\n512-float vector]
    EMB --> FI[FaceIndex.best\ncosine similarity]
    FI -- score >= threshold --> EVT_K[Publish FACE_RECOGNIZED\nname, confidence]
    FI -- score < threshold --> EVT_U[Publish UNKNOWN_PERSON\nsave crop to unknown_faces]
    EVT_M & EVT_P & EVT_K & EVT_U --> EB[Event Bus]
```

**Notes:**
- The motion gate maintains its own previous-frame state per camera instance.
- Face detection and embedding run once across all person crops in a frame, not once per crop.
- Per-camera, per-identity cooldown suppresses repeated `FACE_RECOGNIZED` events for the same person within the cooldown window.
- Snapshots are saved to disk for `MOTION_DETECTED` with a person present and for `UNKNOWN_PERSON`.

---

## 3. Event Processing and Persistence

```mermaid
sequenceDiagram
    participant P as Pipeline
    participant EB as EventBus
    participant ES as EventStore (DB)
    participant RE as Rule Engine
    participant OB as Outbox (DB)

    P->>EB: publish(event)
    EB->>ES: "* " subscriber: INSERT INTO events
    EB->>RE: notification subscriber
    RE->>RE: evaluate rules (trigger, camera, time window, cooldown)
    RE->>OB: INSERT notification row (status=pending)
```

- `EventBus.publish` calls each subscriber in `try/except`; a failure in one subscriber does not affect others.
- The `"*"` subscriber persists every event regardless of type.
- The rule engine evaluates synchronously but only inserts a DB row; actual delivery is asynchronous.
- The event bus does not push to browsers. The notification inbox has an SSE endpoint
  (`/api/notifications/stream`) that tails the inbox table; the current UI does not open it
  and instead polls `/api/status` every 2 s for the engine badge.

---

## 4. Notification Delivery

```mermaid
sequenceDiagram
    participant OB as Outbox
    participant W as Notification Worker
    participant CH as Channel (e.g. Email)
    participant DB as Database

    loop Worker poll (every 5 s)
        W->>DB: SELECT pending rows WHERE next_attempt_at <= now()
        DB-->>W: rows[]
        loop each row
            W->>CH: channel.send(notification)
            alt success
                W->>DB: UPDATE status=sent
            else failure
                W->>DB: UPDATE status=pending, attempts++, last_error, next_attempt_at=backoff
            end
        end
    end
```

**Retry schedule:** 1 m → 5 m → 30 m → 2 h → permanent failure. Permanent failures are visible in the notification settings UI with the last error message.

**Channels run independently.** A failing email channel does not delay or block Telegram delivery.

---

## 5. User Interaction: Enrolment

```mermaid
sequenceDiagram
    actor User
    participant UI as Dashboard (browser)
    participant API as Flask POST /people
    participant FE as Face Enrolment Service
    participant FI as FaceIndex
    participant DB as Database

    User->>UI: upload 3–5 photos + name + consent checkbox
    UI->>API: POST /people (multipart)
    API->>FE: enrol(name, photos, consent=True)
    loop each photo
        FE->>FE: quality check (1 face, confidence, size, blur)
        alt quality fail
            FE-->>API: 422 { reason: "No face detected" }
            API-->>UI: show rejection reason
        else pass
            FE->>FE: detect face → embed → store
        end
    end
    FE->>DB: INSERT people, INSERT face_embeddings (N rows)
    FE->>FI: rebuild FaceIndex
    API-->>UI: 201 { person_id, photo_count }
    UI->>UI: show person in people list
```

---

## 6. User Interaction: Unknown Face Promotion

```mermaid
sequenceDiagram
    actor User
    participant UI as Dashboard
    participant API as Flask POST /unknown/<id>/name
    participant FE as Face Enrolment Service
    participant FI as FaceIndex
    participant DB as Database

    User->>UI: open Unknown Faces inbox
    UI->>API: GET /api/unknown-faces
    API-->>UI: list of crops with thumbnails

    User->>UI: "Name this person" → type name → submit
    UI->>API: POST /api/unknown-faces/{id}/promote { name, consent }
    API->>FE: promote(unknown_face_id, name, consent)
    FE->>DB: INSERT people, INSERT face_embeddings (from unknown_faces.vector)
    FE->>DB: UPDATE unknown_faces SET status=promoted
    FE->>FI: rebuild FaceIndex
    API-->>UI: 200
    UI->>UI: move face to People list; remove from inbox
```

---

## 7. Database Persistence Summary

| Data type | Table | Retained | Deleted by |
|-----------|-------|----------|-----------|
| Domain events | `events` | Retention period (default 30 d) | Nightly sweeper |
| Snapshots (file + DB row) | `events.snapshot_path` + file | Retention period | Nightly sweeper |
| Person records | `people` | Until explicit delete | User action |
| Face embeddings | `face_embeddings` | Until person deleted | User action / "Delete person" |
| Unknown face crops | `unknown_faces` | Shorter retention (default 7 d) or until promoted/dismissed | Nightly sweeper + user action |
| Notification outbox | `notification_outbox` | Until delivered or max retries | Worker on delivery / failure |
| Audit log | `audit_log` | Longer retention (default 90 d) | Nightly sweeper |

---

## 8. Live Dashboard Data Flow

```mermaid
flowchart LR
    DB[("events / notifications
tables")] -->|SSE tail| CONN["/api/notifications/stream"]
    API["/api/status poll
every 2 s"] --> BROWSER[Browser]
    BROWSER -->|fetch + textContent| STATUS["Engine status badge"]
    CONN -.->|available, not used by the
current UI| BROWSER
```

The shipped JavaScript (`static/js/app.js`) polls `/api/status` every two seconds and updates
the engine badge with `textContent` (never `innerHTML`). Event lists are rendered
server-side on page load and after a form post. `/api/notifications/stream` streams inbox
rows as Server-Sent Events for a client that chooses to use it; nothing in the current
templates opens an `EventSource`.

## 9. Data Leaving the Machine

By default, **no data leaves the customer's machine**. The only outbound traffic is:

| Destination | When | What |
|-------------|------|------|
| Customer's SMTP server | Notification delivery | Alert text + optional snapshot |
| Push notification relay (browser vendors) | Web Push delivery | End-to-end encrypted payload (event type + text; no snapshot) |
| Customer's webhook URL | Notification delivery | Configured JSON payload |
| Customer's Telegram bot API | Notification delivery | Alert text + optional photo |
| Licence verification endpoint (future) | On licence check | Licence key signature; no biometric data |

Telemetry: **none** by default. Any future opt-in analytics will document every field sent.
