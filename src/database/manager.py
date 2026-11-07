import sqlite3
from pathlib import Path

from src.config.loader import load_settings

settings = load_settings()


class DatabaseManager:
    """Opens a SQLite connection. Create one per thread / per web request."""

    def __init__(self, database_path: str | None = None) -> None:
        db_path = Path(database_path or settings.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        # WAL lets the engine thread write while the web app reads.
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA foreign_keys=ON")

    def get_connection(self) -> sqlite3.Connection:
        return self.connection
