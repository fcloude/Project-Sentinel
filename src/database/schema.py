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

CREATE_PEOPLE_TABLE = """
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    notes TEXT NOT NULL DEFAULT '',
    consent_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

CREATE_FACE_EMBEDDINGS_TABLE = """
CREATE TABLE IF NOT EXISTS face_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    vector BLOB NOT NULL,
    quality REAL NOT NULL,
    created_at TEXT NOT NULL
);
"""

CREATE_FACE_EMBEDDINGS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_face_embeddings_person ON face_embeddings(person_id);
"""

CREATE_UNKNOWN_FACES_TABLE = """
CREATE TABLE IF NOT EXISTS unknown_faces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER,
    seen_at TEXT NOT NULL,
    model_id TEXT NOT NULL,
    vector BLOB NOT NULL,
    crop_path TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1
);
"""

CREATE_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

MIGRATIONS = [
    # v1
    [CREATE_EVENTS_TABLE, CREATE_DETECTIONS_TABLE, CREATE_SNAPSHOTS_TABLE],
    # v2
    [CREATE_USERS_TABLE, CREATE_CAMERAS_TABLE],
    # v3
    [
        CREATE_PEOPLE_TABLE,
        CREATE_FACE_EMBEDDINGS_TABLE,
        CREATE_FACE_EMBEDDINGS_INDEX,
        CREATE_UNKNOWN_FACES_TABLE,
        CREATE_SETTINGS_TABLE,
    ],
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
