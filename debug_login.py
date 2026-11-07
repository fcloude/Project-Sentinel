import sys
sys.path.insert(0, 'C:/dev/Project-Sentinel')

import tempfile
from pathlib import Path
from src.security.config import SecurityConfig
from tests.test_security import base_env, token_from
from src.dashboard.app import create_app
from src.security.auth import _store, _ip, _throttle
from src.security import passwords
from unittest.mock import patch

tmp = Path(tempfile.mkdtemp())
cfg = SecurityConfig.from_env(base_env(tmp))

app = create_app(None, cfg)
app.testing = False

# Setup admin
c = app.test_client()
tok = token_from(c.get("/setup").data)
r = c.post("/setup", data={"csrf_token": tok, "username": "admin", "password": "correct horse battery", "confirm": "correct horse battery"})
print(f"Setup status: {r.status_code}")

# Now test login flow
c2 = app.test_client()
tok2 = token_from(c2.get("/login").data)
print(f"CSRF token: {tok2}")
print(f"GET /login status: OK")

# Post login
r2 = c2.post("/login", data={"csrf_token": tok2, "username": "admin", "password": "correct horse battery", "next": ""})
print(f"Login POST status: {r2.status_code}")
print(f"Login POST data: {r2.data[:200]}")

# Check if session exists
with c2.session_transaction() as sess:
    print(f"Session after login: {dict(sess)}")

# Try dashboard
r3 = c2.get("/")
print(f"Dashboard status: {r3.status_code}")
print(f"Dashboard location: {r3.headers.get('Location', 'N/A')}")