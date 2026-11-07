import sys
sys.path.insert(0, 'C:/dev/Project-Sentinel')

import tempfile
from pathlib import Path
from src.security.config import SecurityConfig
from tests.test_security import base_env, token_from
from src.dashboard.app import create_app
from src.security.store import SecurityStore
from src.security import passwords

tmp = Path(tempfile.mkdtemp())
cfg = SecurityConfig.from_env(base_env(tmp))

app = create_app(None, cfg)
app.testing = False

# Setup admin
c = app.test_client()
tok = token_from(c.get("/setup").data)
r = c.post("/setup", data={"csrf_token": tok, "username": "admin", "password": "correct horse battery", "confirm": "correct horse battery"})
print(f"Setup status: {r.status_code}")

# Check users
store = app.extensions['sentinel_store']
print(f"User count: {store.count_users()}")
users = store.list_users()
print(f"Users: {users}")

# Check specific user
admin_user = store.get_user_by_name("admin")
print(f"Admin user: {admin_user}")
if admin_user:
    print(f"  active: {admin_user.active}")
    print(f"  password_hash: {admin_user.password_hash[:20]}...")
    print(f"  provider: {admin_user.provider}")
    print(f"  email: {admin_user.email}")

# Now test the login logic manually
identifier = "admin"
password = "correct horse battery"

# Simulate the login function's logic
user = store.find_by_external_id("google", identifier) or store.find_by_email(identifier)
print(f"\nfind_by_external_id result: {user}")
if user:
    print(f"  provider: {user.provider}")
    print(f"  provider_subject: {user.provider_subject}")

user2 = store.get_user_by_name(identifier) if not user else None
print(f"\nget_user_by_name result: {user2}")
if user2:
    print(f"  active: {user2.active}")
    print(f"  password_hash: {user2.password_hash[:20]}...")

# Verify password
if user2:
    valid = user2 is not None and user2.active
    print(f"\nvalid: {valid}")
    ok = passwords.verify_password(user2.password_hash if valid else passwords.DUMMY_HASH, password) and valid
    print(f"ok: {ok}")
    print(f"verify_password result: {passwords.verify_password(user2.password_hash, password)}")