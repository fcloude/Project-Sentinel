from database.manager import DatabaseManager


class DetectionRepository:

    def __init__(self):

        self.db = DatabaseManager()

    def get_last_seen(self, person_name):

        conn = self.db.get_connection()

        cursor = conn.execute(
            """
            SELECT *
            FROM detections

            WHERE person_name = ?

            ORDER BY timestamp DESC

            LIMIT 1
            """,
            (person_name,),
        )

        return cursor.fetchone()

    def get_unknown_people(self):

        conn = self.db.get_connection()

        cursor = conn.execute(
            """
            SELECT *

            FROM detections

            WHERE known_person = 0

            ORDER BY timestamp DESC
            """
        )

        return cursor.fetchall()