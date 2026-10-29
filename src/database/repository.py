from src.database.manager import DatabaseManager
from src.events.event import Event


class EventRepository:

    def __init__(self):
        self.database = DatabaseManager()
        self.connection = self.database.get_connection()

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

    def delete_all(self):
        self.connection.execute("DELETE FROM events")
        self.connection.commit()