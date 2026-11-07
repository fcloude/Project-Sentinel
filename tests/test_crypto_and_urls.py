import pytest

from src.camera.url_utils import capture_source, mask_url, validate_source
from src.security.crypto import SecretBox, SecretDecryptionError, get_encryption_keys


def test_secretbox_round_trip():
    box = SecretBox([SecretBox.generate_key()])
    token = box.encrypt("rtsp://admin:pw@10.0.0.5/stream")

    assert "admin" not in token
    assert box.decrypt(token) == "rtsp://admin:pw@10.0.0.5/stream"


def test_secretbox_wrong_key_cannot_decrypt():
    token = SecretBox([SecretBox.generate_key()]).encrypt("hello")

    with pytest.raises(SecretDecryptionError):
        SecretBox([SecretBox.generate_key()]).decrypt(token)


def test_encryption_keys_are_read_from_env(monkeypatch):
    first, second = SecretBox.generate_key(), SecretBox.generate_key()
    monkeypatch.setenv("SENTINEL_ENCRYPTION_KEYS", f" {first} , {second} ")

    assert get_encryption_keys() == (first, second)

    monkeypatch.delenv("SENTINEL_ENCRYPTION_KEYS")
    with pytest.raises(RuntimeError):
        get_encryption_keys()


def test_old_key_still_decrypts_after_rotation():
    old, new = SecretBox.generate_key(), SecretBox.generate_key()
    token = SecretBox([old]).encrypt("hello")

    assert SecretBox([new, old]).decrypt(token) == "hello"


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


def test_validate_source_uses_the_hardened_camera_validator():
    # These pass the plain URL parser but are SSRF/credential-exfiltration risks.
    for bad in (
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/",
        "http://0.0.0.0/",
        "http://2852039166/",
        "rtsp://h/x\nHOST: evil",
    ):
        assert validate_source("url", bad)[1] is not None, bad
    assert validate_source("url", "rtsp://192.168.1.20:554/stream1") == (
        "rtsp://192.168.1.20:554/stream1", None
    )


def test_capture_source_types():
    assert capture_source("usb", "1") == 1
    assert capture_source("url", "rtsp://x/y") == "rtsp://x/y"
