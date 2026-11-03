import dataclasses

import pytest

from src.database import manager
from src.events.event import Event
from src.events.event_bus import EventBus


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Points the app at a throwaway database instead of your real one."""
    test_settings = dataclasses.replace(
        manager.settings, database_path=str(tmp_path / "data" / "test.db")
    )
    monkeypatch.setattr(manager, "settings", test_settings)


def test_event_is_saved_and_read_back(temp_db):
    from src.database.repository import EventRepository
    from src.database.schema import initialize_database

    initialize_database()
    repo = EventRepository()

    repo.save(Event(event_type="MOTION_DETECTED", source="test", message="hi"))

    rows = repo.get_all()
    assert len(rows) == 1
    assert rows[0][1] == "MOTION_DETECTED"


def test_bus_saves_every_event(temp_db):
    from src.database.repository import EventRepository
    from src.database.schema import initialize_database

    initialize_database()
    repo = EventRepository()
    bus = EventBus()
    bus.subscribe("*", repo.save)

    bus.publish(Event(event_type="A", source="test", message="1"))
    bus.publish(Event(event_type="B", source="test", message="2"))

    assert len(repo.get_all()) == 2
