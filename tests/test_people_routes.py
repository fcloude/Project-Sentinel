import io
import sqlite3
from types import SimpleNamespace

import pytest
from app_support import (
    csrf_token,
    log_in as register_and_login,
    make_security_config,
    use_temporary_database,
)
from face_fakes import encode, fake_backends, make_photo

from src.dashboard.app import create_app
from src.database import manager
from src.database.manager import DatabaseManager
from src.faces.backends import ModelsMissingError
from src.faces.service import STRICTNESS, FaceService


@pytest.fixture
def service(tmp_path, monkeypatch):
    use_temporary_database(tmp_path, monkeypatch)
    return FaceService(
        lambda: DatabaseManager().get_connection(), fake_backends, unknown_dir=tmp_path / "unknown"
    )


def build_client(config, factory):
    app = create_app(engine=None, config=config, overrides={"FACE_SERVICE_FACTORY": factory})
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def client(service, tmp_path):
    return build_client(make_security_config(tmp_path), lambda: service)


def token(client, path="/"):
    return csrf_token(client, path)


def log_in(client):
    register_and_login(client)


def photos(*kinds, **kw):
    return [(io.BytesIO(encode(make_photo(k, **kw))), f"p{i}.jpg") for i, k in enumerate(kinds)]


def add_person(client, name="Alice", consent=True, files=None, path="/people"):
    data = {"name": name, "csrf_token": token(client, "/people"),
            "photos": files if files is not None else photos(["alice"], ["alice"])}
    if consent:
        data["consent"] = "on"
    return client.post(path, data=data, content_type="multipart/form-data", follow_redirects=True)


def db_rows(query):
    conn = sqlite3.connect(manager.settings.database_path)
    rows = conn.execute(query).fetchall()
    conn.close()
    return rows


def test_pages_need_login(client):
    for path in ("/people", "/unknown", "/settings"):
        log_in(client)
        client.post("/logout", data={"csrf_token": token(client, "/")})
        assert client.get(path).status_code == 302


def test_adding_a_person_with_photos(client):
    log_in(client)

    html = add_person(client).get_data(as_text=True)

    assert "Alice added with 2 photo" in html
    assert db_rows("SELECT name FROM people") == [("Alice",)]
    assert db_rows("SELECT COUNT(*) FROM face_embeddings") == [(2,)]


def test_consent_is_required(client):
    log_in(client)

    html = add_person(client, consent=False).get_data(as_text=True)

    assert "agreed" in html
    assert db_rows("SELECT COUNT(*) FROM people") == [(0,)]


def test_when_no_photo_is_usable_nobody_is_added(client):
    log_in(client)

    html = add_person(client, files=photos([], [])).get_data(as_text=True)

    assert "No face found" in html
    assert "nobody was added" in html
    assert db_rows("SELECT COUNT(*) FROM people") == [(0,)]


def test_duplicate_names_are_refused(client):
    log_in(client)
    add_person(client)

    html = add_person(client, name="alice").get_data(as_text=True)

    assert "already exists" in html
    assert db_rows("SELECT COUNT(*) FROM people") == [(1,)]


def test_more_photos_can_be_added_later(client):
    log_in(client)
    add_person(client, files=photos(["alice"]))
    person_id = db_rows("SELECT id FROM people")[0][0]

    response = client.post(
        f"/people/{person_id}/photos",
        data={"csrf_token": token(client, "/people"), "photos": photos(["alice"], ["alice"])},
        content_type="multipart/form-data", follow_redirects=True,
    )

    assert "Added 2 photo" in response.get_data(as_text=True)
    assert db_rows("SELECT COUNT(*) FROM face_embeddings") == [(3,)]


def test_deleting_a_person_deletes_their_face_data(client, service):
    log_in(client)
    add_person(client)
    person_id = db_rows("SELECT id FROM people")[0][0]

    client.post(f"/people/{person_id}/delete", data={"csrf_token": token(client, "/people")})

    assert db_rows("SELECT COUNT(*) FROM people") == [(0,)]
    assert db_rows("SELECT COUNT(*) FROM face_embeddings") == [(0,)]
    assert len(service.index) == 0


def test_people_page_works_even_when_models_are_missing(service, tmp_path):
    def no_models():
        raise ModelsMissingError("Face recognition models are missing. Run: python scripts/download_models.py")

    client = build_client(make_security_config(tmp_path), no_models)
    log_in(client)

    assert client.get("/people").status_code == 200

    html = add_person(client).get_data(as_text=True)
    assert "download_models" in html
    assert db_rows("SELECT COUNT(*) FROM people") == [(0,)]


def seed_unknown(service, who="carol"):
    frame = SimpleNamespace(data=make_photo([who]))
    return service.record_unknown(1, service.process(frame)[0], frame)


def test_unknown_inbox_lists_serves_names_and_dismisses(client, service):
    log_in(client)
    first = seed_unknown(service, "carol")
    second = seed_unknown(service, "bob")

    page = client.get("/unknown").get_data(as_text=True)
    assert "seen 1 time" in page
    assert "badge warn" in page            # nav count badge

    crop = client.get(f"/unknown/{first}/crop.jpg")
    assert crop.status_code == 200 and crop.data[:2] == b"\xff\xd8"

    t = token(client, "/unknown")
    client.post(f"/unknown/{first}/name", data={"name": "Carol", "consent": "on", "csrf_token": t})
    client.post(f"/unknown/{second}/dismiss", data={"csrf_token": t})

    assert db_rows("SELECT name FROM people") == [("Carol",)]
    assert db_rows("SELECT COUNT(*) FROM unknown_faces") == [(0,)]


def test_unknown_crop_requires_login_and_stays_inside_its_folder(client, service, tmp_path):
    log_in(client)
    unknown_id = seed_unknown(service)

    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"\xff\xd8secret")
    conn = sqlite3.connect(manager.settings.database_path)
    conn.execute("UPDATE unknown_faces SET crop_path = ?", (str(secret),))
    conn.commit()
    conn.close()

    assert client.get(f"/unknown/{unknown_id}/crop.jpg").status_code == 404   # outside the folder

    client.post("/logout", data={"csrf_token": token(client, "/")})
    assert client.get(f"/unknown/{unknown_id}/crop.jpg").status_code == 302


def test_naming_without_consent_shows_an_error(client, service):
    log_in(client)
    unknown_id = seed_unknown(service)

    response = client.post(
        f"/unknown/{unknown_id}/name",
        data={"name": "Carol", "csrf_token": token(client, "/unknown")},
        follow_redirects=True,
    )

    assert "agreed" in response.get_data(as_text=True)
    assert db_rows("SELECT COUNT(*) FROM people") == [(0,)]


def test_strictness_can_be_changed(client, service):
    log_in(client)

    client.post("/settings", data={"strictness": "strict", "csrf_token": token(client, "/settings")})
    assert service.threshold == STRICTNESS["strict"]

    html = client.post(
        "/settings", data={"strictness": "nonsense", "csrf_token": token(client, "/settings")},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "Choose one of the listed options" in html
    assert service.threshold == STRICTNESS["strict"]
