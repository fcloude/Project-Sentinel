import time


class Cooldown:
    """allowed(key) is True at most once per `seconds` for each key."""

    def __init__(self, seconds, clock=time.monotonic):
        self.seconds = seconds
        self.clock = clock
        self._last = {}

    def allowed(self, key) -> bool:
        now = self.clock()
        last = self._last.get(key)
        if last is not None and now - last < self.seconds:
            return False
        self._last[key] = now
        return True
