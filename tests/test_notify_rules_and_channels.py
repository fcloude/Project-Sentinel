from datetime import time as clock

import pytest

from src.notifications.channels import summarize, validate_channel
from src.notifications.rules import in_window, validate_rule


class Form(dict):
    def getlist(self, key):
        value = self.get(key, [])
        return value if isinstance(value, list) else [value]


def test_quiet_window_that_crosses_midnight():
    assert in_window("22:00", "06:00", clock(23, 30))
    assert in_window("22:00", "06:00", clock(3, 0))
    assert not in_window("22:00", "06:00", clock(12, 0))


def test_normal_window_and_always_on():
    assert in_window("09:00", "17:00", clock(10, 0))
    assert not in_window("09:00", "17:00", clock(18, 0))
    assert in_window(None, None, clock(3, 0))


def test_rule_validation_catches_bad_input():
    base = Form(name="Night", trigger="unknown_person", channel_ids=["1"], cooldown_s="60")

    rule, error = validate_rule(base, camera_ids={1}, channel_ids={1})
    assert error is None and rule["channel_ids"] == [1]

    assert validate_rule(Form(base, name=""), {1}, {1})[1]
    assert validate_rule(Form(base, trigger="nonsense"), {1}, {1})[1]
    assert validate_rule(Form(base, camera_id="9"), {1}, {1})[1]          # camera doesn't exist
    assert validate_rule(Form(base, channel_ids=["7"]), {1}, {1})[1]      # channel doesn't exist
    assert validate_rule(Form(base, cooldown_s="1"), {1}, {1})[1]         # too short
    assert validate_rule(Form(base, start_time="22:00"), {1}, {1})[1]     # only one time given
    assert validate_rule(Form(base, start_time="25:00", end_time="06:00"), {1}, {1})[1]


def test_rule_needs_at_least_one_channel():
    form = Form(name="x", trigger="motion", channel_ids=[], cooldown_s="60")
    assert validate_rule(form, {1}, {1})[1] is not None


@pytest.mark.parametrize("type_,form", [
    ("telegram", {"bot_token": "not-a-token", "chat_id": "123456"}),
    ("telegram", {"bot_token": "123456789:AAHZBnhzv-wOFOLuE0JLBK1p8ClE6yWV7bQ", "chat_id": "abc!"}),
    ("email", {"host": "smtp.example.com", "port": "abc", "from_addr": "a@b.com", "to_addrs": "c@d.com"}),
    ("email", {"host": "smtp.example.com", "port": "587", "from_addr": "not-an-email", "to_addrs": "c@d.com"}),
    ("email", {"host": "smtp.example.com", "port": "587", "from_addr": "a@b.com", "to_addrs": "c@d.com", "username": "me"}),
    ("webhook", {"url": "ftp://example.com/hook"}),
    ("webhook", {"url": "not a url"}),
])
def test_bad_channel_settings_are_rejected(type_, form):
    config, error = validate_channel(type_, form)
    assert config is None and error


def test_valid_channel_settings_pass():
    config, error = validate_channel("webhook", {"url": "https://ha.local/api/webhook/x", "secret": "s"})
    assert error is None and config["url"].startswith("https://")

    config, error = validate_channel("email", {
        "host": "smtp.example.com", "port": "587", "security": "starttls",
        "from_addr": "sentinel@example.com", "to_addrs": "me@example.com, wife@example.com",
    })
    assert error is None and config["to_addrs"] == ["me@example.com", "wife@example.com"]


def test_summaries_never_show_secrets():
    text = summarize("webhook", {"url": "https://u:password123@ha.local/api/x", "secret": "hunter2"})
    assert "password123" not in text and "hunter2" not in text
    assert "(signed)" in text

    text = summarize("telegram", {"bot_token": "123456789:SECRETTOKENSECRETTOKEN", "chat_id": "42"})
    assert "SECRET" not in text and "42" in text
