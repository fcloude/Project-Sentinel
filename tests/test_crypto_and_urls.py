import pytest
from cryptography.fernet import InvalidToken

from src.camera.url_utils import capture_source, mask_url, validate_source
from src.security.crypto import SecretBox, get_secret_key


def test_secretbox_round_trip():
    box = SecretBox("a-long-random-secret")
    token = box.encrypt("rtsp://admin:pw@10.0.0.5/stream")

    assert "admin" not in token
    assert box.decrypt(token) == "rtsp://admin:pw@10.0.0.5/stream"


def test_secretbox_wrong_key_cannot_decrypt():
    token = SecretBox("key-one").encrypt("hello")

    with pytest.raises(InvalidToken):
        SecretBox("key-two").decrypt(token)


def test_secret_key_is_created_once_and_reused(tmp_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    db = str(tmp_path / "data" / "x.db")

    first = get_secret_key(db)
    second = get_secret_key(db)

    assert first == second
    assert len(first) >= 40


def test_env_secret_key_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "from-env")
    assert get_secret_key(str(tmp_path / "x.db")) == "from-env"


def test_mask_url():
    assert mask_url("rtsp://admin:pw@192.168.1.5:554/s1") == "rtsp://admin:***@192.168.1.5:554/s1"
    assert mask_url("rtsp://192.168.1.5/s1") == "rtsp://192.168.1.5/s1"
    assert "secret" not in mask_url("http://cam/video?user=a&password=secret")


def test_validate_source():
    assert validate_source("usb", "0") == ("0", None)
    assert validate_source("usb", "abc")[1] is not None
    assert validate_source("url", "rtsp://10.0.0.5/s")[1] is None
    assert validate_source("url", "ftp://10.0.0.5/s")[1] is not None
    assert validate_source("url", "file:///etc/passwd")[1] is not None
    assert validate_source("url", "http://host:notaport/")[1] is not None
    assert validate_source("file", "/tmp/x.mp4", allow_file=False)[1] is not None


def test_capture_source_types():
    assert capture_source("usb", "1") == 1
    assert capture_source("url", "rtsp://x/y") == "rtsp://x/y"
