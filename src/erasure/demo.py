"""Separate demo launcher; never loads the user's .env, Keychain or database."""

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

from erasure.crypto import generate_master_key, generate_session_secret, hash_password

DEMO_PASSWORD = 'try-erasure-demo'  # noqa: S105 - public password for isolated synthetic demo only


def deny_outbound_connections(event, args):
    # The server accepts browser connections, but never initiates connections.
    # A process audit hook cannot be accidentally bypassed by another HTTP client.
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
        raise PermissionError('Outbound networking is disabled in the demo process')


def localize_links(markup):
    # Rewrite the actual href, not only click events: opening in a new tab must
    # also stay in the demo. Public catalog URLs remain evidence, never contacted.
    def replace(match):
        destination = html.unescape(match[2])
        # Account creation is an intentional real navigation, not a broker action.
        # Keep this exact-only: other Google URLs and redirect/query variants stay local.
        if destination == 'https://accounts.google.com/signup':
            return match[0]
        return 'href="/demo/external?' + html.escape(urlencode({'destination': destination}), quote=True) + '"'
    return re.sub(r'href=([\"\'])(https?://.*?)(?:\1)', replace, markup, flags=re.I)


def demo_environment(data_dir, port):
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = data_dir / 'demo-secrets.json'
    if not state_path.exists():
        secrets = {'master_key': generate_master_key(), 'session_secret': generate_session_secret(),
                   'password_hash': hash_password(DEMO_PASSWORD)}
        with open(state_path, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
            json.dump(secrets, handle)
    secrets = json.loads(state_path.read_text())
    # Override both inherited environment and the normal .env field sources.
    return {
        'ERASURE_DEMO_MODE': 'true', 'ERASURE_DATABASE_URL': f'sqlite:///{data_dir / "demo.db"}',
        'ERASURE_MASTER_KEY': secrets['master_key'], 'ERASURE_SESSION_SECRET': secrets['session_secret'],
        'ERASURE_PASSWORD_HASH': secrets['password_hash'], 'ERASURE_BASE_URL': f'http://localhost:{port}',
        'ERASURE_LIVE_SUBMISSIONS': 'true', 'ERASURE_JEV_ENABLED': 'false', 'TYPESAFE_API_KEY': '',
        'ERASURE_GOOGLE_CLIENT_ID': '', 'ERASURE_GOOGLE_CLIENT_SECRET': '',
        'ERASURE_WORKER_POLL_SECONDS': '1',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('.demo-data'))
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    os.environ.update(demo_environment(args.data_dir, args.port))
    sys.addaudithook(deny_outbound_connections)
    # Import after isolation settings: the app/database modules create globals.
    from erasure.config import get_settings
    get_settings.cache_clear()
    import uvicorn
    uvicorn.run('erasure.app:app', host=args.host, port=args.port)


if __name__ == '__main__':
    main()
