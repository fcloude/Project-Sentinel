from flask import render_template
from flask import current_app, jsonify, redirect, url_for

from src.dashboard.services.dashboard_service import DashboardService


service = DashboardService()

@app.route("/start", methods=["POST"])
def start_sentinel():

    engine = current_app.config["ENGINE"]

    if not engine.running:
        engine.start()

    return redirect(url_for("index"))


@app.route("/stop", methods=["POST"])
def stop_sentinel():

    engine = current_app.config["ENGINE"]

    if engine.running:
        engine.stop()

    return redirect(url_for("index"))


@app.route("/restart", methods=["POST"])
def restart_sentinel():

    engine = current_app.config["ENGINE"]

    engine.restart()

    return redirect(url_for("index"))


@app.route("/api/status")
def status():

    engine = current_app.config["ENGINE"]

    return jsonify(engine.status)

def register_routes(app):

    @app.route("/")
    def index():

        return render_template(
            "index.html",
            state=service.get_dashboard_state(),
        )

    @app.route("/cameras")
    def cameras():

        return render_template(
            "cameras.html",
            cameras=service.get_cameras(),
        )

    @app.route("/faces")
    def faces():

        return render_template(
            "faces.html",
            faces=service.get_faces(),
        )

    @app.route("/events")
    def events():

        return render_template(
            "events.html",
            events=service.get_recent_events(),
        )

    @app.route("/settings")
    def settings():

        return render_template(
            "settings.html",
            settings=service.get_settings(),
        )