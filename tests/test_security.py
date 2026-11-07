import logging
import pickle
import re
import secrets
import sqlite3
import sys
import tempfile
import time
import unittest
from importlib import util as importlib_util
from pathlib import Path
from unittest import mock

import numpy as np
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.security import passwords  # noqa: E402
from src.security.config import SecurityConfig, SecurityConfigError, is_loopback  # noqa: E402
from src.security.crypto import SecretBox, SecretDecryptionError  # noqa: E402
from src.security.ratelimit import LoginThrottle, SlidingWindowLimiter  # noqa: E402
from src.security.redaction import RedactingFormatter, redact  # noqa: E402
from src.security.validators import (  # noqa: E402
    ValidationError, is_safe_snapshot_name, safe_join, validate_camera_source,
    validate_image_upload, validate_person_name,
)

FAKE_TOKEN = "123456789:" + "A" * 35  # obviously fake


def base_env(tmp, **extra):
    env = {
        "SECRET_KEY": secrets.token_urlsafe(48),
        "SENTINEL_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
        "DATABASE_PATH": str(Path(tmp) / "db" / "sentinel.db"),
        "SNAPSHOT_DIR": str(Path(tmp) / "snaps"),
        # Google OAuth required for V1 public product - dummy values for testing
        "GOOGLE_OAUTH_CLIENT_ID": "test-google-client-id",
        "GOOGLE_OAUTH_CLIENT_SECRET": "test-google-client-secret",
        "GOOGLE_OAUTH_REDIRECT_URI": "http://localhost/auth/google-callback",
    }
    env.update(extra)
    return env


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_valid(self):
        cfg = SecurityConfig.from_env(base_env(self.tmp))
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertNotIn(cfg.secret_key, repr(cfg))

    def test_missing_or_weak_secret(self):
        for bad in ("", "short", "changeme" * 5, "a" * 40):
            with self.assertRaises(SecurityConfigError, msg=bad):
                SecurityConfig.from_env(base_env(self.tmp, SECRET_KEY=bad))

    def test_missing_or_bad_encryption_key(self):
        for bad in ("", "not-a-key"):
            with self.assertRaises(SecurityConfigError):
                SecurityConfig.from_env(base_env(self.tmp, SENTINEL_ENCRYPTION_KEYS=bad))

    def test_debug_refused(self):
        for name in ("DEBUG", "FLASK_DEBUG"):
            with self.assertRaises(SecurityConfigError):
                SecurityConfig.from_env(base_env(self.tmp, **{name: "True"}))

    def test_lan_requires_explicit_opt_in(self):
        with self.assertRaises(SecurityConfigError):
            SecurityConfig.from_env(base_env(self.tmp, HOST="0.0.0.0"))
        cfg = SecurityConfig.from_env(base_env(self.tmp, HOST="0.0.0.0", SENTINEL_ALLOW_LAN="true"))
        self.assertTrue(cfg.warnings)  # no HTTPS -> warns
        cfg = SecurityConfig.from_env(base_env(self.tmp, HOST="0.0.0.0", SENTINEL_ALLOW_LAN="true", SENTINEL_HTTPS="true"))
        self.assertFalse(cfg.warnings)

    def test_bad_port(self):
        for bad in ("0", "70000", "abc"):
            with self.assertRaises(SecurityConfigError):
                SecurityConfig.from_env(base_env(self.tmp, PORT=bad))

    def test_loopback(self):
        self.assertTrue(all(map(is_loopback, ["127.0.0.1", "::1", "localhost", "[::1]"])))
        self.assertFalse(any(map(is_loopback, ["0.0.0.0", "192.168.1.5", "example.com", ""])))


class PasswordTests(unittest.TestCase):
    def test_policy(self):
        for bad in ("short", "a" * 129, "password1", "aaaaaaaaaaaa"):
            with self.assertRaises(passwords.PasswordPolicyError, msg=bad):
                passwords.check_policy(bad)
        with self.assertRaises(passwords.PasswordPolicyError):
            passwords.check_policy("MyUserName1", username="myusername1")
        passwords.check_policy("correct horse battery")

    def test_hash_verify(self):
        h = passwords.hash_password("correct horse battery")
        self.assertNotIn("correct", h)
        self.assertTrue(passwords.verify_password(h, "correct horse battery"))
        self.assertFalse(passwords.verify_password(h, "correct horse batterY"))
        self.assertNotEqual(h, passwords.hash_password("correct horse battery"))  # salted

    def test_never_raises(self):
        self.assertFalse(passwords.verify_password("garbage", "x"))
        self.assertFalse(passwords.verify_password("$argon2id$broken", "x"))
        self.assertFalse(passwords.verify_password(None, "x"))
        self.assertFalse(passwords.verify_password(passwords.DUMMY_HASH, "x" * 5000))
        self.assertFalse(passwords.verify_password(passwords.DUMMY_HASH, "anything"))


class RateLimitTests(unittest.TestCase):
    def test_window(self):
        now = [0.0]
        lim = SlidingWindowLimiter(3, 10, clock=lambda: now[0])
        self.assertTrue(all(lim.hit("a") for _ in range(3)))
        self.assertFalse(lim.hit("a"))
        self.assertGreater(lim.retry_after("a"), 0)
        self.assertTrue(lim.hit("b"))
        now[0] = 11
        self.assertTrue(lim.hit("a"))

    def test_bounded_memory(self):
        lim = SlidingWindowLimiter(1, 100, max_keys=50)
        for i in range(500):
            lim.record(f"k{i}")
        self.assertLessEqual(len(lim._events), 50)

    def test_login_throttle_isolated_per_username(self):
        t = LoginThrottle(max_failures=3)
        for _ in range(3):
            t.failure("1.1.1.1", "admin")
        self.assertTrue(t.blocked("1.1.1.1", "admin"))
        self.assertFalse(t.blocked("2.2.2.2", "admin"))   # attacker elsewhere can't lock the real admin out
        t.success("1.1.1.1", "admin")
        self.assertFalse(t.blocked("1.1.1.1", "admin"))


class RedactionTests(unittest.TestCase):
    def test_patterns(self):
        cases = [
            f"POST https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage failed",
            "opening rtsp://admin:S3cr3t!pw@192.168.1.20:554/stream1",
            "rtsp://user:p@ss@host/x",
            "Authorization: Bearer abcDEF123.xyz",
            "TELEGRAM_BOT_TOKEN=abcdef123456 password: hunter22",
        ]
        for text in cases:
            out = redact(text)
            for leaked in (FAKE_TOKEN, "S3cr3t", "p@ss", "ss@host", "abcDEF123", "abcdef123456", "hunter22", FAKE_TOKEN.split(":")[1]):
                self.assertNotIn(leaked, out, (text, out))

    def test_keeps_normal_text(self):
        self.assertEqual(redact("camera 1 connected at 25 fps"), "camera 1 connected at 25 fps")

    def test_formatter_redacts_tracebacks(self):
        logger = logging.getLogger("t.redact")
        logger.propagate = False
        records = []
        h = logging.Handler()
        h.emit = lambda r: records.append(h.format(r))
        h.setFormatter(RedactingFormatter("%(message)s"))
        logger.addHandler(h)
        try:
            raise RuntimeError(f"https://api.telegram.org/bot{FAKE_TOKEN}/x")
        except RuntimeError:
            logger.exception("boom")
        self.assertNotIn(FAKE_TOKEN.split(":")[1], records[0])


class ValidatorTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(validate_person_name("  Aryan K. "), "Aryan K.")
        self.assertEqual(validate_person_name("José O'Neil-Smith"), "José O'Neil-Smith")
        for bad in ("", " ", "<script>alert(1)</script>", "a" * 65, "x\ny", "../etc", "_hidden", "name;DROP"):
            with self.assertRaises(ValidationError, msg=bad):
                validate_person_name(bad)

    def test_camera_sources(self):
        self.assertEqual(validate_camera_source("0"), 0)
        self.assertEqual(validate_camera_source(" 3 "), 3)
        ok = ["rtsp://admin:pw@192.168.1.20:554/stream1", "http://10.0.0.5/video", "https://cam.example.com/x",
              "rtsps://cam.local/s", "rtsp://127.0.0.1:8554/test"]
        for u in ok:
            self.assertEqual(validate_camera_source(u), u)
        bad = ["file:///etc/passwd", "javascript:alert(1)", "ftp://x/y", "rtsp://", "", "100",
               "http://169.254.169.254/latest/meta-data", "http://[::ffff:169.254.169.254]/",
               "http://2852039166/", "http://0xA9FEA9FE/", "http://0251.0376.0251.0376/",
               "http://metadata.google.internal/", "http://0.0.0.0/", "rtsp://host:99999/x",
               "rtsp://h/x y", "rtsp://h/x\nHOST: evil", "http://224.0.0.1/", "x" * 3000, "$(reboot)", "-i /dev/video0"]
        for u in bad:
            with self.assertRaises(ValidationError, msg=u):
                validate_camera_source(u)

    def test_images(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (640).to_bytes(4, "big") + (480).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
        self.assertEqual(validate_image_upload(png, max_bytes=10_000), "png")
        jpg = b"\xff\xd8\xff\xe0\x00\x04\x00\x00" + b"\xff\xc0\x00\x11\x08" + (480).to_bytes(2, "big") + (640).to_bytes(2, "big") + b"\x03" + b"\x00" * 9
        self.assertEqual(validate_image_upload(jpg, max_bytes=10_000), "jpeg")
        huge = png[:16] + (60000).to_bytes(4, "big") + (60000).to_bytes(4, "big") + png[24:]
        for bad, kw in [(b"", {}), (b"GIF89a....", {}), (b"<?php system($_GET[0]); ?>", {}), (huge, {}),
                        (png, {"max_bytes": 5}), (b"\xff\xd8\xff\xe0\x00\x04\x00\x00", {})]:
            with self.assertRaises(ValidationError):
                validate_image_upload(bad, **({"max_bytes": 10_000} | kw))

    def test_paths(self):
        for good in ("20260101_120000.jpg", "a-b_c.jpg"):
            self.assertTrue(is_safe_snapshot_name(good))
        for bad in ("../x.jpg", "a/b.jpg", "a\\b.jpg", ".env", "x.jpg.exe", "a..b/../c.jpg", "", ".hidden.jpg", "x.png"):
            self.assertFalse(is_safe_snapshot_name(bad), bad)
        base = tempfile.mkdtemp()
        self.assertIsNotNone(safe_join(base, "ok.jpg"))
        self.assertIsNone(safe_join(base, "../outside.jpg"))
        self.assertIsNone(safe_join(base, "/etc/passwd"))


class CryptoTests(unittest.TestCase):
    def test_roundtrip_tamper_rotation(self):
        k1, k2 = SecretBox.generate_key(), SecretBox.generate_key()
        old = SecretBox([k1]).encrypt("rtsp://u:p@h/x")
        self.assertNotIn("rtsp", old)
        self.assertEqual(SecretBox([k1]).decrypt(old), "rtsp://u:p@h/x")
        with self.assertRaises(SecretDecryptionError):
            SecretBox([k2]).decrypt(old)
        with self.assertRaises(SecretDecryptionError):
            SecretBox([k1]).decrypt(old[:-4] + "AAAA")
        rotated = SecretBox([k2, k1])
        self.assertEqual(rotated.decrypt(old), "rtsp://u:p@h/x")
        new = rotated.rotate(old)
        self.assertEqual(SecretBox([k2]).decrypt(new), "rtsp://u:p@h/x")


class FaceDatabaseTests(unittest.TestCase):
    def test_no_pickle_and_legacy_rows_skipped(self):
        from src.face.database import FaceDatabase
        path = str(Path(tempfile.mkdtemp()) / "f.db")
        db = FaceDatabase(path)
        vec = np.random.rand(512).astype("float32")
        db.add_face("Aryan", vec)
        np.testing.assert_array_equal(db.get_face("Aryan"), vec)
        # simulate a legacy pickled row (and a malicious one)
        conn = sqlite3.connect(path)
        conn.execute("INSERT INTO known_faces VALUES (?, ?)", ("Legacy", pickle.dumps(vec)))
        conn.execute("INSERT INTO known_faces VALUES (?, ?)", ("Evil", b"cos\nsystem\n(S'echo pwned'\ntR."))
        conn.commit(); conn.close()
        names = [n for n, _ in db.get_all_faces()]
        self.assertEqual(names, ["Aryan"])
        self.assertIsNone(db.get_face("Legacy"))
        with self.assertRaises(ValueError):
            db.add_face("Bad", np.zeros(10))
        with self.assertRaises(ValueError):
            db.add_face("Nan", np.full(512, np.nan))
        with self.assertRaises(ValidationError):
            db.add_face("<b>x</b>", vec)


class EventBusAndNotifierTests(unittest.TestCase):
    def test_failing_subscriber_is_isolated(self):
        from src.events.event import Event
        from src.events.event_bus import EventBus
        bus, seen = EventBus(), []
        def boom(e): raise RuntimeError("network down")
        bus.subscribe("X", boom)
        bus.subscribe("X", seen.append)
        bus.subscribe("*", seen.append)
        with self.assertLogs("src.events.event_bus", level="ERROR"):
            bus.publish(Event("X", "t", "m"))
        self.assertEqual(len(seen), 2)

    def test_telegram_client_never_logs_token(self):
        import requests
        from src.notifications.client import TelegramClient
        client = TelegramClient(token=FAKE_TOKEN, chat_id=42)
        err = requests.ConnectionError(f"HTTPSConnectionPool: https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage")
        with mock.patch("requests.post", side_effect=err), self.assertLogs("src.notifications.client", level="WARNING") as cm:
            self.assertFalse(client.send_message("hi"))
        self.assertNotIn(FAKE_TOKEN.split(":")[1], "\n".join(cm.output))
        self.assertNotIn(FAKE_TOKEN.split(":")[1], repr(client))

    def test_disabled_client_is_noop(self):
        from src.notifications.client import TelegramClient
        with mock.patch("requests.post") as post:
            self.assertFalse(TelegramClient(token="", chat_id=0).send_message("x"))
            post.assert_not_called()

    def test_alerts_never_block_detection_and_delivery_is_bounded(self):
        """ADR-005 replaced the Telegram-only notifier with rules + an outbox.

        The guarantees are unchanged: turning an event into alerts never touches the
        network, and each worker pass handles a bounded number of deliveries.
        """
        from src.events.event import Event
        from src.notifications.dispatcher import NotificationDispatcher
        from src.notifications.models import Notification
        from src.notifications.worker import OutboxWorker

        class QueuedRepo:
            def __init__(self):
                self.queued = []

            def enabled_rules(self):
                return [{"id": 1, "trigger": "motion", "camera_id": None,
                         "channel_ids": [1], "start_time": None, "end_time": None,
                         "cooldown_s": 60, "attach_snapshot": False, "enabled": True}]

            def enqueue(self, rule_id, channel_id, notification: Notification, now=None):
                self.queued.append(notification.title)
                return len(self.queued)

        queued = QueuedRepo()
        dispatcher = NotificationDispatcher(lambda: queued)

        t0 = time.monotonic()
        for i in range(20):  # distinct cameras, so the per-camera cooldown doesn't apply
            dispatcher.handle(Event("MOTION_DETECTED", "s", f"m{i}", metadata={"camera_id": i}))
        self.assertLess(time.monotonic() - t0, 1.0)  # no network on the detection path
        self.assertEqual(len(queued.queued), 20)     # every event queued, none dropped

        class WorkerRepo:
            def __init__(self):
                self.sent = []

            def due(self, now_iso, limit=20):
                return [{"id": i, "rule_id": None, "channel_id": 1, "attempts": 0,
                         "notification": Notification("t", "b")} for i in range(200)][:limit]

            def mark_sent(self, outbox_id, now_iso):
                self.sent.append(outbox_id)

            def purge_outbox(self, before_iso):
                pass

            def purge_inbox(self, before_iso):
                return []

        worker_repo = WorkerRepo()

        class Channel:
            def send(self, notification):
                pass

        worker = OutboxWorker(lambda: worker_repo, lambda channel_id: Channel())
        self.assertEqual(worker.run_once(), 20)        # bounded: due(limit=20) per pass
        self.assertEqual(len(worker_repo.sent), 20)


class FakeEngine:
    def __init__(self):
        self.running = False
    def start(self): self.running = True
    def stop(self): self.running = False
    def restart(self): self.stop(); self.start()
    @property
    def status(self): return {"running": self.running, "thread_alive": self.running}


def token_from(html: bytes) -> str:
    return re.search(rb'name="csrf_token" value="([^"]+)"', html).group(1).decode()


class AppTests(unittest.TestCase):
    PW = "correct horse battery"

    def make(self, **extra):
        from src.dashboard.app import create_app
        self.tmp = tempfile.mkdtemp()
        self.cfg = SecurityConfig.from_env(base_env(self.tmp, **extra))
        self.engine = FakeEngine()
        self.app = create_app(self.engine, self.cfg)
        self.app.testing = False
        return self.app

    def setup_admin(self, app):
        c = app.test_client()
        tok = token_from(c.get("/setup").data)
        r = c.post("/setup", data={"csrf_token": tok, "username": "admin", "password": self.PW, "confirm": self.PW})
        self.assertEqual(r.status_code, 302)

    def login(self, app, user="admin", pw=None, nxt="", client=None):
        c = client or app.test_client()
        tok = token_from(c.get("/login").data)
        r = c.post("/login", data={"csrf_token": tok, "username": user, "password": pw or self.PW, "next": nxt})
        return c, r

    def page_token(self, c):
        return token_from(c.get("/").data)

    # ---------------------------------------------------------------- first run & auth
    def test_fresh_install_redirects_to_setup_and_setup_is_one_shot(self):
        app = self.make()
        c = app.test_client()
        self.assertTrue(c.get("/").headers["Location"].endswith("/setup"))
        self.assertEqual(c.post("/setup", data={"username": "admin", "password": self.PW, "confirm": self.PW}).status_code, 403)  # no CSRF
        tok = token_from(c.get("/setup").data)
        weak = c.post("/setup", data={"csrf_token": tok, "username": "admin", "password": "short", "confirm": "short"})
        self.assertEqual(weak.status_code, 400)
        self.setup_admin(app)
        self.assertEqual(app.test_client().get("/setup").status_code, 404)
        r = app.test_client().post("/setup", data={"username": "evil", "password": self.PW, "confirm": self.PW})
        self.assertIn(r.status_code, (403, 404))
        self.assertEqual(len(app.extensions["sentinel_store"].list_users()), 1)

    def test_setup_refused_from_network_without_token(self):
        app = self.make()
        r = app.test_client().get("/setup", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
        self.assertEqual(r.status_code, 403)

    def test_setup_token_required_when_configured(self):
        app = self.make(SENTINEL_SETUP_TOKEN="tok-" + secrets.token_urlsafe(16))
        c = app.test_client()
        tok = token_from(c.get("/setup").data)
        r = c.post("/setup", data={"csrf_token": tok, "username": "admin", "password": self.PW, "confirm": self.PW, "setup_token": "wrong"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(app.extensions["sentinel_store"].count_users(), 0)

    def test_login_flow_cookie_flags_and_generic_errors(self):
        app = self.make(); self.setup_admin(app)
        c, bad = self.login(app, "admin", "wrong-password-1")
        c2, nouser = self.login(app, "nobody", "wrong-password-1")
        self.assertEqual((bad.status_code, nouser.status_code), (401, 401))
        self.assertEqual(bad.data.count(b"Invalid username or password."), 1)
        self.assertEqual(re.sub(rb'value="[^"]*"', b"", bad.data), re.sub(rb'value="[^"]*"', b"", nouser.data))  # no enumeration
        c3, ok = self.login(app)
        self.assertEqual(ok.status_code, 302)
        cookie = ok.headers.get("Set-Cookie")
        self.assertIn("HttpOnly", cookie); self.assertIn("SameSite=Lax", cookie)
        self.assertEqual(c3.get("/").status_code, 200)

    def test_https_mode_marks_cookie_secure_and_hsts(self):
        app = self.make(SENTINEL_HTTPS="true"); self.setup_admin(app)
        c, ok = self.login(app)
        cookie = ok.headers.get("Set-Cookie")
        self.assertIn("Secure", cookie); self.assertTrue(cookie.startswith("__Host-sentinel_session="))
        self.assertIn("Strict-Transport-Security", ok.headers)

    def test_bruteforce_lockout_blocks_even_correct_password(self):
        app = self.make(); self.setup_admin(app)
        codes = [self.login(app, "admin", "wrong-password-%d" % i)[1].status_code for i in range(6)]
        self.assertEqual(codes, [401] * 5 + [429])
        c, r = self.login(app)
        self.assertEqual(r.status_code, 429); self.assertIn("Retry-After", r.headers)

    def test_default_deny(self):
        app = self.make(); self.setup_admin(app)
        c = app.test_client()
        for path in ("/", "/cameras", "/faces", "/events", "/settings", "/snapshots/a.jpg"):
            r = c.get(path)
            self.assertEqual(r.status_code, 302, path); self.assertIn("/login", r.headers["Location"])
        r = c.get("/api/status"); self.assertEqual(r.status_code, 401); self.assertEqual(r.get_json(), {"error": "authentication required"})
        for path in ("/start", "/stop", "/restart"):
            self.assertIn(c.post(path).status_code, (401, 403, 302))
            self.assertFalse(self.engine.running)
        self.assertEqual(c.get("/healthz").get_json(), {"status": "ok"})
        self.assertEqual(c.get("/static/css/style.css").status_code, 404 if not Path(app.static_folder, "css/style.css").exists() else 200)

    def test_every_registered_route_is_covered(self):
        """Fails if someone adds a route that is publicly reachable by accident."""
        from src.security.auth import PUBLIC_ENDPOINTS
        app = self.make(); self.setup_admin(app)
        c = app.test_client()
        for rule in app.url_map.iter_rules():
            if rule.endpoint in PUBLIC_ENDPOINTS or rule.arguments:
                continue
            for m in rule.methods - {"HEAD", "OPTIONS"}:
                r = c.open(rule.rule, method=m)
                self.assertIn(r.status_code, (301, 302, 401, 403), (rule.rule, m, r.status_code))

    def test_open_redirect_blocked(self):
        app = self.make(); self.setup_admin(app)
        for evil in ("//evil.com", "https://evil.com", "/\\evil.com", "javascript:alert(1)", "/%0d%0aX: y"):
            c, r = self.login(app, nxt=evil)
            self.assertEqual(r.status_code, 302)
            loc = r.headers["Location"]
            self.assertTrue(loc == "/" or (loc.startswith("/") and not loc.startswith("//")), (evil, loc))
        c, r = self.login(app, nxt="/events")
        self.assertEqual(r.headers["Location"], "/events")

    # ---------------------------------------------------------------- CSRF / CORS / headers
    def test_csrf_required_and_origin_checked(self):
        app = self.make(); self.setup_admin(app)
        c, _ = self.login(app)
        self.assertEqual(c.post("/start").status_code, 403)
        self.assertEqual(c.post("/start", data={"csrf_token": "x" * 43}).status_code, 403)
        tok = self.page_token(c)
        self.assertEqual(c.post("/start", data={"csrf_token": tok}, headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(c.post("/start", data={"csrf_token": tok}, headers={"Origin": "null"}).status_code, 403)
        self.assertFalse(self.engine.running)
        self.assertEqual(c.post("/start", data={"csrf_token": tok}, headers={"Origin": "http://localhost"}).status_code, 302)
        self.assertTrue(self.engine.running)
        self.assertEqual(c.post("/stop", headers={"X-CSRF-Token": tok}).status_code, 302)  # header variant for fetch()
        self.assertFalse(self.engine.running)

    def test_csrf_rejection_is_classified_logged_and_audited(self):
        app = self.make(); self.setup_admin(app)
        c = app.test_client()
        tok = token_from(c.get("/login").data)
        with self.assertLogs("src.dashboard.app", level="WARNING"):
            r = c.post("/login", data={"csrf_token": tok, "username": "admin", "password": self.PW},
                       headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.assertIn(b"different site", r.data)
        self.assertEqual(c.get("/").status_code, 302)  # nothing was authenticated
        rows = app.extensions["sentinel_store"].recent_audit()
        self.assertIn("csrf_denied", {row["action"] for row in rows})
        self.assertTrue(any("bad_origin" in (row["detail"] or "") for row in rows))
        self.assertNotIn(self.PW, " ".join(str(tuple(row)) for row in rows))

    def test_login_without_session_cookie_explains_reason_and_allows_retry(self):
        """The reported `POST /login 403`: the token is fine, the session cookie never arrived."""
        app = self.make(); self.setup_admin(app)
        c = app.test_client()
        r = c.post("/login", data={"username": "admin", "password": self.PW})
        self.assertEqual(r.status_code, 403)
        self.assertIn(b"session cookie", r.data)
        # The error page is the login form again, with a fresh, usable token.
        retry = token_from(r.data)
        r2 = c.post("/login", data={"csrf_token": retry, "username": "admin", "password": self.PW})
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(c.get("/").status_code, 200)

    def test_stale_form_token_after_login_is_explained(self):
        app = self.make(); self.setup_admin(app)
        c = app.test_client()
        tok = token_from(c.get("/login").data)
        self.assertEqual(c.post("/login", data={"csrf_token": tok, "username": "admin",
                                                 "password": self.PW}).status_code, 302)
        # The token was rotated on login; the old tab's form must not silently 403.
        r = c.post("/logout", data={"csrf_token": tok})
        self.assertEqual(r.status_code, 403)
        self.assertIn(b"out of date", r.data)
        self.assertEqual(c.get("/").status_code, 200)  # still signed in

    def test_no_cors_headers_ever(self):
        app = self.make(); self.setup_admin(app)
        c, _ = self.login(app)
        for r in (c.get("/api/status", headers={"Origin": "https://evil.example"}),
                  c.options("/api/status", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}),
                  c.get("/login", headers={"Origin": "https://evil.example"})):
            self.assertFalse([h for h in r.headers.keys() if h.lower().startswith("access-control-")])

    def test_security_headers(self):
        app = self.make(); self.setup_admin(app)
        c, _ = self.login(app)
        h = c.get("/").headers
        for name in ("Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy",
                     "Permissions-Policy", "Cross-Origin-Opener-Policy", "Cross-Origin-Resource-Policy"):
            self.assertIn(name, h)
        self.assertEqual(h["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", h["Content-Security-Policy"]); self.assertNotIn("unsafe-eval", h["Content-Security-Policy"])
        self.assertEqual(h["Server"], "Sentinel")
        self.assertNotIn("Strict-Transport-Security", h)  # only over HTTPS

    def test_pages_have_no_inline_script_or_style(self):
        app = self.make(); self.setup_admin(app)
        c, _ = self.login(app)
        for path in ("/", "/login", "/account/password"):
            html = c.get(path, follow_redirects=True).data.decode()
            self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)", path)
            self.assertNotRegex(html, r"\bstyle=", path)
            self.assertNotRegex(html, r"\bon\w+=", path)

    # ---------------------------------------------------------------- roles & sessions
    def test_viewer_is_read_only(self):
        app = self.make(); self.setup_admin(app)
        store = app.extensions["sentinel_store"]
        store.create_user("viewer1", passwords.hash_password(self.PW), "viewer")
        c, r = self.login(app, "viewer1")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get("/").status_code, 200)
        self.assertNotIn(b"Start Sentinel", c.get("/").data)
        tok = self.page_token(c)
        for path in ("/start", "/stop", "/restart"):
            self.assertEqual(c.post(path, data={"csrf_token": tok}).status_code, 403)
        self.assertFalse(self.engine.running)
        self.assertEqual(c.post("/logout", data={"csrf_token": tok}).status_code, 302)  # self-service still allowed
        self.assertEqual(c.get("/").status_code, 302)

    def test_password_change_signs_out_other_sessions(self):
        app = self.make(); self.setup_admin(app)
        a, _ = self.login(app); b, _ = self.login(app)
        self.assertEqual(b.get("/").status_code, 200)
        tok = self.page_token(a)
        new = "another long passphrase"
        r = a.post("/account/password", data={"csrf_token": tok, "current_password": "nope-nope-nope", "new_password": new, "confirm": new})
        self.assertEqual(r.status_code, 400)
        r = a.post("/account/password", data={"csrf_token": tok, "current_password": self.PW, "new_password": new, "confirm": new})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(a.get("/").status_code, 200)       # current session survives
        self.assertEqual(b.get("/").status_code, 302)       # other session is dead
        self.assertEqual(self.login(app, pw=self.PW)[1].status_code, 401)
        self.assertEqual(self.login(app, pw=new)[1].status_code, 302)

    def test_disabled_user_loses_access_immediately(self):
        app = self.make(); self.setup_admin(app)
        store = app.extensions["sentinel_store"]
        store.create_user("viewer1", passwords.hash_password(self.PW), "viewer")
        c, _ = self.login(app, "viewer1")
        self.assertEqual(c.get("/").status_code, 200)
        store.set_active(store.get_user_by_name("viewer1").id, False)
        self.assertEqual(c.get("/").status_code, 302)
        self.assertEqual(self.login(app, "viewer1")[1].status_code, 401)

    def test_idle_and_absolute_timeouts(self):
        app = self.make(); self.setup_admin(app)
        c, _ = self.login(app)
        now = time.time()
        with mock.patch("src.security.auth.time.time", return_value=now + self.cfg.session_idle_seconds + 5):
            self.assertEqual(c.get("/").status_code, 302)
        c, _ = self.login(app)
        for step in range(1, 40):  # stay active, but the absolute limit must still end the session
            with mock.patch("src.security.auth.time.time", return_value=now + step * 1200):
                code = c.get("/").status_code
            if now + step * 1200 - now > self.cfg.session_absolute_seconds:
                self.assertEqual(code, 302); break

    def test_tampered_session_cookie_rejected(self):
        app = self.make(); self.setup_admin(app)
        c, _ = self.login(app)
        cookie = c.get_cookie("sentinel_session")
        c.set_cookie("sentinel_session", cookie.value[:-3] + ("AAA" if not cookie.value.endswith("AAA") else "BBB"))
        self.assertEqual(c.get("/").status_code, 302)

    def test_audit_log_has_no_secrets(self):
        app = self.make(); self.setup_admin(app)
        self.login(app, "admin", "wrong-password-xyz"); self.login(app)
        rows = app.extensions["sentinel_store"].recent_audit()
        actions = {r["action"] for r in rows}
        self.assertTrue({"setup_admin_created", "login_failed", "login_ok"} <= actions)
        dump = " ".join(str(tuple(r)) for r in rows)
        self.assertNotIn("wrong-password-xyz", dump); self.assertNotIn(self.PW, dump)

    # ---------------------------------------------------------------- files, errors, limits
    def test_snapshot_route(self):
        app = self.make(); self.setup_admin(app)
        snaps = Path(self.cfg.snapshot_dir); snaps.mkdir(parents=True)
        (snaps / "ok.jpg").write_bytes(b"\xff\xd8\xff data")
        (Path(self.tmp) / "secret.jpg").write_bytes(b"outside")
        (snaps / ".env").write_text("SECRET=1")
        c, _ = self.login(app)
        r = c.get("/snapshots/ok.jpg"); self.assertEqual(r.status_code, 200); self.assertEqual(r.mimetype, "image/jpeg")
        for evil in ("..%2Fsecret.jpg", "..%2F..%2Fetc%2Fpasswd", ".env", "ok.jpg%00.png", "%2e%2e/secret.jpg", "nope.jpg"):
            self.assertEqual(c.get("/snapshots/" + evil).status_code, 404, evil)

    def test_errors_do_not_leak_internals(self):
        app = self.make(); self.setup_admin(app)
        c, _ = self.login(app)
        def boom(): raise RuntimeError("secret-internal-detail /home/user/app.py")
        self.engine.start = boom
        tok = self.page_token(c)
        r = c.post("/start", data={"csrf_token": tok})
        self.assertEqual(r.status_code, 500)
        self.assertNotIn(b"secret-internal-detail", r.data); self.assertNotIn(b"Traceback", r.data)
        r = c.get("/api/nope"); self.assertEqual(r.status_code, 404); self.assertEqual(r.get_json(), {"error": "Not found"})
        self.assertFalse(app.debug)

    def test_request_size_limit(self):
        app = self.make(MAX_UPLOAD_MB="1")
        c = app.test_client()
        r = c.post("/login", data=b"a=" + b"x" * (2 * 1024 * 1024), content_type="application/x-www-form-urlencoded")
        self.assertEqual(r.status_code, 413)

    def test_xss_in_displayed_values_is_escaped(self):
        app = self.make(); self.setup_admin(app)
        from src.dashboard import routes
        routes.service.state.last_event = '<script>alert(1)</script>'
        c, _ = self.login(app)
        html = c.get("/").data
        self.assertNotIn(b"<script>alert(1)</script>", html); self.assertIn(b"&lt;script&gt;", html)
        routes.service.state.last_event = "System Ready"


class ScannerTests(unittest.TestCase):
    def test_scanner_finds_known_problems_and_masks_secrets(self):
        spec = importlib_util.spec_from_file_location("security_scan", ROOT / "tools" / "security_scan.py")
        mod = importlib_util.module_from_spec(spec); spec.loader.exec_module(mod)
        d = Path(tempfile.mkdtemp())
        (d / "bad.py").write_text(
            f'BOT_TOKEN = "{FAKE_TOKEN}"\n'
            'app.run(host="0.0.0.0", debug=True)\n'
            'import pickle\nx = pickle.loads(blob)\n'
            'conn.execute(f"SELECT * FROM t WHERE n={n}")\n'
            'url = "rtsp://admin:hunter2pass@10.0.0.5/s"\n'
            'return render_template_string(x)\n')
        (d / "bad.html").write_text("<script>alert(1)</script>{{ x|safe }}")
        (d / "good.py").write_text('import os\nTOKEN = os.getenv("TOKEN")\nconn.execute("SELECT 1 WHERE a=?", (a,))\n'
                                   'url = "rtsp://USER:PASS@192.168.1.20/stream"\nx = 1  # sentinel-ok\n')
        found = {(f.name, rid) for f in d.iterdir() for rid, *_ in mod.scan_file(f)}
        for expected in [("bad.py", r) for r in ("SEC001", "SEC004", "SEC005", "SEC010", "SEC011", "SEC012", "SEC017", "SEC020")] + [("bad.html", "SEC020"), ("bad.html", "SEC022")]:
            self.assertIn(expected, found)
        self.assertFalse([x for x in found if x[0] == "good.py"], found)
        for f in d.iterdir():
            for *_, excerpt in mod.scan_file(f):
                self.assertNotIn("A" * 35, excerpt); self.assertNotIn("hunter2pass", excerpt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
