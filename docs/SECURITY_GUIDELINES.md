# Security Guidelines: Project Sentinel

> Companion to [THREAT_MODEL.md](THREAT_MODEL.md). "Existing" = implemented and verified in the prototype. "Required" = must be in place before any paid customer. "Proposed" = planned; not yet implemented.

---

## 1. Authentication

### First-run wizard (Implemented)
- The application starts in a "setup required" state if no users exist in `users`.
- While no user exists, HTML requests to protected pages redirect to `/setup` and
  `/login` redirects there too; `/api/*` still answers `401`.
- `/setup` is one-shot (404 once a user exists), refuses non-loopback clients unless
  `SENTINEL_SETUP_TOKEN` is set and supplied, and creates the first admin. No default
  password exists anywhere.
- The wizard does **not** sign the new admin in; they must log in at `/login`.

### Password hashing (Required)
```python
# Use argon2-cffi
from argon2 import PasswordHasher
ph = PasswordHasher()
hash = ph.hash(password)        # store this
ph.verify(hash, password)       # on login; raises VerifyMismatchError on failure
```
- Never store passwords in plain text, as MD5/SHA-1 hashes, or reversibly encrypted.
- Minimum password length: 10 characters. No arbitrary complexity rules.

### Session cookies (Implemented)
`src/dashboard/app.py` sets on flask session config:
```
sentinel_session=<signed>; HttpOnly; Path=/; SameSite=Lax
```
- `SENTINEL_HTTPS=true` switches the name to `__Host-sentinel_session` and adds `Secure`.
  A `Secure`/`__Host-` cookie cannot be stored over plain HTTP: if the dashboard is
  reachable without TLS, the browser drops the session and every form posts 403.
- Idle timeout `SESSION_IDLE_MINUTES` (default 30), absolute timeout
  `SESSION_ABSOLUTE_HOURS` (default 12); both are enforced server-side in
  `src/security/auth.py` on every request.
- Session content: user id, role, CSRF token, issue/seen timestamps, and a session
  `epoch` compared with the user row. Logout, password change, disabling a user or
  deleting it all invalidate existing sessions because the epoch no longer matches.
  Login rotates the session id (no session fixation).

### Login rate-limiting (Implemented)
- 5 failures per (IP, username) or 20 failures per IP within 15 minutes, then `429` with
  a `Retry-After` header (`src/security/ratelimit.py`). Keying on the pair means an
  outsider cannot lock the real admin out.
- Error response: generic `"Invalid username or password."` — never disclose which field
  was wrong. Unknown users still run one password hash so timing does not reveal them.
- Success and failure are both written to the `audit_log` table.
- The limiter is in process memory, so it resets on restart and is per worker.

---

## 2. Authorisation

### Role model (Required)

| Role | Permissions |
|------|-------------|
| `admin` | Full access to all routes and settings |
| `viewer` | Read-only: dashboard, event timeline, camera live view. Cannot manage faces, cameras, settings, or users |

### Route enforcement (Implemented)
There is no per-route decorator to forget: one `before_request` hook in
`src/security/auth.py` is default-deny.

```python
# every endpoint needs a signed-in user, except PUBLIC_ENDPOINTS
if endpoint in PUBLIC_ENDPOINTS:
    return None
if g.user is None:
    return _deny_unauthenticated()          # 302 to /login, or 401 JSON
# every non-GET needs the admin role, except self-service logout/password change
if request.method not in SAFE_METHODS and endpoint not in SELF_SERVICE_ENDPOINTS:
    if g.user.role != "admin":
        abort(403)
```

`PUBLIC_ENDPOINTS` is the only allow-list: login, setup, static files, `/healthz`,
`/api/health`, the web manifest and the service worker. `test_security.py` enumerates
**every registered route** and fails if one is reachable anonymously. The `/admin`
blueprint adds `require_admin`/`require_role` as defence in depth. Never rely on hidden
UI elements alone.

---

## 3. CSRF Protection

### Token-based CSRF (Implemented, `src/security/csrf.py`)
- Every non-`GET/HEAD/OPTIONS` request must carry the token, as the form field
  `csrf_token` or the header `X-CSRF-Token`.
- The token is per session and rendered server-side into the page:
  `<meta name="csrf-token" content="{{ csrf_token() }}">` in `base.html`, and a hidden
  `csrf_token` input in every form. There is **no** `/api/csrf` endpoint; the field is
  **not** `_csrf_token`.
- A present `Origin` header must match the request host or an entry in
  `SENTINEL_TRUSTED_ORIGINS` (needed behind a reverse proxy that rewrites the host).
  `Origin: null` is always rejected.
- Failure is `403` and is classified (`bad_origin`, `no_session`, `missing_token`,
  `mismatch`), logged as a warning and written to `audit_log` as `csrf_denied`. The
  login/setup form is re-rendered with a fresh token so the user can retry.
- Common cause of a login `403`: the session cookie was not sent (cookies blocked, or a
  `Secure` cookie while browsing over plain HTTP). Check the audit log for
  `csrf_denied` before assuming an authentication bug.

```javascript
// Mutating fetch() calls send the token from the page's meta tag
const token = document.querySelector('meta[name="csrf-token"]').content;
fetch('/api/push/subscribe', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
  body: JSON.stringify(data),
});
```

Forms post the hidden field:
```html
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

---

## 4. Secret Management

### Rules (Non-negotiable)
1. No secrets in source control — ever. Use `.env.example` as a template; never commit `.env`.
2. `SECRET_KEY` must be a cryptographically random 48-byte URL-safe string.
3. `TELEGRAM_BOT_TOKEN`, SMTP passwords, webhook URLs, and camera credentials must never be hardcoded.

### Generating the secret key
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Loading secrets
```python
# src/sentinel/settings.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    secret_key: str            # crashes with a clear message if missing
    telegram_bot_token: str = ""
    database_path: str = "data/sentinel.db"
    # ...

    model_config = {"env_file": ".env"}
```

### Credential encryption (Required)
Camera RTSP URLs and notification channel credentials are encrypted before storage:

```python
from cryptography.fernet import Fernet
import hashlib, base64

def _fernet(secret_key: str) -> Fernet:
    key = base64.urlsafe_b64encode(
        hashlib.sha256(secret_key.encode()).digest()
    )
    return Fernet(key)

def encrypt(value: str, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(value.encode()).decode()

def decrypt(value: str, secret_key: str) -> str:
    return _fernet(secret_key).decrypt(value.encode()).decode()
```

### Prototype remediation (Immediate)
1. `@BotFather → /revoke` — revoke the current token; it is burned.
2. Add the new token to `.env` as `TELEGRAM_BOT_TOKEN`.
3. Load it via `settings.telegram_bot_token` — never hardcode.
4. Run `gitleaks detect` to check git history for other leaked secrets.
5. If the repository was ever public, treat all historical tokens as burned regardless.

---

## 5. Network Security

### Bind address (Required)
Default: `HOST=127.0.0.1`. The application binds to localhost only unless the owner explicitly sets `HOST=0.0.0.0` through the Settings UI, which shows a warning and recommends HTTPS + a strong password.

### HTTPS (Recommended for LAN access)
- Document a Caddy or nginx reverse-proxy setup in `docs/DEPLOYMENT.md`.
- Self-signed certificate option for LAN use with clear browser warning guidance.
- Enable `Secure` on session cookies only when HTTPS is detected.

### Security headers (Required)
```python
# FastAPI middleware
app.add_middleware(
    SecurityHeadersMiddleware,
    # or set manually in a response middleware:
)
# Headers to include on every response:
# Content-Security-Policy: default-src 'self'; script-src 'self'; img-src 'self' data:
# X-Content-Type-Options: nosniff
# X-Frame-Options: DENY
# Referrer-Policy: strict-origin-when-cross-origin
# Permissions-Policy: camera=(), geolocation=()
```

### Camera URL allow-list (Required)
```python
ALLOWED_SCHEMES = {"rtsp", "rtsps", "http", "https"}

def validate_camera_source(source: str | int) -> None:
    if isinstance(source, int):
        return   # USB device index
    parsed = urlparse(source)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"Scheme '{parsed.scheme}' not allowed.")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Cannot use loopback addresses as a camera source.")
```

---

## 6. Input Validation

### General (Required)
- Validate all API inputs with Pydantic models. `422` on validation failure.
- Never pass user input directly into shell commands, file paths outside the allowed directory, or SQL strings.
- File upload limits: max 10 MB per photo; `image/jpeg` and `image/png` only; verify by decoding the image, not just checking the MIME type.

### Enrolment photos (Required)
```python
import cv2, numpy as np

def validate_photo(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image.")
    h, w = img.shape[:2]
    if w > 4096 or h > 4096:
        raise ValueError("Image too large (max 4096×4096).")
    return img
```

### Snapshot serving (Required)
Never serve snapshots as static files. Always validate the path is under `data/snapshots/` before serving:

```python
SNAPSHOT_DIR = Path(settings.snapshot_path).resolve()

def safe_snapshot_path(relative: str) -> Path:
    p = (SNAPSHOT_DIR / relative).resolve()
    if not str(p).startswith(str(SNAPSHOT_DIR)):
        raise PermissionError("Path traversal attempt.")
    return p
```

---

## 7. Data Security

### Face embeddings (Required)
Store as raw `float32` bytes. Never use `pickle`:

```python
import numpy as np

def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()

def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).copy()
```

### Biometric data principles
- Collect only what is needed for recognition (embedding + optional original photo with consent).
- Record `consent_at` on every enrolled person.
- "Delete person" removes all embeddings, photos, and optionally associated events.
- Default retention period for unknown face crops: 7 days.
- Never return raw embeddings via the API.
- Never log face data or embedding values.

---

## 8. Logging and Redaction

### Rules (Required)
```python
# NEVER log:
# - Camera RTSP URLs (contain passwords)
# - Telegram tokens, SMTP passwords, webhook URLs
# - Session tokens or CSRF tokens
# - Face embeddings or biometric values
# - Full file paths containing PII

# Log camera activity with masked URL:
def mask_url(url: str) -> str:
    p = urlparse(url)
    return p._replace(netloc=f"{p.username}:***@{p.hostname}:{p.port}").geturl()

logger.info("Camera %s connected: %s", camera_id, mask_url(source))
```

### Log levels
- `DEBUG`: frame processing metrics (behind `LOG_LEVEL=DEBUG`; never in production)
- `INFO`: engine start/stop, camera connect/disconnect, person recognised, alert sent
- `WARNING`: reconnect attempts, failed deliveries, quality rejections
- `ERROR`: unhandled exceptions, model load failures
- `CRITICAL`: secret missing on startup, DB migration failure

---

## 9. Dependency Security

```bash
# Run in CI on every push and before every release
pip-audit                              # checks known CVEs in installed packages
bandit -r src/ -ll                     # static analysis; report medium and above
ruff check src/                        # style + common bug patterns
gitleaks detect --no-git               # secret scanning
pip-licenses --format=markdown         # check for new GPL/AGPL/NC dependencies
```

- Pin all dependencies in `pyproject.toml` to exact versions.
- Review and update monthly; security patches immediately.
- Separate `[dev]` extras for test tools; never ship them in the production package.
- Check **model weight licences** separately from code licences (InsightFace and YOLOv8 were non-commercial/AGPL as of November 2026).

---

## 10. File Upload Security

| Check | Implementation |
|-------|---------------|
| Authenticate the request | Auth middleware; no public upload routes |
| CSRF token | Required on the upload form |
| File type | Decode with OpenCV; reject if decode fails |
| File size | Max 10 MB per file; max 5 files per request |
| Filename | Ignore the client-provided filename; generate a UUID-based name server-side |
| Storage location | Store under `data/uploads/`; never under the web root |
| Virus scanning | Optional for high-security deployments; not in MVP |

---

## 11. Pre-Paid-Customer Security Checklist

- [ ] Telegram token revoked and moved to `.env`
- [ ] `pickle` removed from face database
- [ ] Auth on every route; no default credentials
- [ ] CSRF on all state-changing routes
- [ ] Binds to `127.0.0.1` by default
- [ ] Session cookie: `HttpOnly`, `SameSite=Lax`
- [ ] Passwords hashed with argon2id
- [ ] Camera credentials encrypted at rest
- [ ] Secrets never appear in logs
- [ ] Snapshots served through authenticated route
- [ ] `pip-audit` and `bandit` clean
- [ ] `gitleaks` clean
- [ ] Camera URL scheme allow-list
- [ ] `THIRD_PARTY_LICENSES.md` verified — no AGPL or non-commercial components
- [ ] `SECURITY.md` with vulnerability disclosure contact
