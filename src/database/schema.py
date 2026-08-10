from src.database.manager import DatabaseManager

CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    message TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
"""


def initialize_database() -> None:
    db = DatabaseManager()
    conn = db.get_connection()

    conn.execute(CREATE_EVENTS_TABLE)

    conn.commit()
