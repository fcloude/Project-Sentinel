from database.manager import DatabaseManager


class SnapshotRepository:

    def __init__(self):

        self.db = DatabaseManager()

    def get_all_snapshots(self):

        conn = self.db.get_connection()

        cursor = conn.execute(
            """
            SELECT *

            FROM snapshots

            ORDER BY timestamp DESC
            """
        )

        return cursor.fetchall()