# Project Sentinel: Security Audit & Hardening Report

**Date:** 2026-11-05  **Scope:** the ~110-file snapshot uploaded in this chat (Flask dashboard, engine, face, notifications, DB).
**Method:** line-by-line read of every file, then a hardening patch with **50 automated tests** (all passing) run against it.

## 0. Read this first: three things only you can do

| # | Action | Why |
|---|--------|-----|
| 1 | **Revoke the Telegram bot token now** (`@BotFather` -> `/revoke`). | It is hardcoded in `src/notifications/settings.py` **and** `telegram_test.py`, and it has now also been pasted into an AI chat. Treat it as public. Deleting the file does not help; git history keeps it. |
| 2 | **Check git history for secrets and personal photos**: `gitleaks detect --source . --log-opts="--all"` and `git log --all --oneline -- 8454.jpg`. | I could not see your git history. Your test scripts load `8454.jpg` from the repo root: a face photo of a real person. If it was ever committed it is in history. |
| 3 | **Run the test suite and the scanner on YOUR current code** (section 6). | I audited the snapshot you uploaded (the Flask prototype). Your message mentions multi-camera, multi-face and new UI work that is **not in that snapshot**, so I could not audit it. |

## 1. Findings in the uploaded code

Severity: CRIT = fix before anything else, HIGH = fix before any user, MED = fix before selling, LOW = hygiene.
Status: **FIXED** = patch included and tested, **ACTION** = needs you, **VERIFY** = I could not confirm from the files.

| ID | Sev | Finding (evidence) | Status |
|----|-----|--------------------|--------|
| S-01 | CRIT | Telegram token + chat ID hardcoded (`notifications/settings.py`, `telegram_test.py`). | **ACTION** revoke; code now reads env only |
| S-02 | CRIT | Dashboard has **no login**, `run.py` binds `0.0.0.0`, `POST /start /stop /restart` unauthenticated, no CSRF. Anyone on the Wi-Fi controls the system. | **FIXED** (default-deny auth, roles, CSRF, loopback default) |
| S-03 | CRIT | `pickle.loads()` on DB content (`face/database.py`): a tampered DB file = code execution. | **FIXED** raw float32 blobs; legacy rows are skipped, never loaded (tested with a malicious payload) |
| S-04 | HIGH | `requests` exceptions embed the full URL, which contains the bot token. Any `logger.exception` would write the token to logs. | **FIXED** client logs only the exception class; global log redaction added (tested) |
| S-05 | HIGH | One failed Telegram call propagates through `EventBus.publish` and kills the engine loop; notification is synchronous and blocks video for up to 10 s (DoS by network outage). | **FIXED** subscriber isolation + bounded background queue |
| S-06 | HIGH | No security headers, no CSP, default `Server` banner. | **FIXED** |
| S-07 | HIGH | Biometric data (embeddings) and snapshots unencrypted, relative paths, no permissions, snapshots never served through an authenticated route. | **PARTLY FIXED** DB dir/file chmod 700/600, authenticated snapshot route with strict filename; **ACTION** enable OS disk encryption; see S-14 |
| S-08 | HIGH | Two SQLite files, face DB opened with `check_same_thread=False` and one shared connection across threads (corruption/lock errors). | **FIXED** (FaceDatabase) one short-lived connection per operation, single configured path |
| S-09 | MED | `.gitignore` lacks `*.db`, `snapshots/`, `*.pt`, `*.bak`, `data/`, root images. A stray `git add .` would commit face data. | **FIXED** new `.gitignore` |
| S-10 | MED | Inline `<script>` in `index.html` and `innerHTML` in JS: blocks a strict CSP and is an XSS sink. | **FIXED** external JS, `textContent`, no inline script/style (tested) |
| S-11 | MED | Telegram command handlers (`/start /ping /status`) have **no sender check**. Harmless today; the moment `/status` or a snapshot command returns real data, any Telegram user who finds the bot gets it. | **ACTION** snippet in section 5 (untested: library not installable here) |
| S-12 | MED | No request-size limit, no input validation layer (person names, camera URLs, image uploads). | **FIXED** `MAX_CONTENT_LENGTH`, `validators.py` (SSRF/`file://`/numeric-IP tricks, magic-byte + declared-dimension image checks) |
| S-13 | MED | Debug `print`s at import (`ai/detector.py`) and in handlers (`routes.py`). | **FIXED** in routes; **ACTION** remove the prints in `ai/detector.py` |
| S-14 | MED | Camera URLs contain passwords (`rtsp://user:pass@...`). Your camera-registry code was not uploaded. | **ACTION** store with `SecretBox.encrypt()` (provided, tested incl. key rotation); mask with `mask_url()` |
| S-15 | MED | `tools/fix_imports.py` rewrites source files; `*.bak` copies of old code are in the repo. | **ACTION** delete both |
| S-16 | MED | No `requirements.txt`/lock file uploaded: dependency CVEs **unverifiable**. | **ACTION** section 4 |
| S-17 | LOW | Recognition threshold 0.50 with no margin-to-second-best rule; no liveness detection (photo/screen spoofing). | **ACTION** benchmark on your own data (ROADMAP Phase 2); never market as access control |
| S-18 | LOW | `datetime.utcnow` deprecated; `MockCamera` returns a string. | not security; see CODE_REVIEW.md |

**Checked and found OK:** every SQL statement in the upload uses `?` parameters (no injection); Jinja2 autoescape is on and no `|safe` / `render_template_string` is used; Telegram messages are sent without `parse_mode`, so event text cannot inject markup; `.env` is git-ignored.

## 2. Your checklist, item by item

| Area | State after patch |
|------|-------------------|
| **API keys / env vars** | Secrets only from `.env`. `SECRET_KEY` (>=32 chars, placeholders rejected) and `SENTINEL_ENCRYPTION_KEYS` are mandatory: the app **refuses to start** without them (`python tools/gen_secrets.py`). `.env.example` provided. Config `repr` never prints secrets. |
| **Admin routes** | Default-deny in one hook (`security/auth.py`): everything needs login; every non-GET needs `admin`. A test enumerates **every registered route** and fails if one is reachable anonymously, so a forgotten decorator cannot slip through. |
| **Auth / sessions** | First-run setup (one-shot, atomic, loopback-only or setup-token), no default credentials, session rotation on login (fixation), HttpOnly + SameSite=Lax (+Secure/`__Host-` over HTTPS), idle (30 min) and absolute (12 h) timeouts, password change / disable / reset **revokes all sessions** (epoch), open-redirect-safe `next`, generic login errors, constant-time-ish verification for unknown users. |
| **Row-level access** | Sentinel is single-tenant, so there are no per-user rows to isolate today. What exists: roles (`admin` / `viewer`), viewer is read-only. **If you ever host multiple customers in one DB, every table needs an owner column and every query a filter. That is a redesign, not a patch.** |
| **Input sanitising** | `validators.py`: names, camera sources, images, snapshot filenames, path-join guard. SQL stays parameterised. Output is escaped by Jinja2 (tested with a `<script>` payload). |
| **XSS** | Strict CSP (`script-src 'self'`, no `unsafe-inline`/`unsafe-eval`), no inline script/style/handlers (tested), `textContent` in JS. |
| **Rate limiting** | Login: 5 failures per (IP, username) or 20 per IP in 15 min -> 429 + `Retry-After`; keyed so an outsider cannot lock the real admin out. A reusable `SlidingWindowLimiter` is provided but **only login uses it so far**; apply it to upload/enrol/camera-test routes when you add them. In-memory, per process. |
| **CORS** | None. No `Access-Control-*` header is ever emitted (tested, including preflight). CSRF token + `Origin` check on every state-changing request. |
| **Security headers** | CSP, nosniff, X-Frame-Options, `frame-ancestors 'none'`, Referrer-Policy, Permissions-Policy, COOP/CORP, `no-store`, HSTS when `SENTINEL_HTTPS=true`. |
| **Debug mode** | `DEBUG` / `FLASK_DEBUG` make startup fail; `app.debug` is forced `False`; the scanner flags `debug=True`. |
| **Dependencies** | See section 4. CI runs `pip-audit` + `bandit`. |
| **Exposed files** | Snapshots are never static: authenticated route, `^[A-Za-z0-9][A-Za-z0-9_.-]*\.jpg$`, traversal tests (`..%2F`, `%00`, `.env`) pass. `.gitignore` covers DBs, images, models, env files. |
| **Database** | Parameterised SQL, WAL, foreign keys, per-operation connections, dir 700 / file 600 (no-op on Windows), audit log table. **Not encrypted at rest**: use full-disk encryption (BitLocker/LUKS/FileVault). |
| **Password hashing** | argon2id when `argon2-cffi` is installed (add it), scrypt otherwise; transparent upgrade on login; min 10 / max 128 chars, no composition rules, common-password and repetition checks. |
| **Leaked secrets in git** | Scanner (`tools/security_scan.py`, also `--staged` for a pre-commit hook), `.gitignore`, gitleaks in CI. History cleanup: section 3. |

## 3. Cleaning git history (only after revoking the token)
```bash
pip install git-filter-repo
printf '%s\n' 'PUT_THE_OLD_TOKEN_HERE==>REMOVED' > /tmp/replacements.txt   # keep this file out of the repo
git filter-repo --replace-text /tmp/replacements.txt
git filter-repo --path 8454.jpg --invert-paths        # only if that photo was ever committed
git push --force --all && git push --force --tags
shred -u /tmp/replacements.txt
```
Forks, clones and GitHub's cached commit views can keep the old data: **revocation is the real fix**, history cleanup is tidiness. Everyone who cloned must re-clone.

## 4. Dependencies
I had no network and no `requirements.txt`, so I **did not check any CVE** and I will not invent version pins.
```bash
pip install flask cryptography python-dotenv argon2-cffi waitress requests    # see requirements-security.txt
pip freeze > requirements.txt            # then: pip install pip-tools && pip-compile --generate-hashes
pip-audit -r requirements.txt && bandit -r src -ll
```
Known licensing blockers (InsightFace weights, YOLOv8 AGPL) are covered in `BUSINESS_AND_LICENSING.md`; they are a legal risk, not a vulnerability.

## 5. Telegram command authorisation (S-11, untested here)
```python
# src/notifications/handlers.py
from telegram.ext import CommandHandler, filters
from src.notifications.settings import CHAT_ID
only_owner = filters.Chat(chat_id=CHAT_ID)          # reject everyone else silently
app.add_handler(CommandHandler("status", status, filters=only_owner))
```
Do this for every handler. Verify with a second Telegram account.

## 6. Install, verify, and what changes for you
1. Copy the files in this folder over your repo (same relative paths). Review the diff for `dashboard/*`, `notifications/*`, `face/database.py`, `events/event_bus.py`, `app_logging/logger.py`, `run.py`; **if you edited those after the snapshot, merge by hand.**
2. `python tools/gen_secrets.py` -> paste into `.env`; add the **new** Telegram token and chat ID.
3. `python -m unittest tests.test_security -v` (50 tests) and `python tools/security_scan.py` (must print "No HIGH findings").
4. `python run.py` -> open `http://127.0.0.1:5000` -> create the admin.

**Behaviour changes:** `DEBUG=True` in `.env` now stops startup; all forms need the CSRF token; face data now lives at `DATABASE_PATH` and old pickled faces are ignored, so **re-enrol faces**; person names must match the validator; Telegram stays silent until configured.

## 7. What I could not verify (be sceptical here)
- Anything written after the uploaded snapshot, git history, installed dependency versions and CVEs.
- `run.py` with real cameras/models and the `waitress` branch (not installed here); the Telegram handler snippet.
- Tests ran with the original `dashboard_service`/`event`/`cooldown` replaced by minimal stand-ins; run them in your repo.
- Limits by design: login throttling is per process; camera-URL validation cannot stop DNS rebinding (hence admin-only); no liveness detection; no 2FA; no encryption of the SQLite file itself; cookie sessions are signed, not encrypted (they hold no secrets).
- **No review can promise zero mistakes.** Before charging customers: a second reviewer on `security/auth.py`, an independent penetration test, and `DEPLOY_CHECKLIST.md` section A.

---

## 8. Post-repair verification (2026-11-06)

This section records what was re-checked against the current tree; sections 1–7 above are
the original snapshot audit and are kept for history.

**Fixed and verified**

- **Legacy `users` table (new, P0).** The live install's `users` table lacked
  `active`/`session_epoch`/`last_login_at`; every login raised `IndexError`. Both
  `SecurityStore` and the schema migration runner now add the columns in place
  (`PRAGMA user_version` 5), preserving accounts and password hashes. Verified on a copy
  of the real database over real HTTP: wrong password → `401`, correct password → `302`
  and the dashboard renders.
- **CSRF `bad_origin` false rejection (S-02 follow-up).** The audit log had 12
  `bad_origin POST /login` rows from `127.0.0.1`. Origin comparison now normalizes
  scheme/host/port and treats `localhost`/`127.0.0.1`/`::1` as one authority only on the
  same scheme and port. Tokens are still required; foreign, `null` and different-port
  origins are still rejected. See ADR-010 in `docs/DECISIONS.md`.
- **Two CSRF implementations.** The unused `src/dashboard/guards.py` (different session
  key, `abort(400)`) and its root-level copy were deleted; `src/security/csrf.py` is the
  only implementation.
- **Two camera-URL validators.** `src/camera/url_utils.validate_source` now delegates to
  `src.security.validators.validate_camera_source`, so metadata hosts, ambiguous numeric
  IPs and control characters are rejected on the camera routes too.
- **`create_app` overrides.** Overrides were applied after the security settings, so a
  view override could weaken cookie/upload/secret settings. They are now applied first.
- **Duplicate/legacy files.** Nine root-level copies (`schema.py`, `guards.py`,
  `crypto.py`, `file_camera.py`, `opencv_source.py`, four `test_*.py`) had no importers
  and conflicted with `src/`; removed (recoverable from git history and the backup).
- **Scanner scope.** `tools/security_scan.py` no longer reports bundled `.agents` skills,
  intentional test fixtures or docs examples; `.env` is skipped for working-tree scans
  but still scanned by `--staged`. It now prints `No HIGH findings.` on this tree.
- **CI.** `.github/workflows/security.yml` referenced a non-existent `requirements.txt`;
  it now installs the project and audits the environment. The ignored root `ci.yml` was
  replaced by `.github/workflows/test.yml`.

**Still requires the owner (not performed here)**

1. **Revoke the Telegram bot token** in `.env` and any token committed in history
   (`src/notifications/settings.py` and `telegram_test.py` appear in past commits, and
   `.env` itself was committed in several commits). The current tree contains no
   token-shaped secret, but history does. Revocation is the real fix; then purge with
   `git filter-repo` and force-push, and rotate `SECRET_KEY` / `SENTINEL_ENCRYPTION_KEYS`
   only if they were exposed.
2. **Hardware and delivery tests** (USB/IP camera, Telegram, web push) are still not
   exercised; the suite uses fakes and mocked HTTP.
3. **Dependency CVEs** (`pip-audit`) and `bandit` were not run in this environment
   (not installed); CI is configured to run them.
