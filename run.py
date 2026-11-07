import sys

from src.app_logging import get_logger
from src.security.config import SecurityConfig, SecurityConfigError

logger = get_logger("sentinel.run")

try:
    config = SecurityConfig.from_env()  # refuses to start on missing/unsafe configuration
except SecurityConfigError as exc:
    print(f"\n[SECURITY] Refusing to start: {exc}\n", file=sys.stderr)
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
