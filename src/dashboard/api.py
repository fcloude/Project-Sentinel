from flask import Blueprint
from flask import jsonify

from src.dashboard.services.dashboard_service import DashboardService


api = Blueprint(
    "api",
    __name__,
)

service = DashboardService()


@api.get("/status")
def status():

    return jsonify(
        service.get_dashboard_state(),
    )


@api.get("/events")
def events():

    return jsonify(
        service.get_recent_events(),
    )


@api.get("/faces")
def faces():

    return jsonify(
        service.get_faces(),
    )


@api.get("/cameras")
def cameras():

    return jsonify(
        service.get_cameras(),
    )


@api.get("/settings")
def settings():

    return jsonify(
        service.get_settings(),
    )


@api.get("/health")
def health():

    return jsonify(
        {
            "status": "online",
            "service": "Project Sentinel Dashboard",
            "version": "1.0.0",
        }
    )