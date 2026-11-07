"""Alerts and in-app notifications.

Every route here is protected by the default-deny hook in ``src/security/auth.py``:
login is required, and state-changing requests additionally need the admin role and a
valid CSRF token. The only exceptions are the service worker and the web manifest,
which a browser fetches before the user is signed in.
"""
from __future__ import annotations

import logging
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)

from src.dashboard.db import get_db
from src.dashboard.streaming import sse_events
from src.database.camera_repository import CameraRepository
from src.database.people_repository import SettingsRepository
from src.errors import UserFacingError
from src.notifications.channels import CHANNEL_TYPES, EMAIL_RE, validate_channel
from src.notifications.defaults import (
    attach_to_default_rules,
    ensure_defaults,
    import_telegram_from_env,
)
from src.notifications.models import Notification
from src.notifications.repository import NotificationRepository
from src.notifications.rules import TRIGGER_LABELS, validate_rule
from src.notifications.service import ChannelFactory
from src.notifications.webpush import DEFAULT_CONTACT, ensure_vapid_keys

logger = logging.getLogger(__name__)

TEST_ALERT = Notification(
    title="Sentinel test alert",
    body="This is a test alert from Project Sentinel. If you can read this, the channel works.",
    event_type="TEST",
)


def _repo() -> NotificationRepository:
    return NotificationRepository(get_db(), current_app.config["SECRET_BOX"])


def _channels_in(conn) -> list[dict]:
    return CameraRepository(conn, current_app.config["SECRET_BOX"]).list()


def _channel_factory(repo: NotificationRepository):
    return current_app.config.get("CHANNEL_FACTORY") or ChannelFactory(repo)


def _data_dir() -> Path:
    return Path(current_app.config["DATABASE_PATH"]).parent


def _seed_defaults(app) -> None:
    """First run: one in-app channel and two useful rules, so a new install alerts at once.

    Runs once at startup (it is idempotent) so a fresh install does not need a page visit
    before the engine can queue alerts. Nothing here reads credentials from the environment.
    """
    from src.database.manager import DatabaseManager

    conn = DatabaseManager(app.config["DATABASE_PATH"]).get_connection()
    try:
        ensure_defaults(NotificationRepository(conn, app.config["SECRET_BOX"]))
    finally:
        conn.close()


def _migrate_telegram_env(repo: NotificationRepository) -> None:
    """Import a pre-existing .env Telegram setup exactly once, on first use of the alerts page.

    Kept out of app startup so that constructing the app never reads or stores credentials.
    """
    settings_repo = SettingsRepository(repo.conn)
    if settings_repo.get("telegram_env_imported") == "1":
        return
    try:
        if import_telegram_from_env(repo):
            logger.info("Imported the existing .env Telegram settings as an alert channel")
    finally:
        settings_repo.set("telegram_env_imported", "1")


def register_notification_routes(app) -> None:
    _seed_defaults(app)

    # ------------------------------------------------------------------ alerts page
    @app.get("/alerts")
    def alerts_page():
        repo = _repo()
        if repo.count_channels() == 0:  # database replaced/removed: restore the basics
            ensure_defaults(repo)
        _migrate_telegram_env(repo)

        channels = repo.list_channels()
        rules = repo.list_rules()
        cameras = _channels_in(get_db())

        cameras_by_id = {c["id"]: c["name"] for c in cameras}
        channels_by_id = {c["id"]: c["name"] for c in channels}
        for rule in rules:
            rule["trigger_label"] = TRIGGER_LABELS.get(rule["trigger"], rule["trigger"])
            rule["camera_label"] = cameras_by_id.get(rule["camera_id"], "All cameras")
            rule["channel_labels"] = [
                channels_by_id.get(channel_id, "(removed channel)") for channel_id in rule["channel_ids"]
            ]

        contact = SettingsRepository(get_db()).get("push_contact", DEFAULT_CONTACT)
        return render_template(
            "alerts.html",
            channels=channels,
            channel_types=CHANNEL_TYPES,
            rules=rules,
            trigger_labels=TRIGGER_LABELS,
            cameras=cameras,
            outbox=repo.recent_outbox(),
            push_count=repo.count_push_subscriptions(),
            push_installed=find_spec("pywebpush") is not None,
            push_contact=str(contact).replace("mailto:", ""),
        )

    @app.post("/alerts/channels")
    def add_alert_channel():
        type_ = (request.form.get("type") or "").strip()
        spec = CHANNEL_TYPES.get(type_)
        if spec is None or spec.get("builtin"):
            flash("Choose one of the listed channel types.", "error")
            return redirect(url_for("alerts_page"))

        config, error = validate_channel(type_, request.form)
        if error:
            flash(error, "error")
            return redirect(url_for("alerts_page"))

        repo = _repo()
        name = (request.form.get("name") or "").strip()[:50] or spec["label"][:50]
        channel_id = repo.add_channel(type_, name, config)
        if request.form.get("use_defaults"):
            attach_to_default_rules(repo, channel_id)
        flash(f"{name} added.", "success")
        return redirect(url_for("alerts_page"))

    @app.post("/alerts/channels/<int:channel_id>/test")
    def test_alert_channel(channel_id: int):
        repo = _repo()
        if repo.get_channel(channel_id) is None:
            abort(404)
        try:
            _channel_factory(repo)(channel_id, require_enabled=False).send(TEST_ALERT)
        except UserFacingError as error:
            flash(f"Test failed: {error}", "error")
        except Exception:
            logger.exception("Test alert delivery failed")
            flash("Test failed. Check the channel settings and the log for details.", "error")
        else:
            flash("Test sent.", "success")
        return redirect(url_for("alerts_page"))

    @app.post("/alerts/channels/<int:channel_id>/toggle")
    def toggle_alert_channel(channel_id: int):
        repo = _repo()
        channel = repo.get_channel(channel_id)
        if channel is None:
            abort(404)
        repo.set_channel_enabled(channel_id, not channel["enabled"])
        flash(f"{channel['name']} switched {'off' if channel['enabled'] else 'on'}.", "success")
        return redirect(url_for("alerts_page"))

    @app.post("/alerts/channels/<int:channel_id>/delete")
    def delete_alert_channel(channel_id: int):
        repo = _repo()
        channel = repo.get_channel(channel_id)
        if channel is None:
            abort(404)
        if channel["type"] == "inapp":
            flash("The in-app channel can't be deleted — it is where every alert is shown.", "error")
            return redirect(url_for("alerts_page"))
        repo.delete_channel(channel_id)
        flash(f"{channel['name']} deleted. Rules that used it were updated.", "success")
        return redirect(url_for("alerts_page"))

    @app.post("/alerts/rules")
    def add_alert_rule():
        repo = _repo()
        camera_ids = {camera["id"] for camera in _channels_in(get_db())}
        channel_ids = {channel["id"] for channel in repo.list_channels()}

        rule, error = validate_rule(request.form, camera_ids, channel_ids)
        if error:
            flash(error, "error")
        else:
            repo.add_rule(**rule)
            flash("Rule added.", "success")
        return redirect(url_for("alerts_page"))

    @app.post("/alerts/rules/<int:rule_id>/toggle")
    def toggle_alert_rule(rule_id: int):
        repo = _repo()
        rule = next((r for r in repo.list_rules() if r["id"] == rule_id), None)
        if rule is None:
            abort(404)
        repo.set_rule_enabled(rule_id, not rule["enabled"])
        flash(f"{rule['name']} switched {'off' if rule['enabled'] else 'on'}.", "success")
        return redirect(url_for("alerts_page"))

    @app.post("/alerts/rules/<int:rule_id>/delete")
    def delete_alert_rule(rule_id: int):
        repo = _repo()
        rule = next((r for r in repo.list_rules() if r["id"] == rule_id), None)
        if rule is None:
            abort(404)
        repo.delete_rule(rule_id)
        flash(f"{rule['name']} deleted.", "success")
        return redirect(url_for("alerts_page"))

    @app.post("/alerts/push-contact")
    def save_push_contact():
        email = (request.form.get("contact") or "").strip()
        if not EMAIL_RE.match(email) or len(email) > 254:
            flash("Enter a valid email address for push notifications.", "error")
        else:
            SettingsRepository(get_db()).set("push_contact", f"mailto:{email}")
            flash("Push contact saved.", "success")
        return redirect(url_for("alerts_page"))

    # ------------------------------------------------------------------ in-app inbox
    @app.get("/notifications")
    def notifications_page():
        repo = _repo()
        return render_template(
            "notifications.html", items=repo.list_inbox(), unread_count=repo.unread_count()
        )

    @app.post("/notifications/read")
    def mark_notifications_read():
        _repo().mark_all_read()
        flash("All notifications marked as read.", "success")
        return redirect(url_for("notifications_page"))

    @app.get("/notifications/<int:inbox_id>/snapshot.jpg")
    def notification_snapshot(inbox_id: int):
        row = _repo().get_inbox(inbox_id)
        if row is None or not row["snapshot_path"]:
            abort(404)
        base = Path(current_app.config["SNAPSHOT_DIR"]).resolve()
        path = Path(row["snapshot_path"]).resolve()
        if base not in path.parents or not path.is_file():
            abort(404)  # never serve a file outside the snapshots folder
        return send_file(path, mimetype="image/jpeg", max_age=0)

    # ------------------------------------------------------------------ JSON / SSE APIs
    @app.get("/api/notifications/unread")
    def notifications_unread():
        return jsonify(unread=_repo().unread_count())

    @app.get("/api/notifications/stream")
    def notifications_stream():
        repo, conn = _repo(), get_db()
        return Response(
            sse_events(repo, conn, repo.latest_inbox_id(), repo.unread_count()),
            mimetype="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
        )

    # ------------------------------------------------------------------ push (Web Push)
    @app.get("/api/push/public-key")
    def push_public_key():
        _, public_key = ensure_vapid_keys(_data_dir())
        return jsonify(publicKey=public_key)

    @app.post("/api/push/subscribe")
    def push_subscribe():
        data = request.get_json(silent=True) or {}
        endpoint = data.get("endpoint") if isinstance(data.get("endpoint"), str) else ""
        keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
        p256dh = keys.get("p256dh") if isinstance(keys.get("p256dh"), str) else ""
        auth = keys.get("auth") if isinstance(keys.get("auth"), str) else ""

        try:
            parts = urlsplit(endpoint.strip())
        except ValueError:
            parts = None
        if parts is None or parts.scheme != "https" or not parts.hostname or len(endpoint) > 2048:
            return jsonify(error="Push subscriptions must use an https:// endpoint."), 400
        if not (8 <= len(p256dh) <= 200 and 4 <= len(auth) <= 200):
            return jsonify(error="The browser sent invalid push keys."), 400

        repo = _repo()
        repo.add_push_subscription(endpoint.strip(), p256dh, auth)
        if repo.find_channel_by_type("webpush") is None:
            channel_id = repo.add_channel("webpush", "Phone / browser push", {})
            attach_to_default_rules(repo, channel_id)
        return jsonify(ok=True)

    # ------------------------------------------------------------------ PWA files
    @app.get("/sw.js")
    def service_worker():
        response = send_from_directory(
            current_app.static_folder, "sw.js", mimetype="text/javascript", max_age=0
        )
        # A service worker at the root may control every page.
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.get("/manifest.webmanifest")
    def manifest():
        return send_from_directory(
            current_app.static_folder,
            "manifest.webmanifest",
            mimetype="application/manifest+json",
            max_age=0,
        )
