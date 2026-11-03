import sqlite3
from datetime import datetime, timezone

import numpy as np


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_blob(vector) -> bytes:
    """Embeddings are stored as raw float32 bytes (never pickle)."""
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).copy()


class PeopleRepository:
    """People, their face embeddings, and the inbox of unknown faces."""

    def __init__(self, conn):
        self.conn = conn

    # ---- people ---------------------------------------------------------

    def person_exists(self, name: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM people WHERE name = ?", (name,)).fetchone()
        return row is not None

    def create_person(self, name: str, consent: bool, notes: str = "") -> int:
        if not consent:
            raise ValueError("Consent is required to add a person.")
        try:
            cursor = self.conn.execute(
                "INSERT INTO people (name, notes, consent_at, created_at) VALUES (?, ?, ?, ?)",
                (name, notes, now_iso(), now_iso()),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"'{name}' already exists.") from None
        self.conn.commit()
        return cursor.lastrowid

    def get_person(self, person_id: int):
        row = self.conn.execute(
            "SELECT id, name, created_at FROM people WHERE id = ?", (person_id,)
        ).fetchone()
        return {"id": row[0], "name": row[1], "created_at": row[2]} if row else None

    def list_people(self):
        rows = self.conn.execute(
            """
            SELECT p.id, p.name, p.created_at, COUNT(e.id)
            FROM people p LEFT JOIN face_embeddings e ON e.person_id = p.id
            GROUP BY p.id ORDER BY p.name COLLATE NOCASE
            """
        ).fetchall()
        return [
            {"id": r[0], "name": r[1], "created_at": r[2], "photo_count": r[3]} for r in rows
        ]

    def delete_person(self, person_id: int) -> None:
        """Real deletion: the person and all their face data (cascade)."""
        self.conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
        self.conn.commit()

    # ---- embeddings -----------------------------------------------------

    def add_embedding(self, person_id: int, model_id: str, vector, quality: float) -> None:
        self.conn.execute(
            """
            INSERT INTO face_embeddings (person_id, model_id, vector, quality, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (person_id, model_id, to_blob(vector), float(quality), now_iso()),
        )
        self.conn.commit()

    def all_embeddings(self, model_id: str):
        """[(person_id, name, vector)] for the current model only."""
        rows = self.conn.execute(
            """
            SELECT e.person_id, p.name, e.vector
            FROM face_embeddings e JOIN people p ON p.id = e.person_id
            WHERE e.model_id = ?
            """,
            (model_id,),
        ).fetchall()
        return [(r[0], r[1], from_blob(r[2])) for r in rows]

    def count_stale(self, model_id: str) -> int:
        """Embeddings made by a different model: unusable until photos are re-added."""
        return self.conn.execute(
            "SELECT COUNT(*) FROM face_embeddings WHERE model_id != ?", (model_id,)
        ).fetchone()[0]

    # ---- unknown faces ----------------------------------------------------

    def add_unknown(self, camera_id, model_id, vector, crop_path, seen_at=None) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO unknown_faces (camera_id, seen_at, model_id, vector, crop_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (camera_id, seen_at or now_iso(), model_id, to_blob(vector), crop_path),
        )
        self.conn.commit()
        return cursor.lastrowid

    def recent_unknown_vectors(self, model_id: str, since_iso: str, limit: int = 200):
        rows = self.conn.execute(
            """
            SELECT id, vector FROM unknown_faces
            WHERE model_id = ? AND seen_at >= ?
            ORDER BY seen_at DESC LIMIT ?
            """,
            (model_id, since_iso, limit),
        ).fetchall()
        return [(r[0], from_blob(r[1])) for r in rows]

    def bump_unknown(self, unknown_id: int, seen_at: str) -> None:
        self.conn.execute(
            "UPDATE unknown_faces SET seen_count = seen_count + 1, seen_at = ? WHERE id = ?",
            (seen_at, unknown_id),
        )
        self.conn.commit()

    def _unknown_row(self, row):
        return {
            "id": row[0],
            "camera_id": row[1],
            "seen_at": row[2],
            "model_id": row[3],
            "vector": from_blob(row[4]),
            "crop_path": row[5],
            "seen_count": row[6],
        }

    def list_unknown(self, limit: int = 100):
        rows = self.conn.execute(
            """
            SELECT id, camera_id, seen_at, model_id, vector, crop_path, seen_count
            FROM unknown_faces ORDER BY seen_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._unknown_row(r) for r in rows]

    def get_unknown(self, unknown_id: int):
        row = self.conn.execute(
            """
            SELECT id, camera_id, seen_at, model_id, vector, crop_path, seen_count
            FROM unknown_faces WHERE id = ?
            """,
            (unknown_id,),
        ).fetchone()
        return self._unknown_row(row) if row else None

    def count_unknown(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM unknown_faces").fetchone()[0]

    def delete_unknown(self, unknown_id: int) -> None:
        self.conn.execute("DELETE FROM unknown_faces WHERE id = ?", (unknown_id,))
        self.conn.commit()

    def delete_old_unknowns(self, before_iso: str):
        """Deletes rows last seen before the cutoff; returns their crop paths."""
        paths = [
            r[0]
            for r in self.conn.execute(
                "SELECT crop_path FROM unknown_faces WHERE seen_at < ?", (before_iso,)
            ).fetchall()
        ]
        self.conn.execute("DELETE FROM unknown_faces WHERE seen_at < ?", (before_iso,))
        self.conn.commit()
        return paths


class SettingsRepository:

    def __init__(self, conn):
        self.conn = conn

    def get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.conn.commit()
