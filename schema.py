"""Database schema with tiny versioned migrations.

RULE: never edit an existing migration. To change the schema, APPEND a new
entry to MIGRATIONS. The database remembers which ones already ran
(PRAGMA user_version), so customers' databases upgrade in place.
"""

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

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT NOT NULL
);
"""

CREATE_CAMERAS_TABLE = """
CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_enc TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    detection_fps INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL
);
"""

MIGRATIONS = [
    # v1
    [CREATE_EVENTS_TABLE, CREATE_DETECTIONS_TABLE, CREATE_SNAPSHOTS_TABLE],
    # v2
    [CREATE_USERS_TABLE, CREATE_CAMERAS_TABLE],
]


def initialize_database() -> None:
    conn = DatabaseManager().get_connection()
    current = conn.execute("PRAGMA user_version").fetchone()[0]

    for version, statements in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        for statement in statements:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()

    conn.close()
