import os
import sys

from src.app_logging import get_logger
from src.security.config import SecurityConfig, SecurityConfigError, _is_first_run, _load_config, _save_config, _generate_secure_secrets

logger = get_logger("sentinel.run")

# --- First-run / configuration loading handling ---
config_path = os.path.join(os.environ.get("APPDATA", ""), "Sentinel", "config.json")
needs_first_run = not os.path.exists(config_path)

env = dict(os.environ)  # copy env vars

if needs_first_run:
    # Generate secure secrets for this installation
    secret_key, encryption_keys = _generate_secure_secrets()
    
    # Set environment variables for this installation
    env["SECRET_KEY"] = secret_key
    env["SENTINEL_ENCRYPTION_KEYS"] = encryption_keys
    env["HOST"] = "127.0.0.1"
    env["PORT"] = "5000"
    
    # Save base configuration
    base_config = {
        "SECRET_KEY": secret_key,
        "SENTINEL_ENCRYPTION_KEYS": encryption_keys,
        "HOST": "127.0.0.1",
        "PORT": 5000,
        "GOOGLE_OAUTH_CLIENT_ID": "",
        "GOOGLE_OAUTH_CLIENT_SECRET": "",
        "GOOGLE_OAUTH_REDIRECT_URI": "",
    }
    _save_config(base_config)
    
    # Show first-run guidance
    print(f"\n[FIRST RUN] Project Sentinel is being started for the first time.")
    print(f"[FIRST RUN] Configuration generated at: {config_path}")
    print(f"[FIRST RUN] Google OAuth 2.0 credentials are required for the public V1 product.")
    print(f"[FIRST RUN] Please obtain credentials from https://console.cloud.google.com/")
    print(f"[FIRST RUN] Set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET,")
    print(f"[FIRST RUN] and GOOGLE_OAUTH_REDIRECT_URI environment variables.")
    print()
else:
    # Load existing config from application data
    saved = _load_config()
    if saved:
        env["SECRET_KEY"] = saved.get("SECRET_KEY", env.get("SECRET_KEY", ""))
        env["SENTINEL_ENCRYPTION_KEYS"] = saved.get(
            "SENTINEL_ENCRYPTION_KEYS", env.get("SENTINEL_ENCRYPTION_KEYS", "")
        )
        env["HOST"] = saved.get("HOST", env.get("HOST", "127.0.0.1"))
        env["PORT"] = str(saved.get("PORT", int(env.get("PORT", 5000))))
        # Load Google OAuth from config if not already set via environment
        env.setdefault("GOOGLE_OAUTH_CLIENT_ID", saved.get("GOOGLE_OAUTH_CLIENT_ID", ""))
        env.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", saved.get("GOOGLE_OAUTH_CLIENT_SECRET", ""))
        env.setdefault("GOOGLE_OAUTH_REDIRECT_URI", saved.get("GOOGLE_OAUTH_REDIRECT_URI", ""))
# Load configuration - from environment variables (override saved config)
configuration_error = None
try:
    config = SecurityConfig.from_env(env)  # refuses to start on missing/unsafe configuration
except SecurityConfigError as exc:
    configuration_error = exc

if configuration_error and needs_first_run:
    # On first run, show guidance and exit gracefully
    print(f"\n[FIRST RUN] {configuration_error}\n")
    print(f"[FIRST RUN] Please set the required Google OAuth credentials and restart.")
    sys.exit(1)
elif configuration_error:
    # On subsequent runs, refuse to start
    print(f"\n[SECURITY] Refusing to start: {configuration_error}\n", file=sys.stderr)
    sys.exit(1)

from src.dashboard import create_app  # noqa: E402  (after config validation on purpose)
from src.main import engine  # noqa: E402

app = create_app(engine, config)


def main() -> None:
    scheme = "https" if config.https else "http"
    print("=" * 50)
    print("        Project Sentinel")
    print("=" * 50)
    print(f"Dashboard : {scheme}://{config.host}:{config.port}")
    print("=" * 50)
    try:
        from waitress import serve  # production-grade WSGI server
    except ImportError:
        logger.warning("waitress is not installed: using Flask's development server. Do NOT use it in production "
                       "(pip install waitress).")
        app.run(host=config.host, port=config.port, debug=False, use_reloader=False, threaded=True)
    else:
        serve(app, host=config.host, port=config.port, threads=8, url_scheme=scheme)


if __name__ == "__main__":
    main()
