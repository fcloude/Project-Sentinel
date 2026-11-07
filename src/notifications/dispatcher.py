import time
from datetime import datetime

from src.events import event_types
from src.notifications.models import Notification
from src.notifications.rules import EVENT_TO_TRIGGER, in_window


class NotificationDispatcher:
    """Turns engine events into queued alerts, using the owner's rules.

    It only writes rows to the outbox, which is fast and can't fail because of
    the network. The OutboxWorker delivers them.
    """

    def __init__(self, repo_factory, clock=datetime.now, monotonic=time.monotonic):
        self._repo_factory = repo_factory
        self._repo = None
        self.clock = clock
        self.monotonic = monotonic
        self._last_sent = {}  # (rule id, camera, who) -> time of last alert

    def _get_repo(self):
        if self._repo is None:
            self._repo = self._repo_factory()
        return self._repo

    def _cooldown_allows(self, rule, camera_id, who) -> bool:
        key = (rule["id"], camera_id, who)
        now = self.monotonic()
        last = self._last_sent.get(key)
        if last is not None and now - last < rule["cooldown_s"]:
            return False
        self._last_sent[key] = now
        return True

    @staticmethod
    def _title(event, camera):
        where = f" at {camera}" if camera else ""
        if event.event_type == event_types.UNKNOWN_PERSON:
            return f"Unknown person{where}"
        if event.event_type == event_types.FACE_RECOGNIZED:
            return f"{event.metadata.get('name', 'Someone')} arrived{where}"
        if event.event_type == event_types.PERSON_DETECTED:
            return f"Person{where}"
        return f"Motion{where}"

    def handle(self, event) -> int:
        """Queues alerts for one event. Returns how many were queued."""
        trigger = EVENT_TO_TRIGGER.get(event.event_type)
        if trigger is None:
            return 0

        repo = self._get_repo()
        camera_id = event.metadata.get("camera_id")
        who = event.metadata.get("name", "")
        local_time = self.clock().time()
        queued = 0

        for rule in repo.enabled_rules():
            if rule["trigger"] != trigger:
                continue
            if rule["camera_id"] is not None and rule["camera_id"] != camera_id:
                continue
            if not in_window(rule["start_time"], rule["end_time"], local_time):
                continue
            if not rule["channel_ids"]:
                continue
            if not self._cooldown_allows(rule, camera_id, who):
                continue

            notification = Notification(
                title=self._title(event, event.source),
                body=f"{event.message} ({local_time.strftime('%H:%M')})",
                event_type=event.event_type,
                camera_id=camera_id,
                camera_name=event.source,
                snapshot_path=event.metadata.get("snapshot") if rule["attach_snapshot"] else None,
            )
            for channel_id in rule["channel_ids"]:
                repo.enqueue(rule["id"], channel_id, notification)
                queued += 1

        return queued
