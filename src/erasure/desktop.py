"""Local macOS entry point. No Docker, shell profiles or developer .env required."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from erasure import background, keychain_cli
from erasure.crypto import (
    Vault,
    generate_master_key,
    generate_session_secret,
    hash_password,
)


class StartupError(RuntimeError):
    pass


class SetupCancelled(Exception):
    pass


def keychain_service(data_dir):
    return 'erase.desktop.' + hashlib.sha256(str(data_dir.resolve()).encode()).hexdigest()[:16]


def password_dialog(message):
    # Only fixed app-owned copy enters AppleScript. Passwords return through a pipe,
    # never a shell argument, environment variable or diagnostic log.
    script = ('text returned of (display dialog ' + json.dumps(message)
              + ' with title "Welcome to erase" default answer "" with hidden answer '
              + 'buttons {"Cancel", "Continue"} default button "Continue" cancel button "Cancel")')
    result = subprocess.run(['/usr/bin/osascript', '-'], input=script,  # noqa: S603
                            capture_output=True, text=True, check=False)
    if result.returncode:
        if '(-128)' in result.stderr:
            raise SetupCancelled
        raise StartupError('The password dialog could not open. Reopen erase to try again. No campaign was started.')
    return result.stdout.rstrip('\n')


def choose_password(ask):
    for _ in range(3):
        password = ask('Choose a password for your private dashboard (at least 12 characters). A password manager can remember it for you.')
        if len(password) >= 12 and ask('Enter the same dashboard password again.') == password:
            return password
    raise StartupError('The passwords must match and have at least 12 characters. Open erase to try again; no keys were replaced.')


def desktop_secrets(data_dir, *, ask=password_dialog, existing_only=False):
    service = keychain_service(data_dir)
    result = subprocess.run(  # noqa: S603
        [keychain_cli.SECURITY, 'find-generic-password', '-a', keychain_cli.ACCOUNT, '-s', service],
        check=False, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            values = json.loads(keychain_cli._read(service))
            if set(values) != set(keychain_cli.SERVICES) or not all(values.values()):
                raise ValueError('Incomplete key entry')
            Vault(values['ERASURE_MASTER_KEY'])
            return values
        except (ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
            raise StartupError('The saved erase keys could not be read. Unlock your login Keychain and reopen erase. Do not delete keys or existing data.') from exc
    if result.returncode != 44:
        raise StartupError('Allow erase to access your login Keychain, then reopen it. Existing keys were not changed.')
    if existing_only:
        raise StartupError('No desktop keys were found for this data folder. Nothing was changed.')
    if (data_dir / 'data' / 'erasure.db').exists():
        raise StartupError('Existing data was found without its encryption key. Restore the original Keychain entry before continuing. Nothing was overwritten.')
    password = choose_password(ask)
    values = {
        'ERASURE_MASTER_KEY': generate_master_key(),
        'ERASURE_PASSWORD_HASH': hash_password(password),
        'ERASURE_SESSION_SECRET': generate_session_secret(),
    }
    # One atomic Keychain item avoids partially initialized sets of three keys.
    keychain_cli._store(service, json.dumps(values))
    return values


def maintain(data_dir, *, backup=None, reset_password=False, ask=password_dialog):
    if not data_dir.is_dir() or data_dir.is_symlink():
        raise StartupError('The desktop data folder was not found. Nothing was changed.')
    if backup is not None:
        from erasure.backup_cli import create_backup

        values = desktop_secrets(data_dir, existing_only=True)
        create_backup(data_dir / 'data/erasure.db', backup, Vault(values['ERASURE_MASTER_KEY']))
        return
    if reset_password:
        with (data_dir / '.launch.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StartupError('Quit erase before resetting its dashboard password.') from exc
            values = desktop_secrets(data_dir, existing_only=True)
            password = choose_password(ask)
            values['ERASURE_PASSWORD_HASH'] = hash_password(password)
            values['ERASURE_SESSION_SECRET'] = generate_session_secret()
            keychain_cli._store(keychain_service(data_dir), json.dumps(values))


def configure_environment(root, data_dir, values):
    # A desktop install must never accidentally inherit a developer's real
    # credentials, demo setting, database URL or external-service opt-in.
    for key in list(os.environ):
        if key.startswith('ERASURE_') or key == 'TYPESAFE_API_KEY':
            os.environ.pop(key)
    os.environ.update(values)
    os.environ.update({
        'ERASURE_DESKTOP_MODE': 'true',
        'ERASURE_DESKTOP_ROOT': str(root),
        'ERASURE_DESKTOP_DATA_DIR': str(data_dir),
        'ERASURE_DATABASE_URL': 'sqlite:///' + str(data_dir / 'data' / 'erasure.db'),
        'ERASURE_BASE_URL': 'http://127.0.0.1:8787',
        'ERASURE_TEMPLATES_DIR': str(root / 'templates'),
        'ERASURE_STATIC_DIR': str(root / 'static'),
        'ERASURE_CATALOG_DIR': str(root / 'catalog'),
        # Capability only. The same signed in-app consent gate remains mandatory.
        'ERASURE_LIVE_SUBMISSIONS': 'true',
    })


def existing_app(port=8787):
    probe = socket.socket()
    try:
        probe.bind(('127.0.0.1', port))
        return False
    except OSError:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                data = json.load(response)
            if data.get('application') == 'erase' and data.get('ok') is True:
                return True
        except (OSError, ValueError):
            pass
        raise StartupError('Another app is using erase’s local address (port 8787). Close that app and reopen erase. No running process was stopped.') from None
    finally:
        probe.close()


def launch(root, data_dir, *, open_browser=True, foreground=False):
    if sys.platform != 'darwin':
        raise StartupError('This desktop launcher supports macOS. The developer checkout remains available on other systems.')
    if not all((root / name).is_dir() for name in ('src', 'templates', 'static', 'catalog')):
        raise StartupError('The erase download is incomplete. Download a fresh copy; keep your existing data and keys.')
    if existing_app():
        if open_browser:
            webbrowser.open('http://127.0.0.1:8787/')
        return
    result = subprocess.run([keychain_cli.FILEVAULT, 'status'], check=False,  # noqa: S603
                            capture_output=True, text=True, timeout=15)
    if result.returncode or 'FileVault is On' not in result.stdout:
        raise StartupError('Turn on FileVault in System Settings → Privacy & Security, then reopen erase. It protects your local identity and mail data when this Mac is locked down.')
    os.umask(0o077)
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if data_dir.is_symlink() or (data_dir / 'data').is_symlink():
        raise StartupError('The erase data folder must be a local folder, not a symbolic link. No data was changed.')
    (data_dir / 'data').mkdir(exist_ok=True, mode=0o700)
    with (data_dir / '.launch.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StartupError('erase is already starting. Wait a moment, then open it again.') from exc
        if foreground:
            serve(root, data_dir, open_browser=open_browser)
            return
        # First-run interaction happens here, not in an invisible launchd job.
        desktop_secrets(data_dir)
    background.start(root, data_dir)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            ready = existing_app()
        except StartupError:
            # uvicorn can bind before startup/catalog loading has completed.
            ready = False
        if ready:
            if open_browser:
                webbrowser.open('http://127.0.0.1:8787/')
            return
        time.sleep(0.1)
    raise StartupError('erase is taking longer than expected to start. Reopen it after unlocking your login Keychain. Your data and keys were kept.')


def serve(root, data_dir, *, open_browser):
    values = desktop_secrets(data_dir)
    configure_environment(root, data_dir, values)
    os.chdir(data_dir)

    import uvicorn

    server = uvicorn.Server(uvicorn.Config('erasure.app:app', host='127.0.0.1', port=8787,
                                          log_level='warning', access_log=False))

    def open_when_ready():
        for _ in range(600):
            if server.started:
                if open_browser:
                    webbrowser.open('http://127.0.0.1:8787/')
                return
            if server.should_exit:
                return
            time.sleep(0.1)

    threading.Thread(target=open_when_ready, daemon=True).start()
    server.run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--data-dir', type=Path,
                        default=Path.home() / 'Library' / 'Application Support' / 'erase')
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--foreground', action='store_true', help='Run attached to this terminal instead of in the background')
    maintenance = parser.add_mutually_exclusive_group()
    maintenance.add_argument('--backup', type=Path, help='Create an encrypted backup at a new path')
    maintenance.add_argument('--reset-password', action='store_true', help='Reset dashboard access using your unlocked login Keychain; quit erase first')
    maintenance.add_argument('--stop', action='store_true', help='Quit the managed background process; keep data and permissions')
    args = parser.parse_args()
    try:
        if args.stop:
            background.stop(args.data_dir.absolute())
        elif args.backup is not None or args.reset_password:
            maintain(args.data_dir.absolute(), backup=args.backup, reset_password=args.reset_password)
        else:
            launch(args.root.resolve(), args.data_dir.absolute(), open_browser=not args.no_open,
                   foreground=args.foreground)
    except SetupCancelled:
        return
    except (StartupError, background.BackgroundError, OSError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, (StartupError, background.BackgroundError)) else 'erase could not start. Check Keychain access and available disk space, then try again. Your existing data was kept.'
        print(message, file=sys.stderr)  # No traceback, OAuth URLs or secret subprocess arguments.
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
