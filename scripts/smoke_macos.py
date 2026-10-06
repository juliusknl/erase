"""Run a relocated bundle with isolated synthetic state, no Keychain or mailbox."""
# ruff: noqa: S603 -- caller-selected local app artifact, isolated synthetic child environment

import argparse
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('app', type=Path)
args = parser.parse_args()
scratch = Path(tempfile.mkdtemp(prefix='erase-bundle-smoke-'))
app = scratch / 'Relocated erase.app'
shutil.copytree(args.app, app, symlinks=True)
root = app / 'Contents/Resources/app'
python = app / 'Contents/Resources/python/bin/python3'
state = scratch / 'synthetic-state'
(state / 'data').mkdir(parents=True)
with socket.socket() as probe:
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
code = '''
import sys
from pathlib import Path
root, state, port = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
sys.path.insert(0, str(root / 'src'))
from erasure.desktop import configure_environment
from erasure.crypto import generate_master_key, generate_session_secret, hash_password
configure_environment(root, state, {
 'ERASURE_MASTER_KEY': generate_master_key(),
 'ERASURE_SESSION_SECRET': generate_session_secret(),
 'ERASURE_PASSWORD_HASH': hash_password('synthetic smoke password'),
})
import os
os.environ['ERASURE_BASE_URL'] = f'http://127.0.0.1:{port}'
os.chdir(state)
import uvicorn
uvicorn.run('erasure.app:app', host='127.0.0.1', port=port, access_log=False, log_level='critical')
'''
environment = {k: v for k, v in os.environ.items()
               if not k.startswith(('ERASURE_', 'PYTHON')) and k != 'TYPESAFE_API_KEY'}
process = subprocess.Popen([str(python), '-I', '-B', '-c', code, str(root), str(state), str(port)],
                           cwd=scratch, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=10,
                      follow_redirects=True) as client:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError('Bundled server exited before readiness')
            try:
                health = client.get('/health')
                if health.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError('Bundled server did not become ready')
        assert health.json()['application'] == 'erase'
        assert not health.json()['demo_mode']
        assert client.post('/login', data={'password': 'synthetic smoke password'}).url.path == '/setup'
        for path, expected in [('/setup', 'Make it yours.'), ('/dashboard', 'Dashboard'),
                               ('/brokers', 'Broker library'), ('/quick-wins?view=all', 'Quick wins'),
                               ('/onboarding', 'Profile'), ('/appearance', 'Appearance')]:
            page = client.get(path)
            assert page.status_code == 200 and expected in page.text, path
        for path in ['/static/setup.css', '/static/themes.css', '/static/setup.js']:
            assert client.get(path).status_code == 200, path
        assert client.get('/health', headers={'Host': 'attacker.invalid'}).status_code == 400
        assert client.get('/api/status').json()['sent_requests'] == 0
        print('PASS: relocated bundled runtime, fresh database, login, setup, app pages, assets and localhost host boundary; zero sends.')
finally:
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    print('Isolated synthetic smoke artifacts:', scratch)
