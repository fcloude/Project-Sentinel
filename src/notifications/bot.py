from telegram.ext import (
    Application,
)

from src.notifications.handlers import register_handlers
from telegram.ext import Application

class SentinelBot:

    def __init__(self, token):

        self.app = (
            Application
            .builder()
            .token(token)
            .build()
        )

        register_handlers(
            self.app,
        )

    def run(self):

        self.app.run_polling()