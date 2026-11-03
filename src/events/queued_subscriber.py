import queue
import threading

from src.app_logging import get_logger

logger = get_logger(__name__)

_STOP = object()


class QueuedSubscriber:
    """Runs a slow callback (save to DB, send Telegram) on its own thread.

    Detection only drops the event into a queue and moves on, so a slow
    network can never freeze video processing. A failing callback is logged
    and the next event is still handled.
    """

    def __init__(self, callback, name, maxsize=500):
        self.callback = callback
        self.__name__ = name
        self._queue = queue.Queue(maxsize=maxsize)
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, name=self.__name__, daemon=True)
        self._thread.start()

    def stop(self, timeout=5.0):
        """Finishes everything already queued, then stops."""
        if self._thread is None:
            return
        try:
            self._queue.put(_STOP, timeout=1.0)
        except queue.Full:
            logger.warning("%s: queue full while stopping", self.__name__)
        self._thread.join(timeout)
        self._thread = None

    def __call__(self, event):
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning("%s: queue full, dropping an event", self.__name__)

    def _loop(self):
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            try:
                self.callback(item)
            except Exception:
                logger.exception("%s: callback failed", self.__name__)
