from flask import Blueprint

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
)

from src.admin import routes  # noqa: E402, F401
