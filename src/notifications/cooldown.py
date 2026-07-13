import time


class CooldownManager:

    def __init__(self, seconds: int):

        self.seconds = seconds

        self.last_sent = {}

    def allowed(self, key: str) -> bool:

        now = time.time()

        previous = self.last_sent.get(
            key,
            0,
        )

        if now - previous < self.seconds:

            return False

        self.last_sent[key] = now

        return True