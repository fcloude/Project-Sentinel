import sqlite3
import pickle
from pathlib import Path

import numpy as np


class FaceDatabase:

    def __init__(self, database_path="sentinel.db"):

        self.database_path = database_path

        self.connection = sqlite3.connect(
            self.database_path,
        )

        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS known_faces(
                name TEXT PRIMARY KEY,
                embedding BLOB NOT NULL
            )
            """
        )

        self.connection.commit()

    def add_face(
        self,
        name: str,
        embedding: np.ndarray,
    ):

        blob = pickle.dumps(
            embedding,
        )

        self.connection.execute(
            """
            INSERT OR REPLACE INTO known_faces
            VALUES (?, ?)
            """,
            (
                name,
                blob,
            ),
        )

        self.connection.commit()

    def get_face(
        self,
        name: str,
    ):

        cursor = self.connection.execute(
            """
            SELECT embedding
            FROM known_faces
            WHERE name=?
            """,
            (
                name,
            ),
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return pickle.loads(
            row[0],
        )

    def get_all_faces(self):

        cursor = self.connection.execute(
            """
            SELECT name, embedding
            FROM known_faces
            """
        )

        faces = []

        for name, blob in cursor.fetchall():

            faces.append(
                (
                    name,
                    pickle.loads(blob),
                )
            )

        return faces

    def delete_face(
        self,
        name,
    ):

        self.connection.execute(
            """
            DELETE FROM known_faces
            WHERE name=?
            """,
            (
                name,
            ),
        )

        self.connection.commit()

    def close(self):

        self.connection.close()