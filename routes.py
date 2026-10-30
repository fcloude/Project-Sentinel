from flask import (
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from src.auth.users import UserRepository, validate_password, validate_username
from src.camera.camera_exceptions import CameraError
from src.camera.opencv_source import grab_jpeg
from src.camera.url_utils import KINDS, capture_source, validate_source
from src.dashboard.db import get_db
from src.dashboard.guards import LoginRateLimiter, login_required
from src.database.camera_repository import CameraRepository
from src.database.repository import EventRepository

CAMERA_TEST_HELP = (
    "Could not get a picture from this camera. Check the address and login, and "
    "that the camera is on and reachable from this computer. For a USB camera, "
    "stop Sentinel first so the camera is free."
)


def register_routes(app):
    limiter = LoginRateLimiter()

    def engine_status():
        engine = current_app.config.get("ENGINE")
        if engine is None:
            return {"running": False, "thread_alive": False}
        return engine.status

    def cameras_repo():
        return CameraRepository(get_db(), current_app.config["SECRET_BOX"])

    # ------------------------------------------------------------------
    # Who is logged in? First run goes to the setup wizard.
    # ------------------------------------------------------------------

    @app.before_request
    def load_user():
        g.user = None

        if request.endpoint in (None, "static"):
            return

        users = UserRepository(get_db())

        user_id = session.get("user_id")
        if user_id:
            g.user = users.get_by_id(user_id)

        if users.count() == 0 and request.endpoint not in ("setup", "health"):
            return redirect(url_for("setup"))

    # ------------------------------------------------------------------
    # Setup, login, logout
    # ------------------------------------------------------------------

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        users = UserRepository(get_db())

        if users.count() > 0:
            return redirect(url_for("login"))

        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")

            error = (
                validate_username(username)
                or validate_password(password)
                or (None if password == confirm else "Passwords do not match.")
            )

            if error:
                flash(error, "error")
            else:
                user_id = users.create_first_admin(username, password)
                if user_id is None:
                    return redirect(url_for("login"))
                session.clear()
                session["user_id"] = user_id
                session.permanent = True
                return redirect(url_for("index"))

        return render_template("setup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("index"))

        if request.method == "POST":
            address = request.remote_addr or "unknown"

            if limiter.is_blocked(address):
                flash("Too many failed attempts. Please wait a few minutes.", "error")
                return render_template("login.html"), 429

            user = UserRepository(get_db()).verify(
                request.form.get("username", ""),
                request.form.get("password", ""),
            )

            if user is None:
                limiter.record_failure(address)
                flash("Invalid username or password.", "error")
                return render_template("login.html"), 401

            limiter.reset(address)
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            return redirect(url_for("index"))

        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @app.route("/")
    @login_required
    def index():
        conn = get_db()
        events = EventRepository(conn)
        return render_template(
            "index.html",
            status=engine_status(),
            camera_count=cameras_repo().count(),
            event_count=events.count(),
            events=events.recent(10),
        )

    @app.route("/events")
    @login_required
    def events_page():
        return render_template("events.html", events=EventRepository(get_db()).recent(100))

    @app.post("/engine/<action>")
    @login_required
    def engine_control(action):
        engine = current_app.config.get("ENGINE")
        if engine is None:
            flash("The detection engine is not available.", "error")
            return redirect(url_for("index"))

        if action == "start":
            if not engine.running:
                engine.start()
            flash("Sentinel started.", "success")
        elif action == "stop":
            if engine.running:
                engine.stop()
            flash("Sentinel stopped.", "success")
        elif action == "restart":
            engine.restart()
            flash("Sentinel restarted.", "success")
        else:
            abort(404)

        return redirect(url_for("index"))

    # ------------------------------------------------------------------
    # Cameras
    # ------------------------------------------------------------------

    @app.route("/cameras", methods=["GET", "POST"])
    @login_required
    def cameras():
        repo = cameras_repo()

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            kind = request.form.get("kind", "")
            source, error = validate_source(
                kind,
                request.form.get("source", ""),
                current_app.config["ALLOW_FILE_SOURCES"],
            )

            if not 1 <= len(name) <= 50:
                error = "Give the camera a name (1-50 characters)."

            if error:
                flash(error, "error")
            else:
                repo.add(name, kind, source)
                flash(f"Camera '{name}' added.", "success")
                return redirect(url_for("cameras"))

        kinds = [k for k in KINDS if k != "file" or current_app.config["ALLOW_FILE_SOURCES"]]
        return render_template("cameras.html", cameras=repo.list(), kinds=kinds)

    @app.post("/cameras/<int:camera_id>/delete")
    @login_required
    def delete_camera(camera_id):
        cameras_repo().delete(camera_id)
        flash("Camera removed.", "success")
        return redirect(url_for("cameras"))

    @app.post("/api/cameras/test")
    @login_required
    def test_camera():
        kind = request.form.get("kind", "")
        source, error = validate_source(
            kind, request.form.get("source", ""), current_app.config["ALLOW_FILE_SOURCES"]
        )
        if error:
            return jsonify(error=error), 400

        try:
            jpeg = grab_jpeg(capture_source(kind, source))
        except CameraError:
            return jsonify(error=CAMERA_TEST_HELP), 400

        return Response(jpeg, mimetype="image/jpeg")

    # ------------------------------------------------------------------
    # Status APIs
    # ------------------------------------------------------------------

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/status")
    @login_required
    def status():
        return jsonify(engine_status())
