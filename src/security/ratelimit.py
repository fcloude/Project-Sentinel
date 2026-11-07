"""Thread-safe in-memory sliding-window limiter + login throttle.

Per-process only (fine for the single-process MVP). Memory is bounded (max_keys)."""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float, *, max_keys: int = 10_000,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self.max_keys = max_keys
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, dq: deque[float], now: float) -> None:
        while dq and now - dq[0] >= self.window:
            dq.popleft()

    def _get(self, key: str, now: float, create: bool) -> deque[float] | None:
        dq = self._events.get(key)
        if dq is None:
            if not create:
                return None
            if len(self._events) >= self.max_keys:
                for k in [k for k, v in self._events.items() if not v or now - v[-1] >= self.window]:
                    del self._events[k]
                while len(self._events) >= self.max_keys:  # still full: drop oldest key
                    del self._events[next(iter(self._events))]
            dq = self._events[key] = deque()
        self._prune(dq, now)
        return dq

    def blocked(self, key: str) -> bool:
        with self._lock:
            dq = self._get(key, self._clock(), create=False)
            return dq is not None and len(dq) >= self.max_events

    def record(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            self._get(key, now, create=True).append(now)  # type: ignore[union-attr]

    def hit(self, key: str) -> bool:
        """Record an event; return False (and don't record) if the limit is already reached."""
        with self._lock:
            now = self._clock()
            dq = self._get(key, now, create=True)
            assert dq is not None
            if len(dq) >= self.max_events:
                return False
            dq.append(now)
            return True

    def retry_after(self, key: str) -> int:
        with self._lock:
            now = self._clock()
            dq = self._get(key, now, create=False)
            if not dq or len(dq) < self.max_events:
                return 0
            return max(1, int(self.window - (now - dq[0])) + 1)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


class LoginThrottle:
    """5 failures per (ip, username) or 20 per ip within 15 minutes => temporarily blocked.

    Keying on (ip, username) stops an attacker from locking the real admin out from elsewhere."""

    def __init__(self, max_failures: int = 5, window_seconds: float = 900, clock: Callable[[], float] = time.monotonic):
        self._pair = SlidingWindowLimiter(max_failures, window_seconds, clock=clock)
        self._ip = SlidingWindowLimiter(max_failures * 4, window_seconds, clock=clock)

    @staticmethod
    def _pair_key(ip: str, username: str) -> str:
        return f"{ip}|{username.lower()[:64]}"

    def blocked(self, ip: str, username: str) -> bool:
        return self._pair.blocked(self._pair_key(ip, username)) or self._ip.blocked(ip)

    def retry_after(self, ip: str, username: str) -> int:
        return max(self._pair.retry_after(self._pair_key(ip, username)), self._ip.retry_after(ip))

    def failure(self, ip: str, username: str) -> None:
        self._pair.record(self._pair_key(ip, username))
        self._ip.record(ip)

    def success(self, ip: str, username: str) -> None:
        self._pair.reset(self._pair_key(ip, username))
