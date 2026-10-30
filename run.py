from src.config import settings
from src.dashboard import create_app
from src.main import engine

app = create_app(engine)


if __name__ == "__main__":
    print("=" * 50)
    print("        Project Sentinel")
    print("=" * 50)
    print(f"Dashboard : http://{settings.host}:{settings.port}")

    if settings.host not in ("127.0.0.1", "localhost"):
        print("WARNING   : dashboard is reachable from your network.")
        print("            Anyone who can reach this address can try to log in.")

    print("=" * 50)

    app.run(host=settings.host, port=settings.port, debug=False, threaded=True)
