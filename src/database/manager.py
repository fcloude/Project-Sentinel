import sqlite3

from config.loader import load_settings

settings = load_settings()


class DatabaseManager:
    """Manages the SQLite database connection."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(settings.database_path)

    def get_connection(self) -> sqlite3.Connection:
        return self.connection