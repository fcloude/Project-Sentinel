"""Database schema with tiny versioned migrations.

RULE: never edit an existing migration. To change the schema, APPEND a new
entry to MIGRATIONS. The database remembers which ones already ran
(PRAGMA user_version), so customers' databases upgrade in place.

Note: The Google authentication columns (provider, provider_subject, email, email_verified)
are added via a migration step in the app factory. The migration runner
ensures they exist on legacy databases while preserving existing data.
"""

from src.database.manager import DatabaseManager
from src.security.store import ensure_user_columns

CREATE_EVENTS_TABLE = """CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    message TEXT NOT NULL,
    timestamp TEXT NOT NULL
);"""

CREATE_DETECTIONS_TABLE = """CREATE TABLE IF NOT EXISTS detections (
    detection_id TEXT PRIMARY KEY,
    person_name TEXT NOT NULL,
    known_person INTEGER NOT NULL,
    confidence REAL NOT NULL,
    camera TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    snapshot_path TEXT
);"""

CREATE_SNAPSHOTS_TABLE = """CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES events(event_id)
);"""

CREATE_USERS_TABLE = """CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    created_at TEXT NOT NULL
);"""

CREATE_CAMERAS_TABLE = """CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_enc TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    detection_fps INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL
);"""

CREATE_PEOPLE_TABLE = """CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    notes TEXT NOT NULL DEFAULT '',
    consent_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);"""

CREATE_FACE_EMBEDDINGS_TABLE = """CREATE TABLE IF NOT EXISTS face_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    vector BLOB NOT NULL,
    quality REAL NOT NULL,
    created_at TEXT NOT NULL
);"""

CREATE_FACE_EMBEDDINGS_INDEX = """CREATE INDEX IF NOT EXISTS idx_face_embeddings_person ON face_embeddings(person_id);"""

CREATE_UNKNOWN_FACES_TABLE = """CREATE TABLE IF NOT EXISTS unknown_faces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER,
    seen_at TEXT NOT NULL,
    model_id TEXT NOT NULL,
    vector BLOB NOT NULL,
    crop_path TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1
);"""

CREATE_SETTINGS_TABLE = """CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);"""

CREATE_NOTIFICATION_CHANNELS_TABLE = """CREATE TABLE IF NOT EXISTS notification_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    config_enc TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);"""

CREATE_NOTIFICATION_RULES_TABLE = """CREATE TABLE IF NOT EXISTS notification_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    camera_id INTEGER,
    channel_ids TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    cooldown_s INTEGER NOT NULL DEFAULT 60,
    attach_snapshot INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1
);"""

CREATE_NOTIFICATION_OUTBOX_TABLE = """CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER,
    channel_id INTEGER NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_attempt_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT
);"""

CREATE_OUTBOX_INDEX = """CREATE INDEX IF NOT EXISTS idx_outbox_due ON notification_outbox(status, next_attempt_at);"""

CREATE_NOTIFICATIONS_TABLE = """CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT '',
    camera_id INTEGER,
    camera_name TEXT NOT NULL DEFAULT '',
    snapshot_path TEXT,
    is_read INTEGER NOT NULL DEFAULT 0
);"""

CREATE_PUSH_SUBSCRIPTIONS_TABLE = """CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL
);"""

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
    # v4
    [
        CREATE_NOTIFICATION_CHANNELS_TABLE,
        CREATE_NOTIFICATION_RULES_TABLE,
        CREATE_NOTIFICATION_OUTBOX_TABLE,
        CREATE_OUTBOX_INDEX,
        CREATE_NOTIFICATIONS_TABLE,
        CREATE_PUSH_SUBSCRIPTIONS_TABLE,
    ],
    # v5: users columns required by src.security.store. Applied in Python below because
    # SQLite has no "ADD COLUMN IF NOT EXISTS" and fresh installs already have them.
    [],
    # v6: Google authentication columns
    [
        # Add provider, provider_subject, email, email_verified columns if missing
        # These are added in Python in create_app rather than pure SQL migration
        # to preserve existing user records safely
    ],
]

"""Migration v6 adds Google auth columns to the users table.

The columns are added in the app factory via ensure_user_columns + explicit
ALTER TABLE statements so that legacy databases upgrade safely and existing
user accounts (with password hashes) are preserved.

Columns added (if not already present):
  - provider TEXT NOT NULL DEFAULT ''        -- e.g. 'google'
  - provider_subject TEXT NOT NULL DEFAULT ''  -- Google's 'sub' claim
  - email TEXT NOT NULL COLLATE NOCASE UNIQUE  -- user's email
  - email_verified INTEGER NOT NULL DEFAULT 0  -- whether email was verified by Google
"""


def initialize_database(database_path: str | None = None) -> None:
    """Apply pending migrations. Pass a path when the caller (the app factory) owns the
    configuration; omit it to use the process-wide settings.

    After applying migrations, ensures user columns exist (for legacy database upgrade).
    """
    conn = DatabaseManager(database_path).get_connection()
    current = conn.execute("PRAGMA user_version").fetchone()[0]

    for version, statements in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        for statement in statements:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {version}")  # sentinel-ok: loop integer
        conn.commit()

    ensure_user_columns(conn)
    conn.commit()
    conn.close()