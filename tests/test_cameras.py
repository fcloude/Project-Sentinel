import sqlite3

import pytest
from app_support import csrf_token, log_in, make_security_config, use_temporary_database

from src.dashboard.app import create_app
from src.database import manager


@pytest.fixture
def client(tmp_path, monkeypatch):
    use_temporary_database(tmp_path, monkeypatch)
    app = create_app(engine=None, config=make_security_config(tmp_path))
    app.config["TESTING"] = True
    return app.test_client()


def token(client, path="/"):
    return csrf_token(client, path)


def login_as_admin(client):
    log_in(client)


def camera_rows():
    conn = sqlite3.connect(manager.settings.database_path)
    rows = conn.execute("SELECT name, kind, source_enc FROM cameras").fetchall()
    conn.close()
    return rows


def add_camera(client, name, kind, source):
    return client.post(
        "/cameras",
        data={"name": name, "kind": kind, "source": source,
              "csrf_token": token(client, "/cameras")},
        follow_redirects=True,
    )


def test_camera_password_is_masked_and_stored_encrypted(client):
    login_as_admin(client)

    response = add_camera(client, "Front door", "url", "rtsp://admin:s3cret@192.168.1.20:554/stream1")
    html = response.get_data(as_text=True)

    assert "Front door" in html
    assert "s3cret" not in html
    assert "admin:***@192.168.1.20" in html

    stored = camera_rows()[0][2]
    assert "s3cret" not in stored
    assert "192.168.1.20" not in stored


def test_dangerous_address_schemes_are_rejected(client):
    login_as_admin(client)

    add_camera(client, "Evil", "url", "file:///etc/passwd")
    add_camera(client, "Evil2", "url", "javascript:alert(1)")

    assert camera_rows() == []


def test_empty_name_is_rejected(client):
    login_as_admin(client)
    add_camera(client, "   ", "usb", "0")
    assert camera_rows() == []


def test_camera_can_be_removed(client):
    login_as_admin(client)
    add_camera(client, "Garage", "usb", "0")
    assert len(camera_rows()) == 1

    conn = sqlite3.connect(manager.settings.database_path)
    camera_id = conn.execute("SELECT id FROM cameras").fetchone()[0]
    conn.close()

    client.post(f"/cameras/{camera_id}/delete", data={"csrf_token": token(client, "/cameras")})

    assert camera_rows() == []


def test_test_connection_returns_a_jpeg(client, sample_video):
    login_as_admin(client)

    response = client.post(
        "/api/cameras/test",
        data={"kind": "file", "source": sample_video},
        headers={"X-CSRF-Token": token(client, "/cameras")},
    )

    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"
    assert response.data[:2] == b"\xff\xd8"


def test_test_connection_to_unreachable_camera_gives_friendly_error(client):
    login_as_admin(client)

    response = client.post(
        "/api/cameras/test",
        data={"kind": "url", "source": "http://admin:s3cret@127.0.0.1:9/video"},
        headers={"X-CSRF-Token": token(client, "/cameras")},
    )

    assert response.status_code == 400
    assert "s3cret" not in response.get_data(as_text=True)
    assert "error" in response.get_json()


def test_test_connection_requires_login(client):
    login_as_admin(client)
    client.post("/logout", data={"csrf_token": token(client, "/")})

    response = client.post(
        "/api/cameras/test",
        data={"kind": "usb", "source": "0"},
        headers={"X-CSRF-Token": token(client, "/login")},
    )

    assert response.status_code == 401
