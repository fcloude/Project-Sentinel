"""Admin Control Center routes (``/admin``).

Reads only real application data: the ``events`` table for activity, the ``cameras``
registry for devices, ``unknown_faces`` for the review inbox, and the shared
``users``/``audit_log`` tables through :class:`~src.security.store.SecurityStore`.
No route here authenticates a user: session handling lives in ``src.security.auth``.
"""
from __future__ import annotations

import sqlite3

from flask import abort, current_app, flash, g, redirect, render_template, request, url_for

from src.admin import admin_bp
from src.admin.auth import audit, require_admin, require_role, store
from src.config.loader import load_settings
from src.dashboard.db import get_db
from src.security import passwords


# Only these tables may be counted; the name is still interpolated, so keep the allow-list
# authoritative (an admin request can never supply it).
_COUNTABLE_TABLES = frozenset({
    "events", "cameras", "people", "unknown_faces", "face_embeddings",
})


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    if table not in _COUNTABLE_TABLES:
        raise ValueError("Unsupported table")
    if not _table_exists(conn, table):
        return 0
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # sentinel-ok: allow-listed


def _current_id() -> int | None:
    user = g.get("user")
    return user.id if user else None


# ── Dashboard ─────────────────────────────────────────────────────
@admin_bp.get("/")
@require_admin
def dashboard():
    conn = get_db()
    stats = {
        "total_events": _count(conn, "events"),
        "total_cameras": _count(conn, "cameras"),
        "total_people": _count(conn, "people"),
        "unknown_faces": _count(conn, "unknown_faces"),
        "embeddings": _count(conn, "face_embeddings"),
        "users": len(store().list_users()),
        "audit_entries": len(store().recent_audit(1000)),
    }

    recent_events = []
    if _table_exists(conn, "events"):
        recent_events = conn.execute(
            "SELECT event_type, source, message, timestamp FROM events ORDER BY timestamp DESC LIMIT 10"
        ).fetchall()

    recent_audit = [
        (row["username"], row["action"], row["detail"], row["ts"])
        for row in store().recent_audit(10)
    ]

    cameras = []
    if _table_exists(conn, "cameras"):
        cameras = conn.execute(
            "SELECT name, kind, enabled FROM cameras ORDER BY name COLLATE NOCASE"
        ).fetchall()

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent_events=recent_events,
        recent_audit=recent_audit,
        cameras=cameras,
    )


# ── Events ────────────────────────────────────────────────────────
@admin_bp.get("/events")
@require_admin
def events():
    conn = get_db()
    rows = []
    if _table_exists(conn, "events"):
        rows = conn.execute(
            "SELECT event_id, event_type, source, message, timestamp "
            "FROM events ORDER BY timestamp DESC LIMIT 500"
        ).fetchall()
    return render_template("admin/events.html", events=rows)


# ── Devices ───────────────────────────────────────────────────────
@admin_bp.get("/devices")
@require_admin
def devices():
    conn = get_db()
    cameras = []
    if _table_exists(conn, "cameras"):
        cameras = conn.execute(
            "SELECT id, name, kind, enabled, detection_fps, created_at "
            "FROM cameras ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return render_template("admin/devices.html", cameras=cameras)


# ── Unknown Faces ─────────────────────────────────────────────────
@admin_bp.get("/unknown-faces")
@require_admin
def unknown_faces():
    conn = get_db()
    rows = []
    if _table_exists(conn, "unknown_faces"):
        rows = conn.execute(
            "SELECT id, camera_id, seen_at, seen_count, crop_path "
            "FROM unknown_faces ORDER BY seen_at DESC LIMIT 200"
        ).fetchall()
    return render_template("admin/unknown_faces.html", faces=rows)


# ── Audit Log ─────────────────────────────────────────────────────
@admin_bp.get("/audit")
@require_admin
def audit_log():
    records = [
        (row["username"], row["action"], row["detail"], row["ip"], row["ts"])
        for row in store().recent_audit(1000)
    ]
    return render_template("admin/audit.html", records=records)


# ── User Management ───────────────────────────────────────────────
@admin_bp.get("/admins")
@require_admin
@require_role("admin")
def admin_users():
    rows = get_db().execute(
        "SELECT id, username, role, active, created_at, last_login_at FROM users ORDER BY id"
    ).fetchall()
    return render_template("admin/admin_users.html", admins=[tuple(row) for row in rows])


@admin_bp.route("/admins/create", methods=["GET", "POST"])
@require_admin
@require_role("admin")
def create_admin_user():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        role = request.form.get("role", "admin")

        if role not in ("admin", "viewer"):
            error = "Choose a valid role."
        elif not 3 <= len(username) <= 32:
            error = "Username must be 3-32 characters."
        else:
            try:
                password_hash = passwords.hash_password(password, username=username)
            except passwords.PasswordPolicyError as problem:
                error = str(problem)
            else:
                try:
                    store().create_user(username, password_hash, role)
                except ValueError as problem:
                    error = str(problem)
                except sqlite3.IntegrityError:
                    error = "That username is already taken."
                else:
                    audit("create_user", f"{role}: {username}")
                    flash(f"User '{username}' created.", "success")
                    return redirect(url_for("admin.admin_users"))
    return render_template("admin/create_admin.html", error=error)


@admin_bp.post("/admins/<int:user_id>/toggle")
@require_admin
@require_role("admin")
def toggle_admin(user_id: int):
    current = store().get_user(user_id)
    if current is None:
        abort(404)
    if current.id == _current_id():
        flash("You cannot suspend your own account.", "error")
        return redirect(url_for("admin.admin_users"))

    store().set_active(user_id, not current.active)
    audit("activate_user" if not current.active else "suspend_user", current.username)
    flash(f"User '{current.username}' {'activated' if not current.active else 'suspended'}.", "success")
    return redirect(url_for("admin.admin_users"))


@admin_bp.post("/admins/<int:user_id>/delete")
@require_admin
@require_role("admin")
def delete_admin_user(user_id: int):
    target = store().get_user(user_id)
    if target is None:
        abort(404)
    if target.id == _current_id():
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin.admin_users"))

    admins = [u for u in store().list_users() if u.role == "admin" and u.active]
    if target.role == "admin" and len(admins) <= 1:
        flash("You cannot delete the last active administrator.", "error")
        return redirect(url_for("admin.admin_users"))

    store().delete_user(user_id)
    audit("delete_user", target.username)
    flash(f"User '{target.username}' deleted.", "success")
    return redirect(url_for("admin.admin_users"))


# ── System Config (read-only, no secrets) ─────────────────────────
@admin_bp.get("/config")
@require_admin
@require_role("admin")
def system_config():
    settings = load_settings()
    cfg = current_app.extensions["sentinel_config"]
    # Only safe, non-sensitive values — never tokens, keys or passwords.
    config = {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "debug": current_app.debug,
        "log_level": settings.log_level,
        "database_path": cfg.database_path,
        "snapshot_dir": cfg.snapshot_dir,
        "https": cfg.https,
        "allow_lan": cfg.allow_lan,
        "session_idle_minutes": cfg.session_idle_seconds // 60,
        "session_absolute_hours": cfg.session_absolute_seconds // 3600,
        "telegram_bot_configured": bool(settings.telegram_bot_token),
    }
    return render_template("admin/config.html", config=config)
