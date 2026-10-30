import dataclasses
import re

import pytest

from src.dashboard.app import create_app
from src.database import manager


class FakeEngine:
    def __init__(self):
        self.running = False
        self.calls = []

    @property
    def status(self):
        return {"running": self.running, "thread_alive": self.running}

    def start(self):
        self.calls.append("start")
        self.running = True

    def stop(self):
        self.calls.append("stop")
        self.running = False

    def restart(self):
        self.calls.append("restart")
        self.running = True


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def client(tmp_path, monkeypatch, engine):
    test_settings = dataclasses.replace(
        manager.settings,
        database_path=str(tmp_path / "data" / "test.db"),
        allow_file_sources=True,
    )
    monkeypatch.setattr(manager, "settings", test_settings)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    app = create_app(engine=engine)
    app.config["TESTING"] = True
    return app.test_client()


PASSWORD = "correct-horse-battery"


def token(client, path="/login"):
    html = client.get(path, follow_redirects=True).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def setup_admin(client, username="admin", password=PASSWORD):
    return client.post(
        "/setup",
        data={
            "username": username,
            "password": password,
            "confirm": password,
            "csrf_token": token(client, "/setup"),
        },
    )


def logout(client):
    client.post("/logout", data={"csrf_token": token(client, "/")})


def login(client, password=PASSWORD):
    return client.post(
        "/login",
        data={"username": "admin", "password": password, "csrf_token": token(client, "/login")},
    )


def test_first_visit_redirects_to_setup(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/setup" in response.headers["Location"]


def test_health_is_public_even_before_setup(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_setup_creates_admin_and_logs_in(client):
    response = setup_admin(client)
    assert response.status_code == 302
    assert client.get("/").status_code == 200


def test_setup_rejects_short_password(client):
    response = setup_admin(client, password="short")
    assert response.status_code == 200
    assert b"at least 10" in response.data
    assert client.get("/").status_code == 302  # still no admin: back to setup


def test_setup_is_closed_after_first_admin(client):
    setup_admin(client)
    logout(client)
    response = client.get("/setup")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_dashboard_requires_login(client):
    setup_admin(client)
    logout(client)
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_wrong_password_is_rejected_and_right_one_works(client):
    setup_admin(client)
    logout(client)

    assert login(client, password="wrong-password-123").status_code == 401
    assert login(client).status_code == 302


def test_post_without_csrf_token_is_rejected(client):
    response = client.post("/login", data={"username": "admin", "password": "x"})
    assert response.status_code == 400


def test_login_is_rate_limited(client):
    setup_admin(client)
    logout(client)
    t = token(client, "/login")

    for _ in range(5):
        client.post("/login", data={"username": "admin", "password": "nope-nope-nope", "csrf_token": t})

    response = client.post(
        "/login", data={"username": "admin", "password": PASSWORD, "csrf_token": t}
    )
    assert response.status_code == 429


def test_engine_controls_call_the_engine(client, engine):
    setup_admin(client)
    t = token(client, "/")

    client.post("/engine/start", data={"csrf_token": t})
    client.post("/engine/stop", data={"csrf_token": t})

    assert engine.calls == ["start", "stop"]


def test_engine_control_needs_login(client, engine):
    setup_admin(client)
    logout(client)
    t = token(client, "/login")

    response = client.post("/engine/start", data={"csrf_token": t})

    assert response.status_code == 302
    assert engine.calls == []


def test_security_headers_and_cookie_flags(client):
    response = client.get("/setup")

    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]

    cookie = " ".join(response.headers.getlist("Set-Cookie"))
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_html_in_event_messages_is_escaped(client):
    from src.database.repository import EventRepository
    from src.events.event import Event

    setup_admin(client)
    EventRepository().save(
        Event(event_type="X", source="t", message="<script>alert(1)</script>")
    )

    html = client.get("/events").get_data(as_text=True)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
