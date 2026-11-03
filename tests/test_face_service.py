import dataclasses

import pytest
from face_fakes import encode, fake_backends, make_photo
from types import SimpleNamespace

from src.database import manager
from src.database.manager import DatabaseManager
from src.database.people_repository import PeopleRepository, SettingsRepository, now_iso
from src.database.schema import initialize_database
from src.faces.service import STRICTNESS, FaceService, FaceServiceError


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(
        manager,
        "settings",
        dataclasses.replace(manager.settings, database_path=str(tmp_path / "data" / "t.db")),
    )
    initialize_database()
    svc = FaceService(
        lambda: DatabaseManager().get_connection(), fake_backends, unknown_dir=tmp_path / "unknown"
    )
    svc.reload()
    return svc


def repo():
    return PeopleRepository(DatabaseManager().get_connection())


def frame_of(*people, **kwargs):
    return SimpleNamespace(data=make_photo(people, **kwargs))


def enrol(name, *photo_people, seeds=(7,)):
    person_id = repo().create_person(name, consent=True)
    return person_id, [(f"{name}{i}.jpg", encode(make_photo(photo_people, seed=s))) for i, s in enumerate(seeds)]


def test_enrolled_person_is_recognised_and_strangers_are_not(service):
    person_id, photos = enrol("Alice", "alice", seeds=(7, 8))
    outcomes = service.enroll_photos(person_id, photos)
    assert [o.ok for o in outcomes] == [True, True]

    alice = service.process(frame_of("alice", seed=99))[0]
    bob = service.process(frame_of("bob"))[0]

    assert alice.recognized and alice.name == "Alice" and alice.person_id == person_id
    assert not bob.recognized and bob.name == "Unknown"


def test_two_faces_in_one_frame_are_judged_separately(service):
    person_id, photos = enrol("Alice", "alice")
    service.enroll_photos(person_id, photos)

    results = service.process(frame_of("alice", "bob"))

    assert [r.name for r in results] == ["Alice", "Unknown"]


def test_bad_photos_are_rejected_with_a_reason(service):
    person_id = repo().create_person("Alice", consent=True)
    photos = [
        ("blank.jpg", encode(make_photo([]))),
        ("two.jpg", encode(make_photo(["alice", "bob"]))),
        ("small.jpg", encode(make_photo(["alice"], face=40))),
        ("blurry.jpg", encode(make_photo(["alice"], blur=True))),
        ("junk.jpg", b"definitely not an image"),
        ("empty.jpg", b""),
        ("good.jpg", encode(make_photo(["alice"]))),
    ]

    outcomes = {o.filename: o for o in service.enroll_photos(person_id, photos)}

    assert "No face" in outcomes["blank.jpg"].reason
    assert "More than one face" in outcomes["two.jpg"].reason
    assert "too small" in outcomes["small.jpg"].reason
    assert "blurry" in outcomes["blurry.jpg"].reason
    assert "not a readable image" in outcomes["junk.jpg"].reason
    assert "not a readable image" in outcomes["empty.jpg"].reason
    assert outcomes["good.jpg"].ok
    assert repo().list_people()[0]["photo_count"] == 1


def test_unknown_faces_are_saved_once_and_repeat_sightings_are_counted(service, tmp_path):
    frame = frame_of("carol")
    result = service.process(frame)[0]

    first = service.record_unknown(1, result, frame)
    again = service.record_unknown(1, result, frame)
    other_frame = frame_of("bob")
    other = service.record_unknown(1, service.process(other_frame)[0], other_frame)

    assert first == again and other != first
    rows = {r["id"]: r for r in repo().list_unknown()}
    assert rows[first]["seen_count"] == 2
    assert len(rows) == 2
    assert list((tmp_path / "unknown").rglob("*.jpg"))


def test_naming_an_unknown_face_teaches_the_system(service, tmp_path):
    frame = frame_of("carol")
    unknown_id = service.record_unknown(1, service.process(frame)[0], frame)
    crop = repo().get_unknown(unknown_id)["crop_path"]

    service.promote_unknown(unknown_id, name="Carol", consent=True)

    assert service.process(frame_of("carol"))[0].name == "Carol"
    assert repo().count_unknown() == 0
    assert not __import__("pathlib").Path(crop).exists()   # image deleted once it's no longer needed


def test_naming_requires_consent_a_valid_name_and_a_new_name(service):
    frame = frame_of("carol")
    unknown_id = service.record_unknown(1, service.process(frame)[0], frame)
    repo().create_person("Dave", consent=True)

    with pytest.raises(FaceServiceError, match="agreed"):
        service.promote_unknown(unknown_id, name="Carol", consent=False)
    with pytest.raises(FaceServiceError, match="name"):
        service.promote_unknown(unknown_id, name="  ", consent=True)
    with pytest.raises(FaceServiceError, match="already exists"):
        service.promote_unknown(unknown_id, name="dave", consent=True)   # not case-sensitive

    assert repo().count_unknown() == 1   # nothing changed


def test_unknown_face_can_be_added_to_an_existing_person(service):
    person_id, photos = enrol("Alice", "alice")
    service.enroll_photos(person_id, photos)
    frame = frame_of("alice", seed=3)
    # pretend this sighting was not matched: save it as unknown directly
    result = service.process(frame)[0]
    unknown_id = service.record_unknown(1, result, frame)

    service.promote_unknown(unknown_id, person_id=person_id)

    assert repo().list_people()[0]["photo_count"] == 2


def test_dismissing_deletes_the_face_and_its_image(service):
    frame = frame_of("carol")
    unknown_id = service.record_unknown(1, service.process(frame)[0], frame)
    crop = repo().get_unknown(unknown_id)["crop_path"]

    service.dismiss_unknown(unknown_id)

    assert repo().count_unknown() == 0
    assert not __import__("pathlib").Path(crop).exists()


def test_old_unknown_faces_are_deleted_by_retention(service, tmp_path):
    folder = tmp_path / "unknown" / "1"
    folder.mkdir(parents=True)
    old_file, new_file = folder / "old.jpg", folder / "new.jpg"
    old_file.write_bytes(b"x")
    new_file.write_bytes(b"x")

    vector = [1.0, 0.0, 0.0]
    repo().add_unknown(1, service.model_id, vector, str(old_file), seen_at="2020-01-01T00:00:00+00:00")
    repo().add_unknown(1, service.model_id, vector, str(new_file), seen_at=now_iso())

    service.purge_unknowns(days=7)

    assert repo().count_unknown() == 1
    assert not old_file.exists() and new_file.exists()


def test_strictness_setting_changes_the_threshold(service):
    assert service.threshold == STRICTNESS["balanced"]

    SettingsRepository(DatabaseManager().get_connection()).set("face_strictness", "strict")
    service.reload()

    assert service.threshold == STRICTNESS["strict"]


def test_embeddings_from_another_model_are_ignored_and_counted(service):
    person_id = repo().create_person("Alice", consent=True)
    repo().add_embedding(person_id, "some-older-model", [1.0, 0.0, 0.0], quality=1.0)

    service.reload()

    assert len(service.index) == 0
    assert service.stale_embeddings == 1


def test_deleting_a_person_removes_their_face_data(service):
    person_id, photos = enrol("Alice", "alice")
    service.enroll_photos(person_id, photos)
    assert service.process(frame_of("alice"))[0].recognized

    repo().delete_person(person_id)
    service.reload()

    assert not service.process(frame_of("alice"))[0].recognized
    count = DatabaseManager().get_connection().execute("SELECT COUNT(*) FROM face_embeddings").fetchone()[0]
    assert count == 0
