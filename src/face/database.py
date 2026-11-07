"""Face-embedding store. Embeddings are raw float32 bytes -- NEVER pickle (pickle.loads == code execution
if the DB file is ever tampered with). Rows written by the old pickle version are skipped, not loaded."""
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np

from src.security.validators import validate_person_name

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 512  # InsightFace/ArcFace; change together with the model (ADR-004)


def to_blob(vector) -> bytes:
    arr = np.asarray(vector, dtype=np.float32)
    if arr.ndim != 1 or arr.shape[0] != EMBEDDING_DIM or not np.isfinite(arr).all():
        raise ValueError(f"Embedding must be a finite float vector of length {EMBEDDING_DIM}.")
    return arr.tobytes()


def from_blob(blob: bytes) -> np.ndarray | None:
    if not isinstance(blob, (bytes, bytearray)) or len(blob) != EMBEDDING_DIM * 4:
        return None  # includes legacy pickle rows
    arr = np.frombuffer(blob, dtype=np.float32).copy()
    return arr if np.isfinite(arr).all() else None


class FaceDatabase:
    def __init__(self, database_path: str | None = None):
        if database_path is None:
            from src.config.loader import load_settings
            database_path = load_settings().database_path
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS known_faces (name TEXT PRIMARY KEY, embedding BLOB NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        # one short-lived connection per operation: safe across threads
        return sqlite3.connect(self.database_path, timeout=10)

    def add_face(self, name: str, embedding) -> None:
        name = validate_person_name(name)
        blob = to_blob(embedding)
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO known_faces (name, embedding) VALUES (?, ?)", (name, blob))

    def get_face(self, name: str):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT embedding FROM known_faces WHERE name = ?", (name,)).fetchone()
        return None if row is None else from_blob(row[0])

    def get_all_faces(self):
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT name, embedding FROM known_faces").fetchall()
        faces, skipped = [], 0
        for name, blob in rows:
            vec = from_blob(blob)
            if vec is None:
                skipped += 1
            else:
                faces.append((name, vec))
        if skipped:
            logger.warning("%d stored face(s) have an unsupported format (legacy pickle?) and were skipped. Re-enrol them.", skipped)
        return faces

    def delete_face(self, name: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM known_faces WHERE name = ?", (name,))

    def delete_all(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM known_faces")

    def close(self) -> None:  # kept for API compatibility; no persistent connection to close
        return None
