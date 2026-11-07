import logging
import queue
import threading

from src.events.event import Event
from src.notifications.client import TelegramClient
from src.notifications.cooldown import CooldownManager
from src.notifications.formatter import NotificationFormatter
from src.notifications.settings import COOLDOWN_SECONDS

logger = logging.getLogger(__name__)


class NotificationManager:
    """notify() only enqueues (microseconds). A background thread does the slow network I/O, so a dead
    internet connection can never freeze video processing. The queue is bounded: when full, new alerts are
    dropped (and logged) instead of growing memory without limit."""

    def __init__(self, client=None, max_queue: int = 50):
        self.client = client or TelegramClient()
        self.cooldown = CooldownManager(COOLDOWN_SECONDS)
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._worker = threading.Thread(target=self._run, name="NotificationWorker", daemon=True)
        self._worker.start()

    def _enqueue(self, job) -> None:
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            logger.warning("Notification queue full; alert dropped.")

    def notify(self, event: Event):
        if not self.cooldown.allowed(event.event_type):
            return
        self._enqueue(("message", NotificationFormatter.format(event), None))

    def notify_photo(self, event: Event, image_path):
        if not self.cooldown.allowed(event.event_type):
            return
        self._enqueue(("photo", NotificationFormatter.format(event), image_path))

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            kind, text, path = job
            try:
                if kind == "photo":
                    self.client.send_photo(path, text)
                else:
                    self.client.send_message(text)
            except Exception:
                logger.exception("Notification delivery failed")

    def close(self) -> None:
        self._queue.put(None)
        self._worker.join(timeout=5)
