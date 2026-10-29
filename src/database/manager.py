import sqlite3
from pathlib import Path

from src.config.loader import load_settings

settings = load_settings()


class DatabaseManager:
    """Manages the SQLite database connection."""

    def __init__(self) -> None:
        db_path = Path(settings.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path, check_same_thread=False)

    def get_connection(self) -> sqlite3.Connection:
        return self.connection