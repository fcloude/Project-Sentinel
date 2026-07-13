from database.manager import DatabaseManager


class EventRepository:

    def __init__(self):

        self.db = DatabaseManager()

    def get_all_events(self):

        conn = self.db.get_connection()

        cursor = conn.execute(
            """
            SELECT *
            FROM events
            ORDER BY timestamp DESC
            """
        )

        return cursor.fetchall()

    def count_events(self):

        conn = self.db.get_connection()

        cursor = conn.execute(
            """
            SELECT COUNT(*)
            FROM events
            """
        )

        return cursor.fetchone()[0]