from src.database.manager import DatabaseManager
from src.events.event import Event


class EventRepository:

    def __init__(self, connection=None):
        # Pass a connection to share one (web requests); omit for a private one.
        if connection is None:
            connection = DatabaseManager().get_connection()
        self.connection = connection

    def save(self, event: Event) -> None:
        self.connection.execute(
            """
            INSERT INTO events (event_id, event_type, source, message, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type,
                event.source,
                event.message,
                event.timestamp,
            ),
        )
        self.connection.commit()

    def get_all(self):
        cursor = self.connection.execute("SELECT * FROM events")
        return cursor.fetchall()

    def recent(self, limit: int = 20) -> list[dict]:
        cursor = self.connection.execute(
            """
            SELECT event_id, event_type, source, message, timestamp
            FROM events ORDER BY timestamp DESC LIMIT ?
            """,
            (limit,),
        )
        keys = ("event_id", "event_type", "source", "message", "timestamp")
        return [dict(zip(keys, row)) for row in cursor.fetchall()]

    def count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def delete_all(self):
        self.connection.execute("DELETE FROM events")
        self.connection.commit()
