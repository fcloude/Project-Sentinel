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

CREATE_DETECTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS detections (
    detection_id TEXT PRIMARY KEY,
    person_name TEXT NOT NULL,
    known_person INTEGER NOT NULL,
    confidence REAL NOT NULL,
    camera TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    snapshot_path TEXT
);
"""

CREATE_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES events(event_id)
);
"""


def initialize_database() -> None:
    conn = DatabaseManager().get_connection()
    conn.execute(CREATE_EVENTS_TABLE)
    conn.execute(CREATE_DETECTIONS_TABLE)
    conn.execute(CREATE_SNAPSHOTS_TABLE)
    conn.commit()
    conn.close()