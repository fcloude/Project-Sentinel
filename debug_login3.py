import sys
sys.path.insert(0, 'C:/dev/Project-Sentinel')

import tempfile
from pathlib import Path
from src.security.config import SecurityConfig
from tests.test_security import base_env, token_from
from src.dashboard.app import create_app
import re

tmp = Path(tempfile.mkdtemp())
cfg = SecurityConfig.from_env(base_env(tmp))

app = create_app(None, cfg)
app.testing = False

# Setup admin
c = app.test_client()
tok = token_from(c.get("/setup").data)
r = c.post("/setup", data={"csrf_token": tok, "username": "admin", "password": "correct horse battery", "confirm": "correct horse battery"})
print(f"Setup status: {r.status_code}")

# Now test login flow with debug
c2 = app.test_client()

# First, GET /login to get CSRF token
print("\n--- GET /login ---")
r_get = c2.get("/login")
print(f"GET /login status: {r_get.status_code}")
print(f"GET /login Location: {r_get.headers.get('Location', 'N/A')}")

# Get CSRF token from the form
html = r_get.get_data(as_text=True)
tok_match = re.search(r'name=\"csrf-token\" content=\"([^\"]+)\"', html) or re.search(r'name=\"csrf_token\" value=\"([^\"]+)\"', html)
if tok_match:
    tok = tok_match.group(1)
    print(f"CSRF token: {tok}")
else:
    print("No CSRF token found!")

# Now POST /login
print("\n--- POST /login ---")
r_post = c2.post("/login", data={"csrf_token": tok, "username": "admin", "password": "correct horse battery", "next": ""})
print(f"POST /login status: {r_post.status_code}")
print(f"POST /login data: {r_post.data[:300]}")

# Check session
with c2.session_transaction() as sess:
    print(f"Session: {dict(sess)}")

# Try dashboard (without following redirect)
print("\n--- GET / (no follow) ---")
r_dash = c2.get("/", follow_redirects=False)
print(f"Dashboard status (no follow): {r_dash.status_code}")
print(f"Dashboard Location (no follow): {r_dash.headers.get('Location', 'N/A')}")

# Try dashboard (with follow)
print("\n--- GET / (with follow) ---")
r_dash2 = c2.get("/")
print(f"Dashboard status (follow): {r_dash2.status_code}")
print(f"Final URL: {r_dash2.url}")