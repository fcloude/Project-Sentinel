import time

from src.engine.cooldown import Cooldown
from src.events.queued_subscriber import QueuedSubscriber


def test_failing_callback_does_not_stop_later_events():
    handled = []

    def callback(event):
        if event == "bad":
            raise RuntimeError("boom")
        handled.append(event)

    sub = QueuedSubscriber(callback, "test-sink")
    sub.start()
    sub("bad")
    sub("good-1")
    sub("good-2")
    sub.stop()

    assert handled == ["good-1", "good-2"]


def test_slow_callback_does_not_block_the_caller():
    sub = QueuedSubscriber(lambda event: time.sleep(0.3), "slow-sink")
    sub.start()

    started = time.monotonic()
    for i in range(5):
        sub(i)
    elapsed = time.monotonic() - started

    sub.stop(timeout=5)
    assert elapsed < 0.1


def test_full_queue_drops_instead_of_blocking():
    sub = QueuedSubscriber(lambda event: None, "tiny", maxsize=2)  # never started
    for i in range(10):
        sub(i)  # must return immediately every time


def test_cooldown_allows_once_per_window():
    now = [0.0]
    gate = Cooldown(30, clock=lambda: now[0])

    assert gate.allowed("a")
    assert not gate.allowed("a")
    assert gate.allowed("b")  # different key

    now[0] = 31
    assert gate.allowed("a")
