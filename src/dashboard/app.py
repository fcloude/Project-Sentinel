from flask import Flask

from src.dashboard.routes import register_routes


def create_app(engine):

    app = Flask(__name__)

    app.config["ENGINE"] = engine

    register_routes(app)

    return app