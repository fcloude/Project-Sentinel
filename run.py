from src.main import engine
from src.dashboard import create_app


app = create_app(engine)


if __name__ == "__main__":

    print("=" * 50)
    print("        Project Sentinel V1")
    print("=" * 50)
    print("Dashboard : http://127.0.0.1:5000")
    print("Engine    : Ready")
    print("=" * 50)

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
    )