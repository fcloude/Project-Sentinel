import sys
sys.path.insert(0, 'C:/dev/Project-Sentinel')

import tempfile
from pathlib import Path
from src.security.config import SecurityConfig
from tests.test_security import base_env, token_from
from src.dashboard.app import create_app

tmp = Path(tempfile.mkdtemp())
cfg = SecurityConfig.from_env(base_env(tmp))

app = create_app(None, cfg)
app.testing = False

# Setup admin
c = app.test_client()
tok = token_from(c.get("/setup").data)
r = c.post("/setup", data={"csrf_token": tok, "username": "admin", "password": "correct horse battery", "confirm": "correct horse battery"})
print(f"Setup status: {r.status_code}")

# Login
c2 = app.test_client()
tok2 = token_from(c2.get("/login").data)
r2 = c2.post("/login", data={"csrf_token": tok2, "username": "admin", "password": "correct horse battery", "next": ""})
print(f"Login POST status: {r2.status_code}")
print(f"Set-Cookie header: {r2.headers.get('Set-Cookie', 'N/A')}")

# Check session
with c2.session_transaction() as sess:
    print(f"Session dict: {dict(sess)}")
    # Check cookie settings
    if 'sentinel_session' in c2.cookies:
        print(f"Test client cookie: {c2.cookies['sentinel_session']}")