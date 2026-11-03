import dataclasses
import time
from types import SimpleNamespace

import pytest

from src.camera.file_camera import FileCamera
from src.database import manager
from src.engine.engine import SentinelEngine
from src.faces.backends import ModelsMissingError


def wait_for(predicate, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class FakeFaces:
    def __init__(self):
        self.unknown_calls = []

    def process(self, frame):
        return [
            SimpleNamespace(recognized=True, name="Aryan"),
            SimpleNamespace(recognized=False, name="Unknown"),
        ]

    def record_unknown(self, camera_id, result, frame):
        self.unknown_calls.append(camera_id)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    test_settings = dataclasses.replace(
        manager.settings, database_path=str(tmp_path / "data" / "test.db")
    )
    monkeypatch.setattr(manager, "settings", test_settings)


def make_engine(tmp_path, video, cameras=None, **overrides):
    if cameras is None:
        cameras = [
            {"id": 1, "name": "Front door", "kind": "file", "source": video, "detection_fps": 20}
        ]
    options = dict(
        camera_loader=lambda: cameras,
        source_factory=lambda camera: (lambda: FileCamera(camera["source"])),
        models_loader=lambda: FakeFaces(),
        notifier_factory=lambda: None,
        snapshot_dir=str(tmp_path / "snaps"),
        fps_override=20,
        persist_events=False,
    )
    options.update(overrides)
    return SentinelEngine(**options)


def collect(engine):
    seen = []
    engine.events.subscribe("*", lambda e: seen.append((e.event_type, e.source)))
    return seen


def test_engine_runs_a_camera_and_stops_cleanly(tmp_path, sample_video):
    engine = make_engine(tmp_path, sample_video)
    seen = collect(engine)

    engine.start()
    wanted = {"MOTION_DETECTED", "PERSON_DETECTED", "FACE_RECOGNIZED", "UNKNOWN_PERSON"}
    assert wait_for(lambda: wanted <= {t for t, _ in seen})

    status = engine.status
    assert status["running"] and status["cameras"][0]["state"] == "online"

    engine.stop()

    assert engine.running is False
    assert engine.status["thread_alive"] is False
    assert all(source == "Front door" for _, source in seen)


def test_repeated_detections_are_rate_limited(tmp_path, sample_video):
    engine = make_engine(tmp_path, sample_video)
    seen = collect(engine)

    engine.start()
    assert wait_for(lambda: any(t == "PERSON_DETECTED" for t, _ in seen))
    time.sleep(1.5)
    engine.stop()

    assert sum(t == "PERSON_DETECTED" for t, _ in seen) == 1
    assert sum(t == "UNKNOWN_PERSON" for t, _ in seen) == 1


def test_unknown_faces_are_sent_to_the_inbox(tmp_path, sample_video):
    faces = FakeFaces()
    engine = make_engine(tmp_path, sample_video, models_loader=lambda: faces)
    seen = collect(engine)

    engine.start()
    assert wait_for(lambda: any(t == "UNKNOWN_PERSON" for t, _ in seen))
    engine.stop()

    assert faces.unknown_calls == [1]   # recorded once, not on every frame


def test_a_snapshot_is_saved_for_alerts(tmp_path, sample_video):
    engine = make_engine(tmp_path, sample_video)
    seen = collect(engine)

    engine.start()
    assert wait_for(lambda: any(t == "PERSON_DETECTED" for t, _ in seen))
    time.sleep(0.5)
    engine.stop()

    files = list((tmp_path / "snaps" / "1").glob("*.jpg"))
    assert 1 <= len(files) <= 2


def test_events_are_saved_to_the_database(tmp_path, sample_video, temp_db):
    from src.database.repository import EventRepository

    engine = make_engine(tmp_path, sample_video, persist_events=True)
    seen = collect(engine)

    engine.start()
    assert wait_for(lambda: any(t == "UNKNOWN_PERSON" for t, _ in seen))
    engine.stop()  # flushes the save queue

    rows = EventRepository().get_all()
    assert len(rows) >= 3
    assert "PERSON_DETECTED" in {row[1] for row in rows}


def test_two_cameras_run_together(tmp_path, sample_video):
    cameras = [
        {"id": 1, "name": "Front", "kind": "file", "source": sample_video, "detection_fps": 20},
        {"id": 2, "name": "Back", "kind": "file", "source": sample_video, "detection_fps": 20},
    ]
    engine = make_engine(tmp_path, sample_video, cameras=cameras)
    seen = collect(engine)

    engine.start()
    assert wait_for(lambda: {"Front", "Back"} <= {source for _, source in seen})
    assert {c["name"] for c in engine.status["cameras"]} == {"Front", "Back"}
    assert engine.get_worker(1) is not None

    engine.stop()
    assert engine.status["cameras"] == []


def test_engine_with_no_cameras_explains_itself(tmp_path, sample_video):
    engine = make_engine(tmp_path, sample_video, cameras=[])

    engine.start()
    assert wait_for(lambda: engine.error is not None)
    assert engine.running is True
    assert "Add one" in engine.error

    engine.stop()
    assert engine.running is False


def test_model_loading_failure_stops_engine_with_message(tmp_path, sample_video):
    def broken():
        raise RuntimeError("model files missing")

    engine = make_engine(tmp_path, sample_video, models_loader=broken)

    engine.start()
    assert wait_for(lambda: not engine.running)
    assert engine.error
    assert "model files missing" not in engine.error  # no internals leaked to the UI


def test_missing_model_files_show_a_helpful_message(tmp_path, sample_video):
    def missing():
        raise ModelsMissingError("Face recognition models are missing. Run: python scripts/download_models.py")

    engine = make_engine(tmp_path, sample_video, models_loader=missing)

    engine.start()
    assert wait_for(lambda: not engine.running)
    assert "download_models" in engine.error


def test_status_shows_loading_while_models_load(tmp_path, sample_video):
    def slow():
        time.sleep(0.5)
        return FakeFaces()

    engine = make_engine(tmp_path, sample_video, models_loader=slow)

    engine.start()
    assert engine.status["loading"] is True
    assert wait_for(lambda: not engine.status["loading"])

    engine.stop()


def test_restart_works(tmp_path, sample_video):
    engine = make_engine(tmp_path, sample_video)

    engine.start()
    assert wait_for(lambda: engine.status["cameras"] != [])
    engine.restart()
    assert engine.running is True
    assert wait_for(lambda: engine.status["cameras"] != [])

    engine.stop()
    assert engine.running is False


def test_a_broken_alert_channel_does_not_stop_detection(tmp_path, sample_video):
    class BrokenNotifier:
        def notify(self, event):
            raise ConnectionError("no internet")

        notify_photo = notify

    engine = make_engine(tmp_path, sample_video, notifier_factory=lambda: BrokenNotifier())
    seen = collect(engine)

    engine.start()
    assert wait_for(lambda: any(t == "UNKNOWN_PERSON" for t, _ in seen))
    time.sleep(0.5)

    assert engine.status["cameras"][0]["state"] == "online"
    engine.stop()
