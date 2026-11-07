import threading
from datetime import datetime, timedelta, timezone

from src.app_logging import get_logger
from src.errors import UserFacingError
from src.notifications.errors import describe_error
from src.notifications.repository import iso

logger = get_logger(__name__)

RETRY_DELAYS_SECONDS = (30, 120, 600, 1800)  # then give up
MAX_ATTEMPTS = len(RETRY_DELAYS_SECONDS) + 1
RETENTION_DAYS = 30


class OutboxWorker:
    """Delivers queued alerts on its own thread.

    A failure only affects that one alert: it is retried later (30 s, 2 min,
    10 min, 30 min), then marked failed, with a safe reason shown on the Alerts
    page. Detection never waits for it.
    """

    def __init__(self, repo_factory, channel_factory, poll_seconds=1.0,
                 clock=lambda: datetime.now(timezone.utc)):
        self._repo_factory = repo_factory
        self._repo = None
        self.channel_factory = channel_factory
        self.poll_seconds = poll_seconds
        self.clock = clock

        self._stop = threading.Event()
        self._thread = None
        self._last_purge = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="outbox-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout=5.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _get_repo(self):
        if self._repo is None:
            self._repo = self._repo_factory()
        return self._repo

    def run_once(self) -> int:
        """Delivers everything that is due. Returns how many alerts were handled."""
        repo = self._get_repo()
        now = self.clock()
        handled = 0

        for item in repo.due(iso(now), limit=20):
            handled += 1
            attempts = item["attempts"] + 1

            try:
                channel = self.channel_factory(item["channel_id"])
                channel.send(item["notification"])
            except UserFacingError as error:
                repo.mark_failed(item["id"], attempts, describe_error(error))  # retrying won't help
            except Exception as error:
                reason = describe_error(error)
                if attempts >= MAX_ATTEMPTS:
                    repo.mark_failed(item["id"], attempts, reason)
                else:
                    delay = RETRY_DELAYS_SECONDS[attempts - 1]
                    repo.mark_retry(item["id"], attempts, reason, iso(now + timedelta(seconds=delay)))
            else:
                repo.mark_sent(item["id"], iso(now))

        self._purge_if_due(repo, now)
        return handled

    def _purge_if_due(self, repo, now):
        if self._last_purge is not None and now - self._last_purge < timedelta(hours=1):
            return
        self._last_purge = now
        cutoff = iso(now - timedelta(days=RETENTION_DAYS))
        repo.purge_outbox(cutoff)
        for path in repo.purge_inbox(cutoff):
            _delete_file(path)

    def _loop(self):
        while not self._stop.is_set():
            try:
                busy = self.run_once()
            except Exception:
                logger.exception("Outbox worker error")
                busy = 0
            self._stop.wait(0.05 if busy else self.poll_seconds)


def _delete_file(path):
    try:
        from pathlib import Path

        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
