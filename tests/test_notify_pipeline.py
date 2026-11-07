import dataclasses
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from src.database import manager
from src.database.manager import DatabaseManager
from src.database.schema import initialize_database
from src.events.event import Event
from src.notifications.channels import (
    EmailChannel,
    TelegramChannel,
    WebhookChannel,
    WebPushChannel,
)
from src.notifications.dispatcher import NotificationDispatcher
from src.notifications.errors import describe_error
from src.notifications.models import Notification
from src.notifications.repository import NotificationRepository, iso
from src.notifications.webpush import PushSubscriptionGone, ensure_vapid_keys, public_key_from_pem
from src.notifications.worker import RETRY_DELAYS_SECONDS, OutboxWorker
from src.security.crypto import SecretBox


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        manager, "settings",
        dataclasses.replace(manager.settings, database_path=str(tmp_path / "data" / "t.db")),
    )
    initialize_database()
    conn = DatabaseManager().get_connection()
    repo = NotificationRepository(conn, SecretBox("test-secret"))
    return SimpleNamespace(repo=repo, tmp=tmp_path, conn=conn)


def make_notification(**kw):
    base = dict(title="Unknown person at Front door", body="Unknown person detected.",
                event_type="UNKNOWN_PERSON", camera_id=1, camera_name="Front door")
    base.update(kw)
    return Notification(**base)


# ---------------- channels: real HTTP to a local server ----------------

class Recorder(BaseHTTPRequestHandler):
    received = []
    reply = 200

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        Recorder.received.append((self.path, dict(self.headers), body))
        self.send_response(Recorder.reply)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def http_server():
    Recorder.received = []
    Recorder.reply = 200
    server = HTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/hook"
    server.shutdown()


def test_webhook_sends_json_and_a_valid_signature(http_server):
    WebhookChannel({"url": http_server, "secret": "s3cret"}).send(make_notification())

    path, headers, body = Recorder.received[0]
    data = json.loads(body)
    assert data["title"] == "Unknown person at Front door"
    assert data["camera"] == "Front door"

    import hashlib, hmac
    expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert headers["X-Sentinel-Signature"] == expected


def test_webhook_error_status_is_reported_without_the_url(http_server):
    Recorder.reply = 500
    with pytest.raises(requests.exceptions.HTTPError) as error:
        WebhookChannel({"url": http_server}).send(make_notification())
    assert "500" in describe_error(error.value)
    assert http_server not in describe_error(error.value)


def test_webhook_connection_error_message_is_safe():
    with pytest.raises(requests.exceptions.ConnectionError) as error:
        WebhookChannel({"url": "http://user:hunter2@127.0.0.1:9/x"}).send(make_notification())
    message = describe_error(error.value)
    assert "hunter2" not in message and "127.0.0.1" not in message


def test_telegram_sends_photo_when_there_is_one(tmp_path):
    image = tmp_path / "snap.jpg"
    image.write_bytes(b"\xff\xd8fake")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200)

    TelegramChannel({"bot_token": "123:ABC", "chat_id": "42"}, post=fake_post).send(
        make_notification(snapshot_path=str(image)))

    url, kwargs = calls[0]
    assert url.endswith("/sendPhoto") and "photo" in kwargs["files"]


def test_telegram_sends_text_without_a_photo():
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=200)

    TelegramChannel({"bot_token": "123:ABC", "chat_id": "42"}, post=fake_post).send(make_notification())
    assert calls[0].endswith("/sendMessage")


def test_email_sends_with_snapshot_attached(tmp_path):
    image = tmp_path / "snap.jpg"
    image.write_bytes(b"\xff\xd8fake")
    sent = {}

    class FakeSMTP:
        def __init__(self, *args): sent["args"] = args
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, context=None): sent["tls"] = True
        def login(self, user, password): sent["login"] = (user, password)
        def send_message(self, message): sent["message"] = message

    config = {"host": "smtp.example.com", "port": 587, "security": "starttls",
              "username": "me", "password": "pw", "from_addr": "s@example.com",
              "to_addrs": ["a@example.com"]}
    EmailChannel(config, smtp_factory=lambda *a: FakeSMTP(*a)).send(
        make_notification(snapshot_path=str(image)))

    assert sent["tls"] and sent["login"] == ("me", "pw")
    assert sent["message"]["Subject"].startswith("[Sentinel]")
    assert any(part.get_content_type() == "image/jpeg" for part in sent["message"].walk())


def test_email_smtp_errors_become_friendly_messages():
    import smtplib

    class BadLogin:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, u, p): raise smtplib.SMTPAuthenticationError(535, b"nope")

    config = {"host": "h", "port": 587, "security": "none", "username": "u", "password": "p",
              "from_addr": "a@b.com", "to_addrs": ["c@d.com"]}
    with pytest.raises(smtplib.SMTPAuthenticationError) as error:
        EmailChannel(config, smtp_factory=lambda *a: BadLogin(*a)).send(make_notification())
    assert "username or password" in describe_error(error.value)


# ---------------- storage, dispatch and delivery ----------------

def test_channel_secrets_are_encrypted_at_rest(env):
    channel_id = env.repo.add_channel("telegram", "Phone", {"bot_token": "123456789:SECRETSECRETSECRET", "chat_id": "42"})

    raw = env.conn.execute("SELECT config_enc FROM notification_channels").fetchone()[0]
    assert "SECRETSECRET" not in raw
    assert env.repo.get_channel(channel_id)["config"]["chat_id"] == "42"
    assert "SECRET" not in env.repo.list_channels()[0]["summary"]


def test_rule_fires_queues_and_respects_camera_and_cooldown(env):
    inapp = env.repo.add_channel("inapp", "In-app", {})
    env.repo.add_rule("Front unknowns", "unknown_person", 1, [inapp], cooldown_s=60)
    now = [0.0]
    dispatcher = NotificationDispatcher(lambda: env.repo, monotonic=lambda: now[0])

    event = Event(event_type="UNKNOWN_PERSON", source="Front door", message="Unknown person detected.",
                  metadata={"camera_id": 1})
    other_camera = Event(event_type="UNKNOWN_PERSON", source="Back", message="x", metadata={"camera_id": 2})

    assert dispatcher.handle(event) == 1
    assert dispatcher.handle(event) == 0           # cooldown
    assert dispatcher.handle(other_camera) == 0    # wrong camera
    now[0] = 61
    assert dispatcher.handle(event) == 1           # cooldown passed


def test_rule_outside_active_hours_is_silent(env):
    inapp = env.repo.add_channel("inapp", "In-app", {})
    env.repo.add_rule("Night", "motion", None, [inapp], start_time="22:00", end_time="06:00")
    noon = lambda: datetime(2026, 11, 4, 12, 0)
    dispatcher = NotificationDispatcher(lambda: env.repo, clock=noon)

    event = Event(event_type="MOTION_DETECTED", source="x", message="m", metadata={"camera_id": 1})
    assert dispatcher.handle(event) == 0


def test_worker_delivers_to_in_app_inbox(env):
    inapp = env.repo.add_channel("inapp", "In-app", {})
    env.repo.enqueue(None, inapp, make_notification())

    from src.notifications.channels import build_channel

    worker = OutboxWorker(lambda: env.repo,
                          lambda cid: build_channel("inapp", {}, repo=env.repo))
    assert worker.run_once() == 1

    assert env.repo.unread_count() == 1
    assert env.repo.recent_outbox()[0]["status"] == "sent"


def test_failed_delivery_is_retried_then_succeeds(env):
    class Flaky:
        calls = 0
        def send(self, notification):
            Flaky.calls += 1
            if Flaky.calls < 3:
                raise ConnectionError("no internet at http://secret-host/x")
            Flaky.ok = True

    webhook = env.repo.add_channel("webhook", "Home", {"url": "https://x.example/h"})
    now = [datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)]
    env.repo.enqueue(None, webhook, make_notification(), now=now[0])
    worker = OutboxWorker(lambda: env.repo, lambda cid: Flaky(), clock=lambda: now[0])

    worker.run_once()                                   # attempt 1 fails
    row = env.repo.recent_outbox()[0]
    assert row["status"] == "pending" and row["attempts"] == 1
    assert "secret-host" not in row["error"]           # the URL never reaches the database

    assert worker.run_once() == 0                       # not due yet
    now[0] += timedelta(seconds=RETRY_DELAYS_SECONDS[0])
    worker.run_once()                                   # attempt 2 fails
    now[0] += timedelta(seconds=RETRY_DELAYS_SECONDS[1])
    worker.run_once()                                   # attempt 3 succeeds
    assert env.repo.recent_outbox()[0]["status"] == "sent"


def test_alert_is_marked_failed_after_all_retries(env):
    class Down:
        def send(self, notification):
            raise ConnectionError("down")

    webhook = env.repo.add_channel("webhook", "Home", {"url": "https://x.example/h"})
    now = [datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)]
    env.repo.enqueue(None, webhook, make_notification(), now=now[0])
    worker = OutboxWorker(lambda: env.repo, lambda cid: Down(), clock=lambda: now[0])

    for delay in RETRY_DELAYS_SECONDS + (0,):
        worker.run_once()
        now[0] += timedelta(seconds=max(delay, 1) + 1)
    worker.run_once()

    assert env.repo.recent_outbox()[0]["status"] == "failed"


def test_misconfigured_channel_fails_once_without_retrying(env):
    from src.errors import UserFacingError

    class Misconfigured:
        def send(self, notification):
            raise UserFacingError("Bad settings.")

    webhook = env.repo.add_channel("webhook", "Home", {"url": "https://x.example/h"})
    env.repo.enqueue(None, webhook, make_notification())
    worker = OutboxWorker(lambda: env.repo, lambda cid: Misconfigured())

    worker.run_once()
    assert env.repo.recent_outbox()[0]["status"] == "failed"


def test_worker_thread_runs_and_stops(env):
    inapp = env.repo.add_channel("inapp", "In-app", {})
    from src.notifications.channels import build_channel

    env.repo.enqueue(None, inapp, make_notification())
    worker = OutboxWorker(lambda: env.repo, lambda cid: build_channel("inapp", {}, repo=env.repo),
                          poll_seconds=0.05)
    worker.start()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and env.repo.unread_count() == 0:
        time.sleep(0.02)
    worker.stop()

    assert env.repo.unread_count() == 1


def test_in_app_notifications_can_be_marked_read_and_have_snapshots_removed(env):
    old = iso(datetime.now(timezone.utc) - timedelta(days=60))
    snap = env.tmp / "old.jpg"
    snap.write_bytes(b"x")
    env.repo.add_inbox(make_notification(snapshot_path=str(snap), created_at=old))
    env.repo.add_inbox(make_notification())

    assert env.repo.unread_count() == 2
    env.repo.mark_all_read()
    assert env.repo.unread_count() == 0

    from src.notifications.worker import _delete_file
    for path in env.repo.purge_inbox(iso(datetime.now(timezone.utc) - timedelta(days=30))):
        _delete_file(path)
    assert not snap.exists()


def test_deleting_a_channel_removes_it_from_rules(env):
    a = env.repo.add_channel("webhook", "A", {"url": "https://a.example/"})
    b = env.repo.add_channel("webhook", "B", {"url": "https://b.example/"})
    rule_id = env.repo.add_rule("R", "motion", None, [a, b])

    env.repo.delete_channel(a)

    assert env.repo.list_rules()[0]["channel_ids"] == [b]


# ---------------- web push (logic only: no browser in tests) ----------------

def test_vapid_keys_are_created_once_and_have_the_right_public_key_format(tmp_path):
    pem_path, public_key = ensure_vapid_keys(tmp_path)
    same_path, same_key = ensure_vapid_keys(tmp_path)

    assert public_key == same_key
    assert pem_path == same_path
    import base64
    raw = base64.urlsafe_b64decode(public_key + "==")
    assert len(raw) == 65 and raw[0] == 4   # uncompressed P-256 point


def test_push_subscriptions_are_stored_and_dead_ones_removed(env):
    env.repo.add_push_subscription("https://push.example/1", "BPUB", "AUTH")
    env.repo.add_push_subscription("https://push.example/2", "BPUB", "AUTH")
    channel = WebPushChannel(env.repo, SimpleNamespace(
        pem_path="k.pem", contact="mailto:a@b.com",
        sender=lambda sub, payload, pem, contact: (_ for _ in ()).throw(PushSubscriptionGone())
        if sub["endpoint"].endswith("/1") else None))

    channel.send(make_notification())

    remaining = [s["endpoint"] for s in env.repo.list_push_subscriptions()]
    assert remaining == ["https://push.example/2"]


def test_push_without_any_subscription_explains_what_to_do(env):
    from src.errors import UserFacingError

    channel = WebPushChannel(env.repo, SimpleNamespace(pem_path="k", contact="c", sender=None))
    with pytest.raises(UserFacingError) as error:
        channel.send(make_notification())
    assert "Enable push" in str(error.value)
