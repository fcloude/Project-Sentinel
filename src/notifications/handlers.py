from telegram.ext import (
    CommandHandler,
)

from notifications.commands import (
    ping,
    start,
    status,
)


def register_handlers(
    app,
):

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "ping",
            ping,
        )
    )

    app.add_handler(
        CommandHandler(
            "status",
            status,
        )
    )