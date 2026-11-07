import pytest
from app_support import (
    csrf_token,
    log_in as register_and_login,
    make_security_config,
    use_temporary_database,
)
from cryptography.fernet import Fernet

from src.dashboard.app import create_app
from src.database.manager import DatabaseManager
from src.notifications.models import Notification
from src.notifications.repository import NotificationRepository
from src.security.crypto import SecretBox

# The app writes channel secrets with its configured key; the tests read them back with it.
TEST_KEY = Fernet.generate_key().decode()


class RecordingChannelFactory:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def __call__(self, channel_id, require_enabled=True):
        factory = self

        class Channel:
            def send(self, notification):
                if factory.fail:
                    raise ConnectionError("unreachable")
                factory.sent.append((channel_id, notification.title))

        return Channel()


@pytest.fixture
def client(tmp_path, monkeypatch):
    use_temporary_database(tmp_path, monkeypatch)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    app = create_app(
        engine=None,
        config=make_security_config(tmp_path, encryption_key=TEST_KEY),
        overrides={"CHANNEL_FACTORY": RecordingChannelFactory()},
    )
    app.config["TESTING"] = True
    return app.test_client()


def token(client, path="/"):
    return csrf_token(client, path)


def log_in(client):
    register_and_login(client)


def repo():
    return NotificationRepository(
        DatabaseManager().get_connection(), SecretBox([TEST_KEY])
    )


def test_first_run_seeds_in_app_channel_and_default_rules(client):
    log_in(client)
    r = repo()

    assert [c["type"] for c in r.list_channels()] == ["inapp"]
    names = sorted(rule["name"] for rule in r.list_rules())
    assert names == ["Known person arrives", "Unknown person"]


def test_alerts_page_loads_and_explains_channels(client):
    log_in(client)
    html = client.get("/alerts").get_data(as_text=True)

    assert "Where alerts go" in html and "When alerts are sent" in html
    assert "Add Telegram" in html and "Add Email" in html and "Add Webhook" in html


def test_adding_a_webhook_channel_and_testing_it(client):
    log_in(client)
    t = token(client, "/alerts")

    client.post("/alerts/channels", data={
        "type": "webhook", "name": "Home Assistant", "url": "https://ha.local/api/webhook/x",
        "secret": "s", "csrf_token": t})
    channel = [c for c in repo().list_channels() if c["type"] == "webhook"][0]

    html = client.post(f"/alerts/channels/{channel['id']}/test",
                       data={"csrf_token": t}, follow_redirects=True).get_data(as_text=True)

    assert "Test sent" in html
    assert "ha.local" in client.get("/alerts").get_data(as_text=True)  # shown as masked summary
    assert "(signed)" in client.get("/alerts").get_data(as_text=True)


def test_bad_channel_form_shows_a_friendly_error(client):
    log_in(client)
    html = client.post("/alerts/channels", data={
        "type": "telegram", "bot_token": "nope", "chat_id": "1",
        "csrf_token": token(client, "/alerts")}, follow_redirects=True).get_data(as_text=True)

    assert "look like a Telegram bot token" in html   # Jinja escapes the apostrophe


def test_secrets_never_appear_on_the_alerts_page(client):
    log_in(client)
    client.post("/alerts/channels", data={
        "type": "webhook", "url": "https://user:TOPSECRETPW@ha.local/x", "secret": "SIGNKEY123",
        "csrf_token": token(client, "/alerts")})

    html = client.get("/alerts").get_data(as_text=True)
    assert "TOPSECRETPW" not in html and "SIGNKEY123" not in html


def test_inbox_page_and_mark_read(client):
    log_in(client)
    repo().add_inbox(Notification(title="Unknown person at Front", body="seen", camera_name="Front"))

    assert "Unknown person at Front" in client.get("/notifications").get_data(as_text=True)
    assert 'id="unread-badge"' in client.get("/notifications").get_data(as_text=True)

    client.post("/notifications/read", data={"csrf_token": token(client, "/notifications")})
    assert repo().unread_count() == 0


def test_stream_endpoint_is_event_stream_and_login_protected(client):
    log_in(client)
    response = client.get("/api/notifications/stream")
    first = next(iter(response.response))
    response.close()
    assert response.mimetype == "text/event-stream"
    assert first.startswith(b"data: ")

    client.post("/logout", data={"csrf_token": token(client, "/")})
    assert client.get("/api/notifications/stream").status_code == 401   # API: JSON 401, not a redirect


def test_snapshot_only_served_from_snapshots_folder(client, tmp_path):
    log_in(client)
    inside = tmp_path / "snapshots" / "1"
    inside.mkdir(parents=True)
    good = inside / "a.jpg"
    good.write_bytes(b"\xff\xd8ok")
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"\xff\xd8secret")

    good_id = repo().add_inbox(Notification(title="a", body="b", snapshot_path=str(good)))
    bad_id = repo().add_inbox(Notification(title="a", body="b", snapshot_path=str(outside)))

    assert client.get(f"/notifications/{good_id}/snapshot.jpg").status_code == 200
    assert client.get(f"/notifications/{bad_id}/snapshot.jpg").status_code == 404


def test_push_subscription_is_validated_and_creates_the_push_channel(client):
    log_in(client)
    t = token(client, "/alerts")

    bad = client.post("/api/push/subscribe", json={"endpoint": "http://insecure.example/x",
                                                   "keys": {"p256dh": "x", "auth": "y"}},
                      headers={"X-CSRF-Token": t})
    assert bad.status_code == 400

    good = client.post("/api/push/subscribe", json={
        "endpoint": "https://push.example.com/abc123",
        "keys": {"p256dh": "BPubKeyValueLongEnough1234", "auth": "AuthValue123456"}},
        headers={"X-CSRF-Token": t})
    assert good.status_code == 200
    assert "webpush" in [c["type"] for c in repo().list_channels()]


def test_push_public_key_endpoint(client):
    log_in(client)
    key = client.get("/api/push/public-key").get_json()["publicKey"]
    assert len(key) >= 80


def test_service_worker_and_manifest_are_public_and_served(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.mimetype
    assert response.headers["Service-Worker-Allowed"] == "/"

    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and b"Project Sentinel" in manifest.data


def test_rules_can_be_added_toggled_and_deleted(client):
    log_in(client)
    t = token(client, "/alerts")
    channel = repo().list_channels()[0]

    client.post("/alerts/rules", data={
        "name": "Night watch", "trigger": "motion", "camera_id": "", "channel_ids": [str(channel["id"])],
        "start_time": "22:00", "end_time": "06:00", "cooldown_s": "120", "attach_snapshot": "on",
        "csrf_token": t})
    rule = [r for r in repo().list_rules() if r["name"] == "Night watch"][0]
    assert rule["start_time"] == "22:00" and rule["cooldown_s"] == 120

    client.post(f"/alerts/rules/{rule['id']}/toggle", data={"csrf_token": t})
    assert [r for r in repo().list_rules() if r["id"] == rule["id"]][0]["enabled"] is False

    client.post(f"/alerts/rules/{rule['id']}/delete", data={"csrf_token": t})
    assert all(r["id"] != rule["id"] for r in repo().list_rules())


def test_the_builtin_inapp_channel_cannot_be_deleted(client):
    log_in(client)
    channel = repo().list_channels()[0]
    html = client.post(f"/alerts/channels/{channel['id']}/delete", data={"csrf_token": token(client, "/alerts")},
                       follow_redirects=True).get_data(as_text=True)
    assert "can&#39;t be deleted" in html   # Jinja escapes the apostrophe
    assert len(repo().list_channels()) == 1


def test_notifications_pages_need_login(client):
    log_in(client)
    client.post("/logout", data={"csrf_token": token(client, "/")})
    for path in ("/alerts", "/notifications"):
        assert client.get(path).status_code == 302      # pages redirect to login
    assert client.get("/api/notifications/unread").status_code == 401   # APIs answer 401


def test_existing_telegram_env_settings_are_imported_once(client, monkeypatch):
    from src.notifications.defaults import import_telegram_from_env

    log_in(client)
    r = repo()
    env = {"TELEGRAM_BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ", "TELEGRAM_CHAT_ID": "42"}

    assert import_telegram_from_env(r, env) is True
    assert import_telegram_from_env(r, env) is False      # not imported twice
    telegram = [c for c in r.list_channels() if c["type"] == "telegram"]
    assert len(telegram) == 1
