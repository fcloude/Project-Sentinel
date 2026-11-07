from dataclasses import dataclass
from pathlib import Path

from src.database import manager
from src.database.manager import DatabaseManager
from src.database.people_repository import SettingsRepository
from src.errors import UserFacingError
from src.notifications.channels import build_channel
from src.notifications.dispatcher import NotificationDispatcher
from src.notifications.repository import NotificationRepository
from src.notifications.webpush import DEFAULT_CONTACT, ensure_vapid_keys, pywebpush_sender
from src.notifications.worker import OutboxWorker
from src.security.crypto import SecretBox, get_encryption_keys


def data_dir() -> Path:
    return Path(manager.settings.database_path).parent


def default_repo_factory():
    """A repository on its own connection: call it once per thread."""
    box = SecretBox(get_encryption_keys())
    return NotificationRepository(DatabaseManager().get_connection(), box)


@dataclass
class PushSettings:
    pem_path: object
    contact: str
    sender: object


class ChannelFactory:
    """channel id -> a ready-to-use channel object (reads its encrypted settings)."""

    def __init__(self, repo, push_sender=pywebpush_sender):
        self.repo = repo
        self.push_sender = push_sender

    def __call__(self, channel_id, require_enabled=True):
        channel = self.repo.get_channel(channel_id)

        if channel is None:
            raise UserFacingError("That alert channel was removed.")
        if require_enabled and not channel["enabled"]:
            raise UserFacingError("That alert channel is switched off.")
        if channel["config"] is None:
            raise UserFacingError(
                "This channel's saved settings can't be read (the secret key changed). "
                "Delete it and add it again."
            )

        push = None
        if channel["type"] == "webpush":
            pem_path, _ = ensure_vapid_keys(data_dir())
            contact = SettingsRepository(self.repo.conn).get("push_contact", DEFAULT_CONTACT)
            push = PushSettings(pem_path, contact, self.push_sender)

        return build_channel(channel["type"], channel["config"], repo=self.repo, push=push)


def build_dispatcher() -> NotificationDispatcher:
    return NotificationDispatcher(default_repo_factory)


def build_outbox_worker() -> OutboxWorker:
    # The repository (and its database connection) is created on the worker's own thread.
    holder = {}

    def repo_factory():
        holder["repo"] = default_repo_factory()
        holder["factory"] = ChannelFactory(holder["repo"])
        return holder["repo"]

    def lazy_channel_factory(channel_id):
        return holder["factory"](channel_id)

    return OutboxWorker(repo_factory, lazy_channel_factory)
