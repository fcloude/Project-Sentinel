import dataclasses
import re

import pytest

from src.dashboard.app import create_app
from src.database import manager
from src.database.camera_repository import CameraRepository
from src.database.manager import DatabaseManager
from src.database.schema import initialize_database
from src.security.crypto import SecretBox


class FakeWorker:
    stopped = False

    def latest_jpeg(self):
        return b"\xff\xd8fake-jpeg-bytes\xff\xd9", 1


class StreamEngine:
    running = True
    status = {
        "running": True, "thread_alive": True, "loading": False, "error": None,
        "cameras": [{"id": 1, "name": "Front", "state": "online", "error": None}],
    }

    def __init__(self):
        self.workers = {1: FakeWorker()}

    def get_worker(self, camera_id):
        return self.workers.get(camera_id)

    def start(self): ...
    def stop(self): ...
    def restart(self): ...


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_settings = dataclasses.replace(
        manager.settings, database_path=str(tmp_path / "data" / "test.db")
    )
    monkeypatch.setattr(manager, "settings", test_settings)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    app = create_app(engine=StreamEngine())
    app.config["TESTING"] = True
    return app.test_client()


def token(client, path="/"):
    html = client.get(path, follow_redirects=True).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def log_in(client):
    pw = "correct-horse-battery"
    client.post(
        "/setup",
        data={"username": "admin", "password": pw, "confirm": pw,
              "csrf_token": token(client, "/setup")},
    )


def test_stream_sends_mjpeg_frames(client):
    log_in(client)

    response = client.get("/cameras/1/stream.mjpg")
    first_chunk = next(iter(response.response))
    response.close()

    assert response.status_code == 200
    assert response.mimetype == "multipart/x-mixed-replace"
    assert first_chunk.startswith(b"--frame")
    assert b"\xff\xd8" in first_chunk


def test_stream_for_unknown_camera_is_404(client):
    log_in(client)
    assert client.get("/cameras/99/stream.mjpg").status_code == 404


def test_stream_requires_login(client):
    log_in(client)
    client.post("/logout", data={"csrf_token": token(client, "/")})

    response = client.get("/cameras/1/stream.mjpg")

    assert response.status_code == 302


def test_status_api_includes_camera_states(client):
    log_in(client)

    data = client.get("/api/status").get_json()

    assert data["cameras"][0]["state"] == "online"
    assert data["loading"] is False


def test_dashboard_shows_live_tiles_for_saved_cameras(client):
    log_in(client)
    t = token(client, "/cameras")
    client.post("/cameras", data={"name": "Garage", "kind": "usb", "source": "0", "csrf_token": t})

    html = client.get("/").get_data(as_text=True)

    assert 'data-camera-id="' in html
    assert "Garage" in html


def test_list_enabled_returns_decrypted_sources(tmp_path, monkeypatch):
    test_settings = dataclasses.replace(
        manager.settings, database_path=str(tmp_path / "data" / "test.db")
    )
    monkeypatch.setattr(manager, "settings", test_settings)
    initialize_database()

    conn = DatabaseManager().get_connection()
    repo = CameraRepository(conn, SecretBox("k"))
    repo.add("Door", "url", "rtsp://admin:pw@10.0.0.5/s")
    repo.add("Webcam", "usb", "0")

    cameras = repo.list_enabled()
    conn.close()

    assert [c["name"] for c in cameras] == ["Door", "Webcam"]
    assert cameras[0]["source"] == "rtsp://admin:pw@10.0.0.5/s"
    assert cameras[0]["detection_fps"] == 3


def test_list_enabled_skips_cameras_it_cannot_decrypt(tmp_path, monkeypatch):
    test_settings = dataclasses.replace(
        manager.settings, database_path=str(tmp_path / "data" / "test.db")
    )
    monkeypatch.setattr(manager, "settings", test_settings)
    initialize_database()

    conn = DatabaseManager().get_connection()
    CameraRepository(conn, SecretBox("old-key")).add("Door", "usb", "0")

    assert CameraRepository(conn, SecretBox("new-key")).list_enabled() == []
    conn.close()
