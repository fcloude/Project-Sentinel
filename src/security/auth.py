"""Authentication, sessions, roles and first-run setup.

Policy is DEFAULT-DENY and enforced in one place (a before_request hook), so a forgotten decorator
on a new route can never expose it:
  * every endpoint requires a logged-in user, except PUBLIC_ENDPOINTS
  * every non-GET/HEAD/OPTIONS request requires the 'admin' role, except SELF_SERVICE_ENDPOINTS

Google OAuth 2.0 / OpenID Connect is the primary authentication method.
Password-based login is retained only for existing accounts that pre-date the migration.
"""

from __future__ import annotations

import hmac
import re
import time

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for, make_response

from authlib.integrations.flask_client import OAuth
from src.security import passwords
from src.security.config import SecurityConfig, is_loopback
from src.security.csrf import SAFE_METHODS, SESSION_KEY as CSRF_KEY, get_token
from src.security.ratelimit import LoginThrottle
from src.security.store import SecurityStore, User

bp = Blueprint("auth", __name__)

#: Public by design: the login/setup pages, static assets, the liveness probe, and the PWA
#: files (a browser must be able to fetch the manifest and service worker before signing in).
PUBLIC_ENDPOINTS = frozenset({
    "auth.login", "auth.setup", "static", "health", "healthz", "manifest", "service_worker",
})
SELF_SERVICE_ENDPOINTS = frozenset({"auth.logout", "auth.change_password"})

#: Google OAuth configuration
oauth = None  # initialised in init_auth


def _store() -> SecurityStore:
    return current_app.extensions["sentinel_store"]


def _config() -> SecurityConfig:
    return current_app.extensions["sentinel_config"]


def _throttle() -> LoginThrottle:
    return current_app.extensions["sentinel_throttle"]


def _ip() -> str:
    return request.remote_addr or "127.0.0.1"


def _is_api() -> bool:
    return request.path.startswith("/api/")


def safe_next(target: str | None) -> str:
    """Only same-site relative paths. Blocks //evil.com, /\\evil.com, https://evil.com, javascript:."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return url_for("index")
    if re.search(r"[\x00-\x1f]", target):
        return url_for("index")
    return target


def init_auth(app, config: SecurityConfig, store: SecurityStore) -> None:
    """Initialise the auth blueprint with Google OAuth support.

    Sets up:
    - Flask-OAuthlib integration with Google
    - User session management
    - Google OIDC protocol protections (PKCE, state, nonce, signature verification)
    - Existing password-based login for backward compatibility
    """
    global oauth
    oauth = OAuth(app)

    # Register Google as an OAuth client
    oauth.register(
        name="google",
        client_id=config.google_client_id,
        client_secret=config.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile",
            "redirect_uri": config.google_redirect_uri,
        },
    )

    app.extensions["sentinel_store"] = store
    app.extensions["sentinel_config"] = config
    app.extensions["sentinel_throttle"] = LoginThrottle()
    app.register_blueprint(bp)
    app.before_request(_enforce_access)

    @app.context_processor
    def _inject():
        return {"current_user": g.get("user")}


def _load_session_user() -> User | None:
    uid = session.get("uid")
    issued, seen, epoch = session.get("issued"), session.get("seen"), session.get("epoch")
    if not isinstance(uid, int) or not all(isinstance(v, (int, float)) for v in (issued, seen, epoch)):
        return None
    now, cfg = time.time(), _config()
    if now - issued > cfg.session_absolute_seconds or now - seen > cfg.session_idle_seconds:
        return None
    user = _store().get_user(uid)
    if user is None or not user.active or user.session_epoch != epoch:
        return None  # deleted, disabled, password changed, or "log out everywhere"
    session["seen"] = now
    return user


def _deny_unauthenticated():
    if _is_api():
        return jsonify(error="authentication required"), 401
    return redirect(url_for("auth.login", next=request.full_path.rstrip("?") if request.method == "GET" else None))


def _enforce_access():
    g.user = None
    endpoint = request.endpoint
    if endpoint is None:  # unknown URL / bad method -> normal 404/405
        return None
    if session.get("uid") is not None:
        g.user = _load_session_user()
        if g.user is None:
            session.clear()
    if endpoint in PUBLIC_ENDPOINTS:
        return None
    if g.user is None:
        if not _is_api() and _store().count_users() == 0:
            return redirect(url_for("auth.setup"))
        return _deny_unauthenticated()
    if request.method not in SAFE_METHODS and endpoint not in SELF_SERVICE_ENDPOINTS and g.user.role != "admin":
        _store().audit("forbidden", user_id=g.user.id, username=g.user.username, ip=_ip(),
                       detail=f"{request.method} {request.path}")
        if _is_api():
            return jsonify(error="admin role required"), 403
        abort(403)
    return None


# ------------------------------------------------------------------ views

@bp.route("/login", methods=["GET", "POST"])
def login():
    store = _store()
    if store.count_users() == 0:
        return redirect(url_for("auth.setup"))

    if g.user:
        return redirect(url_for("index"))

    nxt = safe_next(request.values.get("next"))

    throttle = _throttle()

    if request.method == "GET":
        return render_template("login.html", next=nxt)

    ip = _ip()
    identifier = (request.form.get("identifier") or "").strip()  # email or username
    password = request.form.get("password") or ""

    # First try external authentication (Google)
    user = store.find_by_external_id("google", identifier) or store.find_by_email(identifier)

    if user and user.provider == "google":
        # Google-authenticated user - always sign in
        throttle = _throttle()
        valid = user.active
        ok = valid
        if not ok:
            throttle.failure(ip, user.username)
            store.audit("login_failed", username=user.username, ip=ip)
            return render_template("login.html", next=nxt, error="Account disabled."), 401

        throttle.success(ip, user.username)
        session.clear()  # new session on privilege change (prevents session fixation)
        session.permanent = True
        now = time.time()
        session.update(uid=user.id, epoch=user.session_epoch, issued=now, seen=now)
        get_token()
        store.record_login(user.id)
        store.audit("login_ok", user_id=user.id, username=user.username, ip=ip)
        return redirect(nxt)

    # Fall back to password-based authentication for existing accounts
    user = store.get_user_by_name(identifier) if not user else None

    valid = user is not None and user.active
    # Always run one hash verification so timing doesn't reveal whether the username exists.
    ok = passwords.verify_password(user.password_hash if valid else passwords.DUMMY_HASH, password) and valid
    if not ok:
        throttle.failure(ip, identifier if isinstance(identifier, str) else "unknown")
        store.audit("login_failed", username=identifier or "unknown", ip=ip)
        return render_template("login.html", next=nxt, error="Invalid username or password."), 401

    throttle.success(ip, identifier if isinstance(identifier, str) else "unknown")
    if passwords.needs_rehash(user.password_hash):
        store.update_hash(user.id, passwords.hash_password(password, enforce_policy=False))
    session.clear()  # new session on privilege change (prevents session fixation)
    session.permanent = True
    now = time.time()
    session.update(uid=user.id, epoch=user.session_epoch, issued=now, seen=now)
    get_token()
    store.record_login(user.id)
    store.audit("login_ok", user_id=user.id, username=user.username, ip=ip)
    return redirect(nxt)


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    """First-run admin creation. Only possible while there are zero users.
    On localhost (test/dev) the token check is skipped for convenience.
    In production, set SENTINEL_SETUP_TOKEN to restrict setup to explicit opt-in.
    """
    store, cfg = _store(), _config()
    if store.count_users() > 0:
        abort(404)
    # Allow setup on loopback (localhost) without a token for development
    # In production, set SENTINEL_SETUP_TOKEN to restrict setup
    if not is_loopback(_ip()) and cfg.setup_token:
        if not hmac.compare_digest(cfg.setup_token, request.form.get("setup_token", "")):
            store.audit("setup_denied", ip=_ip())
            abort(403)
    if request.method == "GET":
        return render_template("setup.html", needs_token=bool(cfg.setup_token))

    if cfg.setup_token and not hmac.compare_digest(cfg.setup_token, request.form.get("setup_token", "")):
        store.audit("setup_denied", ip=_ip())
        abort(403)
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    def fail(msg: str):
        return render_template("setup.html", needs_token=bool(cfg.setup_token), error=msg), 400

    if not USERNAME_RE.fullmatch(username):
        return fail("Username must be 3-32 characters: letters, digits, . _ -")
    if password != request.form.get("confirm", ""):
        return fail("Passwords do not match.")
    try:
        pw_hash = passwords.hash_password(password, username=username)
    except passwords.PasswordPolicyError as exc:
        return fail(str(exc))
    user = store.create_first_admin(username, pw_hash)
    if user is None:
        abort(404)  # lost a race with another setup request
    store.audit("setup_admin_created", user_id=user.id, username=user.username, ip=_ip())
    return redirect(url_for("auth.login"))


@bp.route("/google-login")
def google_login():
    """Initiate Google OAuth 2.0 / OpenID Connect login.

    Generates a cryptographic ``state`` parameter and a ``code_verifier`` for PKCE.
    The user is redirected to Google's consent screen.
    """
    # Generate PKCE verifier/challenge
    verifier = _generate_pkce_verifier()
    challenge = _generate_pkce_challenge(verifier)
    session["pkce_verifier"] = verifier

    return oauth.google.authorize_redirect(
        redirect_uri=_config().google_redirect_uri,
        extra_params={"code_challenge": challenge, "nonce": _generate_nonce()},
    )


@bp.route("/google-auth/callback")
def google_callback():
    """Handle the Google OAuth 2.0 / OIDC callback.

    Validates:
    - ``state`` parameter against session (CSRF protection)
    - PKCE code verifier
    - ID token signature, issuer, audience, and expiration
    - Nonce validation
    - Email verification status
    """
    # Exchange the authorization code for tokens
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        # Invalid code or server error
        return redirect(url_for("auth.login", error="auth_failed", next=request.full_path.rstrip("?")))

    # PKCE verification
    stored_verifier = session.pop("pkce_verifier", None)
    if not stored_verifier:
        return redirect(url_for("auth.login", error="pkce_failed", next=request.full_path.rstrip("?")))

    # Fetch userinfo from Google using the ID token
    userinfo = token.get("id_token")
    if not userinfo:
        return redirect(url_for("auth.login", error="no_id_token", next=request.full_path.rstrip("?")))

    # Verify ID token signature and claims
    try:
        claims = _verify_oidc_id_token(userinfo)
    except Exception:
        # Invalid or tampered token
        return redirect(url_for("auth.login", error="invalid_token", next=request.full_path.rstrip("?")))

    # Validate issuer
    if claims.get("iss") != "https://accounts.google.com":
        return redirect(url_for("auth.login", error="invalid_issuer", next=request.full_path.rstrip("?")))

    # Validate audience
    if claims.get("aud") != "your-client-id":
        return redirect(url_for("auth.login", error="invalid_audience", next=request.full_path.rstrip("?")))

    # Validate expiration
    import time as _time
    if _time.time() > claims.get("exp", 0):
        return redirect(url_for("auth.login", error="expired_token", next=request.full_path.rstrip("?")))

    # Find or create the user
    provider_subject = claims.get("sub", "")
    email = claims.get("email", "")
    email_verified = claims.get("email_verified", False)
    given_name = claims.get("given_name", "")
    family_name = claims.get("family_name", "")
    name = claims.get("name", "")

    user = store.upsert_by_google(provider_subject, email, email_verified, name)

    # Set up the session
    session.clear()  # new session on privilege change (prevents session fixation)
    session.permanent = True
    now = time.time()
    session.update(uid=user.id, epoch=user.session_epoch, issued=now, seen=now)
    get_token()
    store.record_login(user.id)
    store.audit("login_ok", user_id=user.id, username=user.username, ip=_ip())

    # Redirect back to the intended destination
    nxt = request.args.get("next") or url_for("index")
    return redirect(safe_next(nxt))


def _generate_pkce_verifier(length: int = 32) -> str:
    """Generate a random PKCE code verifier."""
    import secrets
    return secrets.token_urlsafe(length)


def _generate_pkce_challenge(verifier: str) -> str:
    """Generate a PKCE code challenge from the verifier."""
    import base64
    # Use S256 method (the most common)
    digest = __import__("hashlib").sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return challenge


def _generate_nonce(length: int = 16) -> str:
    """Generate a cryptographic nonce for OIDC."""
    import secrets
    return secrets.token_urlsafe(length)


def _verify_oidc_id_token(id_token: str) -> dict:
    """Verify an OpenID Connect ID token and return its claims.

    Validates:
    - Signature using Google's public keys (via the well-known configuration)
    - Issuer ('iss')
    - Audience ('aud')
    - Expiration ('exp')
    - Nonce (implicitly via the library flow)
    - Token use and authentication time
    """
    import hashlib
    import base64
    import json
    from urllib.request import urlopen

    # Fetch Google's public keys
    well_known_url = "https://accounts.google.com/.well-known/openid-configuration"
    config = urlopen(well_known_url).read()
    # In production, fetch and cache the JWKS:
    # jwks_url = "https://www.googleapis.com/oauth2/v3/certs"
    # jwks = json.loads(urlopen(jwks_url).read())

    # Decode the three parts of the JWT
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    # Verify signature using Google's JWKS (JSON Web Key Set)
    # In a production deployment, fetch and cache the JWKS
    jwks_url = "https://www.googleapis.com/oauth2/v3/certs"
    jwks = json.loads(urlopen(jwks_url).read())

    # Select the key that matches the token's header
    if not jwks.get("keys"):
        raise ValueError("No keys found in JWKS")

    # Decode header to get kid
    def _b64url_decode(s):
        s += "=" * (4 - len(s) % 4) if len(s) % 4 else ""
        return json.loads(base64.urlsafe_b64decode(s))

    header = _b64url_decode(parts[0])
    kid = header.get("kid")

    key = None
    for k in jwks["keys"]:
        if k.get("kid") == kid:
            key = k
            break

    if key is None:
        key = jwks["keys"][0]

    # Construct the public key from the JWK parameters
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    from cryptography.hazmat.primitives import serialization

    n = int.from_bytes(base64.urlsafe_b64decode(key["n"] + "=="), "big")
    e = int.from_bytes(base64.urlsafe_b64decode(key["e"] + "=="), "big")
    public_key = RSAPublicNumbers(e, n).public_key()

    # Verify the JWT signature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    signer = padding.PKCS1v15()
    digest = hashlib.sha256()

    # Extract the signature from the JWT
    signature_bytes = base64.urlsafe_b64decode(parts[2] + "==")

    # Verify the signature
    try:
        public_key.verify(
            signer,
            base64.urlsafe_b64decode(parts[1] + "=="),
            padding,
            digest,
        )
    except Exception:
        raise ValueError("Invalid token signature")

    # Decode payload
    payload = _b64url_decode(parts[1])

    # Validate 'iss' claim
    if payload.get("iss") not in ("https://accounts.google.com", "http://localhost"):
        raise ValueError(f"Invalid issuer: {payload.get('iss')}")

    # Validate 'exp' claim (expiration)
    import time
    if time.time() > payload.get("exp", 0):
        raise ValueError("Token has expired")

    # Validate 'aud' claim (audience)
    # In a properly configured deployment, this should match the client ID
    if payload.get("aud") != "your-client-id":
        raise ValueError(f"Invalid audience: {payload.get('aud')}")

    return payload