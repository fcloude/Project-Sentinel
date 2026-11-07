import json
from datetime import datetime, timezone

from src.notifications.channels import summarize
from src.notifications.models import Notification
from src.security.crypto import SecretDecryptionError


def iso(moment=None) -> str:
    return (moment or datetime.now(timezone.utc)).isoformat(timespec="microseconds")


class NotificationRepository:
    """Channels, rules, the delivery queue (outbox), the in-app inbox and push subscriptions.

    Channel settings (bot tokens, SMTP passwords...) are encrypted at rest.
    """

    def __init__(self, conn, box):
        self.conn = conn
        self.box = box

    # ---- channels ------------------------------------------------------------

    def add_channel(self, type_, name, config) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO notification_channels (type, name, config_enc, enabled, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (type_, name, self.box.encrypt(json.dumps(config)), iso()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def _channel(self, row, reveal):
        channel_id, type_, name, config_enc, enabled = row
        try:
            config = json.loads(self.box.decrypt(config_enc))
        except (SecretDecryptionError, ValueError):
            config = None

        channel = {
            "id": channel_id,
            "type": type_,
            "name": name,
            "enabled": bool(enabled),
            "summary": summarize(type_, config) if config is not None
            else "(unreadable: the secret key changed)",
        }
        if reveal:
            channel["config"] = config
        return channel

    def list_channels(self):
        rows = self.conn.execute(
            "SELECT id, type, name, config_enc, enabled FROM notification_channels ORDER BY id"
        ).fetchall()
        return [self._channel(r, reveal=False) for r in rows]

    def get_channel(self, channel_id):
        row = self.conn.execute(
            "SELECT id, type, name, config_enc, enabled FROM notification_channels WHERE id = ?",
            (channel_id,),
        ).fetchone()
        return self._channel(row, reveal=True) if row else None

    def find_channel_by_type(self, type_):
        row = self.conn.execute(
            "SELECT id FROM notification_channels WHERE type = ? ORDER BY id LIMIT 1", (type_,)
        ).fetchone()
        return row[0] if row else None

    def count_channels(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM notification_channels").fetchone()[0]

    def set_channel_enabled(self, channel_id, enabled) -> None:
        self.conn.execute(
            "UPDATE notification_channels SET enabled = ? WHERE id = ?", (int(enabled), channel_id)
        )
        self.conn.commit()

    def delete_channel(self, channel_id) -> None:
        self.conn.execute("DELETE FROM notification_channels WHERE id = ?", (channel_id,))
        for rule in self.list_rules():
            if channel_id in rule["channel_ids"]:
                remaining = [c for c in rule["channel_ids"] if c != channel_id]
                self.conn.execute(
                    "UPDATE notification_rules SET channel_ids = ? WHERE id = ?",
                    (json.dumps(remaining), rule["id"]),
                )
        self.conn.commit()

    # ---- rules -------------------------------------------------------------------

    def add_rule(self, name, trigger, camera_id, channel_ids, start_time=None, end_time=None,
                 cooldown_s=60, attach_snapshot=True) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO notification_rules
                (name, trigger_type, camera_id, channel_ids, start_time, end_time,
                 cooldown_s, attach_snapshot, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (name, trigger, camera_id, json.dumps(list(channel_ids)), start_time, end_time,
             int(cooldown_s), int(attach_snapshot)),
        )
        self.conn.commit()
        return cursor.lastrowid

    @staticmethod
    def _rule(row):
        return {
            "id": row[0], "name": row[1], "trigger": row[2], "camera_id": row[3],
            "channel_ids": json.loads(row[4]), "start_time": row[5], "end_time": row[6],
            "cooldown_s": row[7], "attach_snapshot": bool(row[8]), "enabled": bool(row[9]),
        }

    _RULE_COLUMNS = (
        "id, name, trigger_type, camera_id, channel_ids, start_time, end_time, "
        "cooldown_s, attach_snapshot, enabled"
    )

    def list_rules(self):
        rows = self.conn.execute(
            f"SELECT {self._RULE_COLUMNS} FROM notification_rules ORDER BY id"
        ).fetchall()
        return [self._rule(r) for r in rows]

    def enabled_rules(self):
        return [r for r in self.list_rules() if r["enabled"]]

    def count_rules(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM notification_rules").fetchone()[0]

    def set_rule_enabled(self, rule_id, enabled) -> None:
        self.conn.execute(
            "UPDATE notification_rules SET enabled = ? WHERE id = ?", (int(enabled), rule_id)
        )
        self.conn.commit()

    def delete_rule(self, rule_id) -> None:
        self.conn.execute("DELETE FROM notification_rules WHERE id = ?", (rule_id,))
        self.conn.commit()

    def add_channel_to_rule(self, rule_id, channel_id) -> None:
        for rule in self.list_rules():
            if rule["id"] == rule_id and channel_id not in rule["channel_ids"]:
                self.conn.execute(
                    "UPDATE notification_rules SET channel_ids = ? WHERE id = ?",
                    (json.dumps(rule["channel_ids"] + [channel_id]), rule_id),
                )
                self.conn.commit()

    # ---- outbox (the delivery queue) -------------------------------------------------

    def enqueue(self, rule_id, channel_id, notification: Notification, now=None) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO notification_outbox
                (rule_id, channel_id, payload, status, attempts, next_attempt_at, created_at)
            VALUES (?, ?, ?, 'pending', 0, ?, ?)
            """,
            (rule_id, channel_id, json.dumps(notification.to_dict()), iso(now), iso(now)),
        )
        self.conn.commit()
        return cursor.lastrowid

    def due(self, now_iso, limit=20):
        rows = self.conn.execute(
            """
            SELECT id, rule_id, channel_id, payload, attempts FROM notification_outbox
            WHERE status = 'pending' AND next_attempt_at <= ? ORDER BY id LIMIT ?
            """,
            (now_iso, limit),
        ).fetchall()
        return [
            {"id": r[0], "rule_id": r[1], "channel_id": r[2],
             "notification": Notification.from_dict(json.loads(r[3])), "attempts": r[4]}
            for r in rows
        ]

    def mark_sent(self, outbox_id, now_iso) -> None:
        self.conn.execute(
            "UPDATE notification_outbox SET status = 'sent', sent_at = ?, last_error = NULL WHERE id = ?",
            (now_iso, outbox_id),
        )
        self.conn.commit()

    def mark_retry(self, outbox_id, attempts, error, next_iso) -> None:
        self.conn.execute(
            "UPDATE notification_outbox SET attempts = ?, last_error = ?, next_attempt_at = ? WHERE id = ?",
            (attempts, error, next_iso, outbox_id),
        )
        self.conn.commit()

    def mark_failed(self, outbox_id, attempts, error) -> None:
        self.conn.execute(
            "UPDATE notification_outbox SET status = 'failed', attempts = ?, last_error = ? WHERE id = ?",
            (attempts, error, outbox_id),
        )
        self.conn.commit()

    def recent_outbox(self, limit=30):
        rows = self.conn.execute(
            """
            SELECT o.id, o.created_at, COALESCE(c.name, '(removed channel)'), o.payload,
                   o.status, o.attempts, o.last_error
            FROM notification_outbox o LEFT JOIN notification_channels c ON c.id = o.channel_id
            ORDER BY o.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {"id": r[0], "created_at": r[1], "channel": r[2],
             "title": json.loads(r[3]).get("title", ""), "status": r[4],
             "attempts": r[5], "error": r[6]}
            for r in rows
        ]

    def purge_outbox(self, before_iso) -> None:
        self.conn.execute(
            "DELETE FROM notification_outbox WHERE status != 'pending' AND created_at < ?",
            (before_iso,),
        )
        self.conn.commit()

    # ---- in-app inbox ------------------------------------------------------------------

    def add_inbox(self, n: Notification) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO notifications
                (created_at, title, body, event_type, camera_id, camera_name, snapshot_path, is_read)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (n.created_at, n.title, n.body, n.event_type, n.camera_id, n.camera_name, n.snapshot_path),
        )
        self.conn.commit()
        return cursor.lastrowid

    @staticmethod
    def _inbox(row):
        return {
            "id": row[0], "created_at": row[1], "title": row[2], "body": row[3],
            "event_type": row[4], "camera_id": row[5], "camera_name": row[6],
            "snapshot_path": row[7], "is_read": bool(row[8]),
        }

    _INBOX_COLUMNS = (
        "id, created_at, title, body, event_type, camera_id, camera_name, snapshot_path, is_read"
    )

    def list_inbox(self, limit=100):
        rows = self.conn.execute(
            f"SELECT {self._INBOX_COLUMNS} FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._inbox(r) for r in rows]

    def get_inbox(self, inbox_id):
        row = self.conn.execute(
            f"SELECT {self._INBOX_COLUMNS} FROM notifications WHERE id = ?", (inbox_id,)
        ).fetchone()
        return self._inbox(row) if row else None

    def inbox_after(self, last_id, limit=50):
        rows = self.conn.execute(
            f"SELECT {self._INBOX_COLUMNS} FROM notifications WHERE id > ? ORDER BY id LIMIT ?",
            (last_id, limit),
        ).fetchall()
        return [self._inbox(r) for r in rows]

    def latest_inbox_id(self) -> int:
        return self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM notifications").fetchone()[0]

    def unread_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE is_read = 0"
        ).fetchone()[0]

    def mark_all_read(self) -> None:
        self.conn.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")
        self.conn.commit()

    def purge_inbox(self, before_iso):
        """Retention: returns the snapshot paths of deleted rows so files can be removed too."""
        paths = [
            r[0]
            for r in self.conn.execute(
                "SELECT snapshot_path FROM notifications WHERE created_at < ? AND snapshot_path IS NOT NULL",
                (before_iso,),
            ).fetchall()
        ]
        self.conn.execute("DELETE FROM notifications WHERE created_at < ?", (before_iso,))
        self.conn.commit()
        return paths

    # ---- push subscriptions ---------------------------------------------------------------

    def add_push_subscription(self, endpoint, p256dh, auth) -> None:
        self.conn.execute(
            """
            INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth
            """,
            (endpoint, p256dh, auth, iso()),
        )
        self.conn.commit()

    def list_push_subscriptions(self):
        rows = self.conn.execute(
            "SELECT endpoint, p256dh, auth FROM push_subscriptions ORDER BY id"
        ).fetchall()
        return [{"endpoint": r[0], "p256dh": r[1], "auth": r[2]} for r in rows]

    def count_push_subscriptions(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]

    def delete_push_subscription(self, endpoint) -> None:
        self.conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        self.conn.commit()
