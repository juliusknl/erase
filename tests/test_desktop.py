import json
import os
from subprocess import CompletedProcess

import pytest

from erasure import desktop
from erasure.crypto import verify_password


def test_source_entrypoint_uses_project_assets_not_terminal_directory(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(desktop.sys, 'argv', ['erase', '--no-open'])
    calls = []
    monkeypatch.setattr(desktop, 'launch', lambda root, data, **kwargs: calls.append((root, data, kwargs)))
    desktop.main()
    root, data, options = calls[0]
    assert (root / 'templates/setup.html').is_file()
    assert (root / 'catalog').is_dir()
    assert root != tmp_path
    assert data == Path.home() / 'Library/Application Support/erase'
    assert options == {'open_browser': False, 'foreground': False}


def test_source_commands_are_registered_and_mit_license_packaged():
    from importlib.metadata import distribution
    package = distribution('personal-erasure')
    commands = {entry.name: entry.value for entry in package.entry_points}
    assert commands['erase'] == 'erasure.desktop:main'
    assert commands['erase-demo'] == 'erasure.demo:main'
    assert package.metadata['License-Expression'] == 'MIT'
    assert any(str(path).endswith('/licenses/LICENSE') for path in package.files)


def lookup(monkeypatch, code=44):
    monkeypatch.setattr(desktop.subprocess, 'run', lambda args, **kw: CompletedProcess(args, code, '', ''))


def test_first_launch_keys_stored_atomically_and_not_in_data(tmp_path, monkeypatch):
    lookup(monkeypatch)
    writes = []
    monkeypatch.setattr(desktop.keychain_cli, '_store', lambda service, value: writes.append((service, value)))
    values = desktop.desktop_secrets(tmp_path, ask=lambda message: 'long synthetic password')
    assert len(writes) == 1
    assert writes[0][0].startswith('erase.desktop.')
    assert json.loads(writes[0][1]) == values
    assert verify_password('long synthetic password', values['ERASURE_PASSWORD_HASH'])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('code', [1, 36, 128])
def test_keychain_denial_never_regenerates_keys(tmp_path, monkeypatch, code):
    lookup(monkeypatch, code)
    with pytest.raises(desktop.StartupError, match='Keychain'):
        desktop.desktop_secrets(tmp_path, ask=lambda _: pytest.fail('Unexpected password prompt'))


def test_existing_database_without_keys_is_never_reinitialized(tmp_path, monkeypatch):
    lookup(monkeypatch)
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/erasure.db').write_bytes(b'synthetic')
    with pytest.raises(desktop.StartupError, match='original Keychain'):
        desktop.desktop_secrets(tmp_path, ask=lambda _: pytest.fail('Unexpected password prompt'))
    assert (tmp_path / 'data/erasure.db').read_bytes() == b'synthetic'


def test_wrong_password_confirmation_never_writes_keys(tmp_path, monkeypatch):
    lookup(monkeypatch)
    monkeypatch.setattr(desktop.keychain_cli, '_store', lambda *args: pytest.fail('Saved invalid password'))
    answers = iter(['short', 'long synthetic password', 'different password', 'short'])
    with pytest.raises(desktop.StartupError, match='passwords must match'):
        desktop.desktop_secrets(tmp_path, ask=lambda _: next(answers))


def test_saved_desktop_keys_are_reused_without_prompts(tmp_path, monkeypatch):
    from erasure.crypto import generate_master_key, generate_session_secret, hash_password
    values = {'ERASURE_MASTER_KEY': generate_master_key(),
              'ERASURE_SESSION_SECRET': generate_session_secret(),
              'ERASURE_PASSWORD_HASH': hash_password('synthetic long password')}
    lookup(monkeypatch, 0)
    monkeypatch.setattr(desktop.keychain_cli, '_read', lambda _: json.dumps(values))
    assert desktop.desktop_secrets(tmp_path, ask=lambda _: pytest.fail('Asked again')) == values


def test_cancel_is_not_reported_as_startup_failure(monkeypatch):
    monkeypatch.setattr(desktop.subprocess, 'run', lambda args, **kw: CompletedProcess(args, 1, '', 'User canceled. (-128)'))
    with pytest.raises(desktop.SetupCancelled):
        desktop.password_dialog('Synthetic prompt')


def test_password_reset_keeps_encryption_key_and_invalidates_sessions(tmp_path, monkeypatch, master_key):
    original = {'ERASURE_MASTER_KEY': master_key, 'ERASURE_PASSWORD_HASH': 'old-hash', 'ERASURE_SESSION_SECRET': 'old-session'}
    monkeypatch.setattr(desktop, 'desktop_secrets', lambda *args, **kw: dict(original))
    writes = []
    monkeypatch.setattr(desktop.keychain_cli, '_store', lambda _, value: writes.append(json.loads(value)))
    desktop.maintain(tmp_path, reset_password=True, ask=lambda _: 'new synthetic password')
    assert writes[0]['ERASURE_MASTER_KEY'] == master_key
    assert writes[0]['ERASURE_SESSION_SECRET'] != original['ERASURE_SESSION_SECRET']
    assert verify_password('new synthetic password', writes[0]['ERASURE_PASSWORD_HASH'])


def test_password_reset_refuses_running_app(tmp_path, monkeypatch):
    import fcntl
    with (tmp_path / '.launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(desktop.StartupError, match='Quit erase'):
            desktop.maintain(tmp_path, reset_password=True, ask=lambda _: pytest.fail('Asked while running'))


def test_desktop_backup_round_trip_and_no_overwrite(tmp_path, monkeypatch, master_key):
    import sqlite3

    from erasure.backup_cli import restore_backup
    from erasure.crypto import Vault

    (tmp_path / 'data').mkdir()
    with sqlite3.connect(tmp_path / 'data/erasure.db') as database:
        database.execute('create table marker (value text)')
        database.execute('insert into marker values (?)', ('synthetic private data',))
    monkeypatch.setattr(desktop, 'desktop_secrets', lambda *args, **kw: {'ERASURE_MASTER_KEY': master_key})
    target = tmp_path / 'copy.erasurebak'
    desktop.maintain(tmp_path, backup=target)
    assert b'synthetic private data' not in target.read_bytes()
    first = target.read_bytes()
    with pytest.raises(FileExistsError):
        desktop.maintain(tmp_path, backup=target)
    assert target.read_bytes() == first
    restored = tmp_path / 'restored.db'
    restore_backup(target, restored, Vault(master_key))
    with sqlite3.connect(restored) as database:
        assert database.execute('select value from marker').fetchone()[0] == 'synthetic private data'


def test_maintenance_never_initializes_missing_keys(tmp_path, monkeypatch):
    lookup(monkeypatch)
    with pytest.raises(desktop.StartupError, match='No desktop keys'):
        desktop.desktop_secrets(tmp_path, existing_only=True, ask=lambda _: pytest.fail('Initialized missing keys'))


def test_desktop_environment_does_not_inherit_other_installation(tmp_path, monkeypatch, master_key):
    monkeypatch.setenv('ERASURE_DATABASE_URL', 'sqlite:////private/real-user.db')
    monkeypatch.setenv('ERASURE_GOOGLE_CLIENT_SECRET', 'synthetic-secret')
    monkeypatch.setenv('ERASURE_DEMO_MODE', 'true')
    monkeypatch.setenv('ERASURE_JEV_ENABLED', 'true')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'synthetic-key')
    snapshot = dict(os.environ)
    try:
        desktop.configure_environment(tmp_path, tmp_path / 'state', {'ERASURE_MASTER_KEY': master_key})
        assert os.environ['ERASURE_DATABASE_URL'].endswith('/state/data/erasure.db')
        assert os.environ['ERASURE_DESKTOP_MODE'] == 'true'
        assert not any(k in os.environ for k in ['TYPESAFE_API_KEY', 'ERASURE_GOOGLE_CLIENT_SECRET', 'ERASURE_DEMO_MODE', 'ERASURE_JEV_ENABLED'])
        from erasure.config import Settings
        (tmp_path / '.env').write_text('ERASURE_DATABASE_URL=sqlite:////private/from-dotenv.db\n')
        monkeypatch.chdir(tmp_path)
        from erasure.config import get_settings
        get_settings.cache_clear()
        assert get_settings().database_url == os.environ['ERASURE_DATABASE_URL']
        assert not Settings(_env_file=None).jev_enabled
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        get_settings.cache_clear()


def test_default_launch_returns_after_background_health_without_serving(tmp_path, monkeypatch):
    root, data = tmp_path / 'source', tmp_path / 'data'
    for name in ('src', 'templates', 'static', 'catalog'):
        (root / name).mkdir(parents=True)
    monkeypatch.setattr(desktop.sys, 'platform', 'darwin')
    checks = iter([False, False, True])
    monkeypatch.setattr(desktop, 'existing_app', lambda: next(checks))
    monkeypatch.setattr(desktop.subprocess, 'run', lambda *args, **kwargs:
        CompletedProcess(args, 0, 'FileVault is On', ''))
    sequence = []
    monkeypatch.setattr(desktop, 'desktop_secrets', lambda _: sequence.append('keys'))
    monkeypatch.setattr(desktop.background, 'start', lambda *args: sequence.append('background'))
    monkeypatch.setattr(desktop.webbrowser, 'open', lambda _: sequence.append('browser'))
    monkeypatch.setattr(desktop, 'serve', lambda *args, **kwargs: pytest.fail('Foreground server'))
    desktop.launch(root, data)
    assert sequence == ['keys', 'background', 'browser']
