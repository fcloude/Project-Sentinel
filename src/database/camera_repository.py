from datetime import datetime, timezone


from src.camera.url_utils import mask_url
from src.security.crypto import SecretDecryptionError


class CameraRepository:
    """Cameras live in the DB. The address (which may hold a password) is encrypted."""

    def __init__(self, conn, box):
        self.conn = conn
        self.box = box

    def add(self, name: str, kind: str, source: str, user_id: int = 1) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO cameras (name, kind, source_enc, enabled, detection_fps, created_at, user_id)
            VALUES (?, ?, ?, 1, 3, ?, ?)
            """,
            (name, kind, self.box.encrypt(source), datetime.now(timezone.utc).isoformat(), user_id),
        )
        self.conn.commit()
        return cursor.lastrowid

    def _row_to_dict(self, row, reveal: bool) -> dict:
        camera_id, name, kind, source_enc, enabled = row
        try:
            source = self.box.decrypt(source_enc)
        except SecretDecryptionError:
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

    def list(self, user_id: int = 1) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, name, kind, source_enc, enabled FROM cameras WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
        return [self._row_to_dict(r, reveal=False) for r in rows]

    def get(self, camera_id: int, user_id: int = 1):
        row = self.conn.execute(
            "SELECT id, name, kind, source_enc, enabled FROM cameras WHERE id = ? AND user_id = ?",
            (camera_id, user_id),
        ).fetchone()
        return self._row_to_dict(row, reveal=True) if row else None

    def delete(self, camera_id: int, user_id: int = 1) -> None:
        self.conn.execute("DELETE FROM cameras WHERE id = ? AND user_id = ?", (camera_id, user_id))
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cameras").fetchone()[0]

    def list_enabled(self, user_id: int = 1):
        """Cameras the engine should run, with their decrypted source."""
        rows = self.conn.execute(
            "SELECT id, name, kind, source_enc, detection_fps FROM cameras WHERE enabled = 1 AND user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()

        cameras = []
        for camera_id, name, kind, source_enc, fps in rows:
            try:
                source = self.box.decrypt(source_enc)
            except SecretDecryptionError:
                continue  # saved under a different secret key; cannot be used
            cameras.append(
                {
                    "id": camera_id,
                    "name": name,
                    "kind": kind,
                    "source": source,
                    "detection_fps": fps,
                }
            )
        return cameras