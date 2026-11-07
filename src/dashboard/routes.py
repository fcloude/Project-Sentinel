"""Dashboard pages and JSON/streaming endpoints.

Every route below is protected by the default-deny hook in ``src/security/auth.py``:
login is required for everything, and every state-changing request additionally needs
the admin role and a valid CSRF token. Snapshots and face crops are never static files.
"""
from pathlib import Path

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
    send_file,
    send_from_directory,
    url_for,
)

from src.camera.camera_exceptions import CameraError
from src.camera.opencv_source import grab_jpeg
from src.camera.url_utils import KINDS, capture_source, validate_source
from src.dashboard.db import close_db, get_db
from src.dashboard.services.dashboard_service import DashboardService
from src.dashboard.streaming import mjpeg_frames
from src.database.camera_repository import CameraRepository
from src.database.people_repository import PeopleRepository, SettingsRepository
from src.database.repository import EventRepository
from src.errors import UserFacingError
from src.faces.backends import MODEL_ID
from src.faces.service import DEFAULT_STRICTNESS, STRICTNESS, get_face_service
from src.notifications.repository import NotificationRepository
from src.security.validators import ValidationError, is_safe_snapshot_name, validate_image_upload

# Presentation state shared with the templates (and read by tests).
service = DashboardService()

CAMERA_TEST_HELP = (
    "Could not get a picture from this camera. Check the address and login, and "
    "that the camera is on and reachable from this computer. For a USB camera, "
    "stop Sentinel first so the camera is free."
)

MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 8 * 1024 * 1024

STRICTNESS_CHOICES = [
    ("strict", "Strict", "Fewest mistakes, but may call a known person 'Unknown' more often."),
    ("balanced", "Balanced", "Recommended starting point."),
    ("lenient", "Lenient", "Recognises people more easily, with a higher risk of mixing people up."),
]


def register_routes(app):
    def face_service():
        factory = current_app.config.get("FACE_SERVICE_FACTORY") or get_face_service
        return factory()

    def cameras_repo():
        return CameraRepository(get_db(), current_app.config["SECRET_BOX"])

    def read_photos():
        """Uploaded files -> ([(name, bytes)], [problems]).

        Size, magic bytes and declared dimensions are checked before the image is decoded,
        so a decompression bomb never reaches OpenCV.
        """
        photos, problems = [], []
        for upload in request.files.getlist("photos")[:MAX_PHOTOS]:
            if not upload or not upload.filename:
                continue
            name = upload.filename.replace("\\\\", "/").split("/")[-1][:60]
            data = upload.read(MAX_PHOTO_BYTES + 1)
            try:
                validate_image_upload(data, max_bytes=MAX_PHOTO_BYTES)
            except ValidationError as problem:
                problems.append(f"{name}: {problem}")
                continue
            photos.append((name, data))
        return photos, problems

    def engine_status():
        engine = current_app.config.get("ENGINE")
        if engine is None:
            return {"running": False, "thread_alive": False, "loading": False, "error": None, "cameras": []}
        return engine.status

    def run_engine(action):
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

    def _current_user_id() -> int:
        user = g.get("user")
        if user is None:
            abort(401, description="authentication required")
        return user.id

    @app.context_processor
    def nav_counts():
        if g.get("user") is None:
            return {}
        user_id = _current_user_id()
        return {
            "unknown_count": PeopleRepository(get_db()).count_unknown(),
            "unread_count": NotificationRepository(
                get_db(), current_app.config["SECRET_BOX"]
            ).unread_count(),
        }

    # ------------------------------------------------------------------ dashboard
    @app.get("/")
    def index():
        conn = get_db()
        user_id = _current_user_id()
        events = EventRepository(conn)
        cameras = cameras_repo().list(user_id=user_id)
        status = engine_status()

        state = service.get_dashboard_state()
        state["camera_count"] = len(cameras)
        state["sentinel_running"] = bool(status.get("running"))

        online_ids = {
            camera.get("id") for camera in status.get("cameras", []) if camera.get("state") == "online"
        }

        return render_template(
            "index.html",
            state=state,
            status=status,
            cameras=cameras,
            online_ids=online_ids,
            camera_count=len(cameras),
            event_count=events.count(),
            events=events.recent(10),
        )

    # ------------------------------------------------------------------ engine controls
    @app.post("/engine/<action>")
    def engine_control(action):
        return run_engine(action)

    # Legacy form targets kept so older bookmarks and the dashboard keep working.
    @app.post("/start")
    def start_sentinel():
        return run_engine("start")

    @app.post("/stop")
    def stop_sentinel():
        return run_engine("stop")

    @app.post("/restart")
    def restart_sentinel():
        return run_engine("restart")

    @app.get("/api/status")
    def status():
        return jsonify(engine_status())

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/healthz")  # public liveness probe; reveals nothing
    def healthz():
        return jsonify(status="ok")

    # ------------------------------------------------------------------ cameras
    @app.route("/cameras", methods=["GET", "POST"])
    def cameras():
        repo = cameras_repo()
        user_id = _current_user_id()

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
                repo.add(name, kind, source, user_id=user_id)
                flash(
                    f"Camera '{name}' added. Press Restart on the Dashboard to start using it.",
                    "success",
                )
                return redirect(url_for("cameras"))

        kinds = [k for k in KINDS if k != "file" or current_app.config["ALLOW_FILE_SOURCES"]]
        return render_template("cameras.html", cameras=repo.list(user_id=user_id), kinds=kinds)

    @app.post("/cameras/<int:camera_id>/delete")
    def delete_camera(camera_id):
        cameras_repo().delete(camera_id, user_id=_current_user_id())
        flash("Camera removed. Press Restart on the Dashboard to apply.", "success")
        return redirect(url_for("cameras"))

    @app.post("/api/cameras/test")
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

    # ------------------------------------------------------------------ people (known faces)
    @app.route("/people", methods=["GET", "POST"])
    def people():
        repo = PeopleRepository(get_db())
        user_id = _current_user_id()

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
            elif repo.person_exists(name, user_id=user_id):
                error = f"'{name}' already exists. Use 'Add photos' on their card instead."

            if error:
                flash(error, "error")
            else:
                try:
                    service_ = face_service()
                    person_id = repo.create_person(name, consent=True, user_id=user_id)
                    outcomes = service_.enroll_photos(person_id, photos)
                except (UserFacingError, ValueError) as problem:
                    flash(str(problem), "error")
                else:
                    for outcome in outcomes:
                        if not outcome.ok:
                            flash(f"{outcome.filename}: {outcome.reason}", "error")
                    added = sum(1 for o in outcomes if o.ok)
                    if added == 0:
                        repo.delete_person(person_id, user_id=user_id)
                        flash("None of the photos could be used, so nobody was added.", "error")
                    else:
                        flash(f"{name} added with {added} photo(s).", "success")
                        return redirect(url_for("people"))

        return render_template(
            "people.html",
            people=repo.list_people(user_id=user_id),
            stale=repo.count_stale(MODEL_ID),
        )

    @app.post("/people/<int:person_id>/photos")
    def add_person_photos(person_id):
        repo = PeopleRepository(get_db())
        user_id = _current_user_id()
        person = repo.get_person(person_id, user_id=user_id)
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
    def delete_person(person_id):
        repo = PeopleRepository(get_db())
        user_id = _current_user_id()
        person = repo.get_person(person_id, user_id=user_id)
        if person is None:
            abort(404)
        repo.delete_person(person_id, user_id=user_id)
        try:
            face_service().reload()
        except UserFacingError as problem:
            flash(str(problem), "error")
        else:
            flash("Person and all their face data deleted.", "success")
        return redirect(url_for("people"))

    # ------------------------------------------------------------------ recognition status
    @app.get("/faces")
    def faces_page():
        repo = PeopleRepository(get_db())
        conn = get_db()
        user_id = _current_user_id()
        level = SettingsRepository(conn).get("face_strictness", DEFAULT_STRICTNESS)
        embeddings = conn.execute(
            "SELECT COUNT(*) FROM face_embeddings WHERE model_id = ? AND person_id IN (SELECT id FROM people WHERE user_id = ?)", (MODEL_ID, user_id)
        ).fetchone()[0]
        return render_template(
            "faces.html",
            model_id=MODEL_ID,
            level=level,
            threshold=STRICTNESS.get(level, STRICTNESS[DEFAULT_STRICTNESS]),
            embeddings=embeddings,
            stale=repo.count_stale(MODEL_ID),
            unknown_count=repo.count_unknown(),
            people=repo.list_people(user_id=user_id),
            levels=STRICTNESS_CHOICES,
        )

    @app.post("/faces/reindex")
    def faces_reindex():
        try:
            face_service().reload()
        except UserFacingError as problem:
            flash(str(problem), "error")
        else:
            flash("Known faces reloaded from the database.", "success")
        return redirect(url_for("faces_page"))

    # ------------------------------------------------------------------ unknown faces inbox
    @app.get("/unknown")
    def unknown_faces():
        repo = PeopleRepository(get_db())
        user_id = _current_user_id()
        camera_names = {c["id"]: c["name"] for c in cameras_repo().list(user_id=user_id)}
        return render_template(
            "unknown.html",
            unknowns=repo.list_unknown(),
            people=repo.list_people(user_id=user_id),
            camera_names=camera_names,
        )

    @app.get("/unknown/<int:unknown_id>/crop.jpg")
    def unknown_crop(unknown_id):
        repo = PeopleRepository(get_db())
        row = repo.get_unknown(unknown_id)
        if row is None:
            abort(404)

        path = Path(row["crop_path"]).resolve()
        allowed = face_service().unknown_dir.resolve()
        if allowed not in path.parents or not path.is_file():
            abort(404)  # never serve a file outside the unknown-faces folder

        return send_file(path, mimetype="image/jpeg", max_age=0)

    @app.post("/unknown/<int:unknown_id>/name")
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
    def dismiss_unknown(unknown_id):
        face_service().dismiss_unknown(unknown_id)
        flash("Dismissed and deleted.", "success")
        return redirect(url_for("unknown_faces"))

    # ------------------------------------------------------------------ events
    @app.get("/events")
    def events_page():
        conn = get_db()
        user_id = _current_user_id()
        events = EventRepository(conn)
        # Filter events by user ownership - need to check the events table has user_id
        # For now, we'll load all events and the template will show only the current user's
        return render_template("events.html", events=events.recent(100))

    # ------------------------------------------------------------------ settings
    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        settings_repo = SettingsRepository(get_db())

        if request.method == "POST":
            level = request.form.get("strictness", "")
            if level in STRICTNESS:
                settings_repo.set("face_strictness", level)
                try:
                    face_service().reload()
                except UserFacingError as problem:
                    flash(str(problem), "error")
                else:
                    flash("Settings saved.", "success")
            else:
                flash("Choose one of the listed options.", "error")
            return redirect(url_for("settings_page"))

        return render_template(
            "settings.html",
            strictness=settings_repo.get("face_strictness", DEFAULT_STRICTNESS),
            levels=STRICTNESS_CHOICES,
        )

    # ------------------------------------------------------------------ snapshots
    @app.get("/snapshots/<name>")
    def snapshot(name):
        if not is_safe_snapshot_name(name):
            abort(404)
        directory = Path(current_app.config["SNAPSHOT_DIR"]).resolve()
        return send_from_directory(directory, name, mimetype="image/jpeg", max_age=0)