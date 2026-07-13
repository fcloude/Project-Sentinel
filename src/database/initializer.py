from database.manager import DatabaseManager

from database.migrations import (
    CREATE_EVENTS_TABLE,
    CREATE_DETECTIONS_TABLE,
    CREATE_SNAPSHOTS_TABLE,
)


def initialize_database() -> None:

    db = DatabaseManager()

    conn = db.get_connection()

    conn.execute(CREATE_EVENTS_TABLE)

    conn.execute(CREATE_DETECTIONS_TABLE)

    conn.execute(CREATE_SNAPSHOTS_TABLE)

    conn.commit()

    conn.close()