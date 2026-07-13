import json
import sqlite3

import numpy as np


class FaceRepository:

    def __init__(self, database_path="sentinel.db"):

        self.database_path = database_path

    def _connect(self):

        return sqlite3.connect(self.database_path)

    def add_face(
        self,
        name: str,
        embedding: np.ndarray,
        photo_path: str,
    ):

        conn = self._connect()

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO faces
            (
                name,
                embedding,
                photo_path
            )
            VALUES
            (?, ?, ?)
            """,
            (
                name,
                json.dumps(embedding.tolist()),
                photo_path,
            ),
        )

        conn.commit()

        conn.close()

    def get_all_faces(self):

        conn = self._connect()

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                id,
                name,
                embedding,
                photo_path
            FROM faces
            """
        )

        rows = cursor.fetchall()

        conn.close()

        faces = []

        for row in rows:

            faces.append(
                {
                    "id": row[0],
                    "name": row[1],
                    "embedding": np.array(
                        json.loads(row[2]),
                        dtype=np.float32,
                    ),
                    "photo_path": row[3],
                }
            )

        return faces

    def delete_face(
        self,
        face_id: int,
    ):

        conn = self._connect()

        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM faces
            WHERE id = ?
            """,
            (face_id,),
        )

        conn.commit()

        conn.close()

    def get_face_count(self):

        conn = self._connect()

        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM faces"
        )

        count = cursor.fetchone()[0]

        conn.close()

        return count