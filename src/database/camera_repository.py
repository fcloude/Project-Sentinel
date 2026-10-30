from datetime import datetime, timezone

from cryptography.fernet import InvalidToken

from src.camera.url_utils import mask_url


class CameraRepository:
    """Cameras live in the DB. The address (which may hold a password) is encrypted."""

    def __init__(self, conn, box):
        self.conn = conn
        self.box = box

    def add(self, name: str, kind: str, source: str) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO cameras (name, kind, source_enc, enabled, detection_fps, created_at)
            VALUES (?, ?, ?, 1, 3, ?)
            """,
            (name, kind, self.box.encrypt(source), datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def _row_to_dict(self, row, reveal: bool) -> dict:
        camera_id, name, kind, source_enc, enabled = row
        try:
            source = self.box.decrypt(source_enc)
        except InvalidToken:
            source = None

        if source is None:
            display = "(unreadable: the secret key changed)"
        elif kind == "url":
            display = mask_url(source)
        else:
            display = source

        result = {
            "id": camera_id,
            "name": name,
            "kind": kind,
            "enabled": bool(enabled),
            "display_source": display,
        }
        if reveal:
            result["source"] = source
        return result

    def list(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, name, kind, source_enc, enabled FROM cameras ORDER BY id"
        ).fetchall()
        return [self._row_to_dict(r, reveal=False) for r in rows]

    def get(self, camera_id: int):
        row = self.conn.execute(
            "SELECT id, name, kind, source_enc, enabled FROM cameras WHERE id = ?",
            (camera_id,),
        ).fetchone()
        return self._row_to_dict(row, reveal=True) if row else None

    def delete(self, camera_id: int) -> None:
        self.conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cameras").fetchone()[0]
