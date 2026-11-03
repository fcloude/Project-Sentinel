from flask import (
    Response,
    send_file,
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
from src.dashboard.db import close_db, get_db
from src.dashboard.guards import LoginRateLimiter, login_required
from src.dashboard.streaming import mjpeg_frames
from src.database.camera_repository import CameraRepository
from src.database.people_repository import PeopleRepository, SettingsRepository
from src.database.repository import EventRepository
from src.errors import UserFacingError
from src.faces.backends import MODEL_ID
from src.faces.service import DEFAULT_STRICTNESS, STRICTNESS, get_face_service

CAMERA_TEST_HELP = (
    "Could not get a picture from this camera. Check the address and login, and "
    "that the camera is on and reachable from this computer. For a USB camera, "
    "stop Sentinel first so the camera is free."
)


MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 8 * 1024 * 1024


def register_routes(app):
    limiter = LoginRateLimiter()

    def face_service():
        factory = current_app.config.get("FACE_SERVICE_FACTORY") or get_face_service
        return factory()

    def read_photos():
        """Uploaded files -> ([(name, bytes)], [problems])."""
        photos, problems = [], []
        for upload in request.files.getlist("photos")[:MAX_PHOTOS]:
            if not upload or not upload.filename:
                continue
            name = upload.filename.replace("\\", "/").split("/")[-1][:60]
            data = upload.read(MAX_PHOTO_BYTES + 1)
            if len(data) > MAX_PHOTO_BYTES:
                problems.append(f"{name}: the photo is larger than 8 MB.")
                continue
            photos.append((name, data))
        return photos, problems

    @app.context_processor
    def nav_counts():
        if g.get("user") is None:
            return {}
        return {"unknown_count": PeopleRepository(get_db()).count_unknown()}

    def engine_status():
        engine = current_app.config.get("ENGINE")
        if engine is None:
            return {
                "running": False,
                "thread_alive": False,
                "loading": False,
                "error": None,
                "cameras": [],
            }
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
            cameras=cameras_repo().list(),
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
                flash(
                    f"Camera '{name}' added. Press Restart on the Dashboard to start using it.",
                    "success",
                )
                return redirect(url_for("cameras"))

        kinds = [k for k in KINDS if k != "file" or current_app.config["ALLOW_FILE_SOURCES"]]
        return render_template("cameras.html", cameras=repo.list(), kinds=kinds)

    @app.post("/cameras/<int:camera_id>/delete")
    @login_required
    def delete_camera(camera_id):
        cameras_repo().delete(camera_id)
        flash("Camera removed. Press Restart on the Dashboard to apply.", "success")
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

    @app.get("/cameras/<int:camera_id>/stream.mjpg")
    @login_required
    def camera_stream(camera_id):
        engine = current_app.config.get("ENGINE")
        get_worker = getattr(engine, "get_worker", None)
        worker = get_worker(camera_id) if get_worker else None
        if worker is None:
            abort(404)

        close_db()  # the stream can last a long time; free the database connection now
        return Response(
            mjpeg_frames(worker),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    # ------------------------------------------------------------------
    # People (known faces)
    # ------------------------------------------------------------------

    @app.route("/people", methods=["GET", "POST"])
    @login_required
    def people():
        repo = PeopleRepository(get_db())

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            consent = request.form.get("consent") == "on"
            photos, problems = read_photos()
            for problem in problems:
                flash(problem, "error")

            error = None
            if not 1 <= len(name) <= 50:
                error = "Give the person a name (1-50 characters)."
            elif not consent:
                error = "Please confirm that this person agreed to be recognised."
            elif not photos:
                error = "Add at least one photo."
            elif repo.person_exists(name):
                error = f"'{name}' already exists. Use 'Add photos' on their card instead."

            if error:
                flash(error, "error")
            else:
                try:
                    service = face_service()
                    person_id = repo.create_person(name, consent=True)
                    outcomes = service.enroll_photos(person_id, photos)
                except UserFacingError as problem:
                    flash(str(problem), "error")
                else:
                    for outcome in outcomes:
                        if not outcome.ok:
                            flash(f"{outcome.filename}: {outcome.reason}", "error")
                    added = sum(1 for o in outcomes if o.ok)
                    if added == 0:
                        repo.delete_person(person_id)
                        flash("None of the photos could be used, so nobody was added.", "error")
                    else:
                        flash(f"{name} added with {added} photo(s).", "success")
                        return redirect(url_for("people"))

        return render_template(
            "people.html",
            people=repo.list_people(),
            stale=repo.count_stale(MODEL_ID),
        )

    @app.post("/people/<int:person_id>/photos")
    @login_required
    def add_person_photos(person_id):
        repo = PeopleRepository(get_db())
        person = repo.get_person(person_id)
        if person is None:
            abort(404)

        photos, problems = read_photos()
        for problem in problems:
            flash(problem, "error")

        if not photos:
            flash("Choose at least one photo.", "error")
            return redirect(url_for("people"))

        try:
            outcomes = face_service().enroll_photos(person_id, photos)
        except UserFacingError as problem:
            flash(str(problem), "error")
            return redirect(url_for("people"))

        for outcome in outcomes:
            if not outcome.ok:
                flash(f"{outcome.filename}: {outcome.reason}", "error")
        added = sum(1 for o in outcomes if o.ok)
        if added:
            flash(f"Added {added} photo(s) to {person['name']}.", "success")
        return redirect(url_for("people"))

    @app.post("/people/<int:person_id>/delete")
    @login_required
    def delete_person(person_id):
        PeopleRepository(get_db()).delete_person(person_id)
        face_service().reload()
        flash("Person and all their face data deleted.", "success")
        return redirect(url_for("people"))

    # ------------------------------------------------------------------
    # Unknown faces inbox
    # ------------------------------------------------------------------

    @app.route("/unknown")
    @login_required
    def unknown_faces():
        repo = PeopleRepository(get_db())
        camera_names = {c["id"]: c["name"] for c in cameras_repo().list()}
        return render_template(
            "unknown.html",
            unknowns=repo.list_unknown(),
            people=repo.list_people(),
            camera_names=camera_names,
        )

    @app.get("/unknown/<int:unknown_id>/crop.jpg")
    @login_required
    def unknown_crop(unknown_id):
        row = PeopleRepository(get_db()).get_unknown(unknown_id)
        if row is None:
            abort(404)

        from pathlib import Path

        path = Path(row["crop_path"]).resolve()
        allowed = face_service().unknown_dir.resolve()
        if allowed not in path.parents or not path.is_file():
            abort(404)  # never serve a file outside the unknown-faces folder

        return send_file(path, mimetype="image/jpeg")

    @app.post("/unknown/<int:unknown_id>/name")
    @login_required
    def name_unknown(unknown_id):
        existing = request.form.get("person_id", "").strip()
        try:
            face_service().promote_unknown(
                unknown_id,
                name=request.form.get("name", ""),
                person_id=int(existing) if existing.isdigit() else None,
                consent=request.form.get("consent") == "on",
            )
        except UserFacingError as problem:
            flash(str(problem), "error")
        else:
            flash("Saved. This person will be recognised from now on.", "success")
        return redirect(url_for("unknown_faces"))

    @app.post("/unknown/<int:unknown_id>/dismiss")
    @login_required
    def dismiss_unknown(unknown_id):
        face_service().dismiss_unknown(unknown_id)
        flash("Dismissed and deleted.", "success")
        return redirect(url_for("unknown_faces"))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings_page():
        settings = SettingsRepository(get_db())

        if request.method == "POST":
            level = request.form.get("strictness", "")
            if level in STRICTNESS:
                settings.set("face_strictness", level)
                face_service().reload()
                flash("Settings saved.", "success")
            else:
                flash("Choose one of the listed options.", "error")
            return redirect(url_for("settings_page"))

        return render_template(
            "settings.html",
            strictness=settings.get("face_strictness", DEFAULT_STRICTNESS),
            levels=[
                ("strict", "Strict", "Fewest mistakes, but may call a known person 'Unknown' more often."),
                ("balanced", "Balanced", "Recommended starting point."),
                ("lenient", "Lenient", "Recognises people more easily, with a higher risk of mixing people up."),
            ],
        )

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
