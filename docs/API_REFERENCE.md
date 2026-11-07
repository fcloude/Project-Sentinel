# API Reference: Project Sentinel

> **Status:** §1 and §2 describe the shipped application (server-rendered Flask
> dashboard driven by HTML forms). Sections from *4. Cameras* onward are a **design
> target**: that JSON API does **not exist yet**; do not build against it.

---

## 1. Implemented HTTP surface

Routes are registered by `src/dashboard/routes.py`, `src/notifications/routes.py` and
`src/admin/routes.py`, and protected by the single default-deny hook in
`src/security/auth.py`. There is no `/api/v1` prefix and no JSON CRUD API: pages post
forms and redirect.

| Area | Routes |
|------|--------|
| Auth | `GET,POST /login`, `POST /logout`, `GET,POST /setup`, `GET,POST /account/password` |
| Dashboard | `GET /`, `POST /engine/<start\|stop\|restart>`, legacy `POST /start`, `/stop`, `/restart` |
| Cameras | `GET,POST /cameras`, `POST /cameras/<id>/delete`, `GET /cameras/<id>/stream.mjpg`, `POST /api/cameras/test` |
| People | `GET,POST /people`, `POST /people/<id>/photos`, `POST /people/<id>/delete` |
| Faces | `GET /faces`, `POST /faces/reindex` |
| Unknown inbox | `GET /unknown`, `GET /unknown/<id>/crop.jpg`, `POST /unknown/<id>/name`, `POST /unknown/<id>/dismiss` |
| Events | `GET /events` |
| Settings | `GET,POST /settings` |
| Alerts | `GET /alerts`, `POST /alerts/rules`, `POST /alerts/rules/<id>/toggle`, `POST /alerts/rules/<id>/delete`, `POST /alerts/channels`, `POST /alerts/channels/<id>/test`, `POST /alerts/channels/<id>/toggle`, `POST /alerts/channels/<id>/delete`, `POST /alerts/push-contact` |
| Notifications | `GET /notifications`, `POST /notifications/read`, `GET /notifications/<id>/snapshot.jpg`, `GET /api/notifications/unread`, `GET /api/notifications/stream` |
| Push | `GET /api/push/public-key`, `POST /api/push/subscribe` |
| Media | `GET /snapshots/<name>` (filename allow-list, never a static file) |
| Admin | `GET /admin/`, `/admin/events`, `/admin/devices`, `/admin/unknown-faces`, `/admin/audit`, `/admin/admins`, `/admin/admins/create`, `/admin/config`, `POST /admin/admins/<id>/toggle`, `POST /admin/admins/<id>/delete` |
| Ops | `GET /healthz`, `GET /api/health` (public liveness), `GET /api/status` (JSON, login required), `GET /manifest.webmanifest`, `GET /sw.js` |

**Access rule.** Every endpoint requires a signed-in session except: the login and setup
pages, static files, `/healthz`, `/api/health`, `/manifest.webmanifest` and `/sw.js`.
Every non-`GET` request additionally requires the `admin` role, except logout and
password change (self-service, any role) and the login/setup forms themselves.

---

## 2. Conventions (as implemented)

### Session cookie
```
sentinel_session=<signed value>; HttpOnly; Path=/; SameSite=Lax[; Secure]
```
With `SENTINEL_HTTPS=true` the name is `__Host-sentinel_session` and `Secure` is set. Idle
timeout `SESSION_IDLE_MINUTES` (default 30), absolute timeout `SESSION_ABSOLUTE_HOURS`
(default 12). Unauthenticated HTML requests get `302 -> /login?next=...`; `/api/*`
requests get `401 {"error": "authentication required"}`.

### CSRF
A per-session token, sent either as the form field `csrf_token` or the header
`X-CSRF-Token`. Pages expose it as `<meta name="csrf-token">`. There is **no**
`GET /api/csrf` endpoint and the field is **not** named `_csrf_token`. Every
non-`GET/HEAD/OPTIONS` request must supply it, and a present `Origin` header must match
the request authority (scheme + host + port, with default ports and case normalized) or
a configured `SENTINEL_TRUSTED_ORIGINS` entry. `localhost`, `127.0.0.1` and `::1` are
the same authority when the scheme and port match. Rejections are `403`; the reason
(`bad_origin`, `no_session`, `missing_token`, `mismatch`) plus the observed `origin` and
`host` is logged and written to `audit_log` as `csrf_denied`, and login/setup re-render
the form with a fresh token. A login `403` therefore means the form was submitted
without a session cookie, with a token from an older session, or from a different
address — not that the password was wrong.

### Error responses
`/api/*` returns `{"error": "<short message>"}`; everything else returns the HTML error
page. No `Access-Control-*` header is ever emitted.

| Status | Meaning |
|--------|---------|
| 400 | Validation failure |
| 401 | Not authenticated (`/api/*`) / bad credentials on login |
| 403 | CSRF rejection, or a viewer/session lacking permission |
| 404 | Not found (also `/setup` once a user exists) |
| 405 | Method not allowed |
| 413 | Body larger than `MAX_UPLOAD_MB` |
| 429 | Login throttled: `Retry-After` header set |
| 500 | Internal error (details only in the server log) |

### Login throttling
5 failures per (IP, username) or 20 per IP within 15 minutes, in process memory.

---

## 3. Planned JSON API (not implemented)

The sections below describe a future JSON API. They are kept as requirements only.

## 4. Cameras

### `GET /api/cameras`
Returns all configured cameras.

**Response `200`:**
```json
{
  "items": [
    {
      "id": 1,
      "name": "Front Door",
      "kind": "rtsp",
      "status": "online",
      "detection_fps": 3,
      "enabled": true,
      "created_at": "2026-11-01T10:00:00Z"
    }
  ]
}
```
Note: `source_enc` (the credential URL) is **never** returned by the API.

---

### `POST /api/cameras`
Add a new camera. `source` is the plaintext URL or device index; it is encrypted before storage.

**Request:**
```json
{
  "name": "Back Garden",
  "kind": "rtsp",
  "source": "rtsp://admin:secret@192.168.1.50:554/stream1",
  "detection_fps": 3,
  "enabled": true
}
```

**Response `201`:**
```json
{ "id": 2, "name": "Back Garden", "status": "connecting" }
```

---

### `POST /api/cameras/test`
Test a camera URL without saving it. Returns a JPEG snapshot.

**Request:**
```json
{ "source": "rtsp://admin:secret@192.168.1.50:554/stream1" }
```

**Response `200`:** `image/jpeg` (the preview frame).
**Response `422`:** `{ "error": { "code": "CAMERA_CONNECT_FAILED", "message": "…" } }`

---

### `PATCH /api/cameras/{id}`
Update camera settings (name, detection_fps, enabled). Cannot update `source` or `kind` — delete and re-add instead.

---

### `DELETE /api/cameras/{id}`
Remove a camera and stop its worker. Events referencing this camera are retained.

---

### `GET /api/cameras/{id}/stream.mjpg`
Live MJPEG stream from one camera. Requires auth.

**Response:** `multipart/x-mixed-replace; boundary=frame`

---

## 5. People

### `GET /api/people`
Returns all enrolled people.

**Response `200`:**
```json
{
  "items": [
    {
      "id": 1,
      "name": "Aryan",
      "photo_count": 4,
      "last_seen": "2026-11-05T18:45:00Z",
      "consent_at": "2026-11-01T09:00:00Z",
      "created_at": "2026-11-01T09:00:00Z"
    }
  ]
}
```

---

### `POST /api/people`
Enrol a new person with one or more photos. `multipart/form-data`.

**Fields:**
- `name` (string, required)
- `consent` (bool, required — must be `true`)
- `photos` (file[], 1–5 JPEG/PNG images)

**Response `201`:**
```json
{ "id": 3, "name": "Priya", "photo_count": 3 }
```

**Response `422` (quality failure):**
```json
{
  "error": {
    "code": "ENROLMENT_QUALITY_FAIL",
    "message": "Photo 2: no face detected. Photo 3: face too small (60 px; min 80 px)."
  }
}
```

---

### `POST /api/people/{id}/photos`
Add more photos to an existing person.

---

### `DELETE /api/people/{id}`
Delete a person. Query param `?delete_history=true` also removes associated events.

---

## 6. Unknown Faces

### `GET /api/unknown-faces`
Returns the unknown face inbox. Filter: `?status=new` (default), `dismissed`, `promoted`, `all`.

**Response `200`:**
```json
{
  "items": [
    {
      "id": 5,
      "seen_at": "2026-11-06T13:00:00Z",
      "camera": { "id": 1, "name": "Front Door" },
      "crop_url": "/api/unknown-faces/5/crop.jpg",
      "status": "new"
    }
  ]
}
```

---

### `POST /api/unknown-faces/{id}/promote`
Name the unknown face and add them as an enrolled person.

**Request:**
```json
{ "name": "Delivery Driver", "consent": true }
```

---

### `POST /api/unknown-faces/{id}/dismiss`
Mark as reviewed; remove from inbox.

---

## 7. Events

### `GET /api/events`
Paginated event history. Query params: `camera`, `person`, `type`, `from` (ISO-8601), `to`, `limit`, `cursor`.

**Response `200`:**
```json
{
  "items": [
    {
      "id": "uuid",
      "ts": "2026-11-06T13:45:00Z",
      "type": "FACE_RECOGNIZED",
      "camera": { "id": 1, "name": "Front Door" },
      "person": { "id": 1, "name": "Aryan" },
      "confidence": 0.87,
      "snapshot_url": "/api/events/uuid/snapshot.jpg"
    }
  ],
  "next_cursor": "...",
  "total": 2341
}
```

---

### `GET /api/events/stream`
Server-Sent Events stream of live events.

**Response:** `text/event-stream`

```
event: FACE_RECOGNIZED
data: {"id":"uuid","ts":"...","camera_id":1,"person_id":1,"name":"Aryan","confidence":0.87}

event: UNKNOWN_PERSON
data: {"id":"uuid","ts":"...","camera_id":1,"crop_url":"/api/unknown-faces/5/crop.jpg"}
```

---

### `GET /api/events/{id}/snapshot.jpg`
Returns the snapshot image for an event. `404` if no snapshot was saved.

---

## 8. Notification Channels and Rules

### `GET /api/notification-channels`
Returns configured channels (config is not decrypted — only type, enabled status, and display name).

### `POST /api/notification-channels`
Add a new channel. `config` is the plaintext credential object; it is encrypted before storage.

**Example request (email):**
```json
{
  "type": "email",
  "config": {
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_user": "alerts@example.com",
    "smtp_password": "...",
    "to_address": "owner@example.com"
  }
}
```

### `POST /api/notification-channels/{id}/test`
Sends a test notification on the given channel. Returns `200` with delivery confirmation or `422` with the error message.

### `GET /api/notification-rules` · `POST` · `PATCH /{id}` · `DELETE /{id}`
CRUD for notification rules. Rule schema:

```json
{
  "name": "Unknown visitor alert",
  "trigger": { "types": ["UNKNOWN_PERSON"], "cameras": [], "persons": [] },
  "channel_ids": [1, 2],
  "cooldown_s": 120,
  "quiet_hours": { "from": "23:00", "to": "07:00", "tz": "Asia/Kolkata" },
  "attach_snapshot": true,
  "enabled": true
}
```

---

## 9. Engine Controls

### `GET /api/health`
System health. Available to `admin` only.

**Response `200`:**
```json
{
  "version": "1.0.0",
  "engine_running": true,
  "cameras": [
    { "id": 1, "name": "Front Door", "status": "online", "fps": 3.0 }
  ],
  "pipeline_queue_depth": 2,
  "notification_outbox_pending": 0,
  "disk_free_gb": 42.5,
  "uptime_s": 86400
}
```

### `POST /api/engine/start` · `/stop` · `/restart`
Start, stop, or restart the detection engine. `admin` role required.

**Response `200`:** `{ "engine_running": true }`

---

## 10. Settings

### `GET /api/settings`
Returns all user-editable settings.

### `PATCH /api/settings`
Update one or more settings.

**Request:**
```json
{
  "retention_days": 14,
  "face_threshold": "balanced",
  "bind_lan": false
}
```

---

## 11. Diagnostics and Licence

### `GET /api/diagnostics`
Returns a diagnostics bundle (logs + health) with **secrets stripped**. Suitable for attaching to a support request.

**Response:** `application/zip`

### `GET /api/license`
Returns current licence status (tier, limits, expiry). Key payload is not exposed.

### `POST /api/license`
Activate a licence key.

**Request:** `{ "key": "<licence key string>" }`
