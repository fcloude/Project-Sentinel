import sys
sys.path.insert(0, 'C:/dev/Project-Sentinel')

import tempfile
from pathlib import Path

from src.dashboard.app import create_app
from tests.app_support import make_security_config, log_in, PASSWORD

tmp = Path(tempfile.mkdtemp())
cfg = make_security_config(tmp)
app = create_app(engine=None, config=cfg)
app.config['TESTING'] = True
client = app.test_client()

print('Users before setup:', len(app.extensions['sentinel_store'].list_users()))
setup_resp = client.get('/setup')
print('Setup status:', setup_resp.status_code)

print('Users after setup attempt:', len(app.extensions['sentinel_store'].list_users()))

log_in(client, 'admin', PASSWORD)

print('Users after login:', len(app.extensions['sentinel_store'].list_users()))

resp = client.get('/')
print('Dashboard status:', resp.status_code)

with client.session_transaction() as sess:
    print('Session:', dict(sess))
