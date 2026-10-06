import os
import plistlib
import re
import sys
import time
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from erasure import background


@pytest.fixture
def install(tmp_path, monkeypatch):
    root = tmp_path / 'source folder'
    (root / 'scripts').mkdir(parents=True)
    (root / 'scripts/desktop_entry.py').touch()
    data = tmp_path / 'private data'
    data.mkdir()
    monkeypatch.setattr(background.Path, 'home', lambda: tmp_path)
    return root, data


def test_background_is_not_login_opt_in_and_contains_no_credentials(install, monkeypatch):
    root, data = install
    calls = []
    def control(*args):
        calls.append(args)
        return CompletedProcess(args, 1 if args[0] == 'print' else 0)
    monkeypatch.setattr(background, 'launchctl', control)
    background.start(root, data)
    spec = plistlib.loads((data / 'background.plist').read_bytes())
    assert spec['KeepAlive'] == {'SuccessfulExit': False}
    assert spec['ThrottleInterval'] == 60
    assert spec['ProgramArguments'][-1] == str(data)
    assert '--foreground' in spec['ProgramArguments']
    assert 'EnvironmentVariables' not in spec
    assert not background.login_path(data).exists()
    assert calls[-1][0] == 'bootstrap'
    assert (data / 'background.plist').stat().st_mode & 0o777 == 0o600


def test_login_toggle_never_stops_running_work_or_removes_data(install, monkeypatch):
    root, data = install
    monkeypatch.setattr(background, 'launchctl', lambda *a: pytest.fail('Should not restart'))
    marker = data / 'user-data'
    marker.write_text('synthetic')
    background.set_login(root, data, True)
    assert background.owned(background.login_path(data), data)
    background.set_login(root, data, False)
    background.set_login(root, data, False)
    assert not background.login_path(data).exists()
    assert marker.read_text() == 'synthetic'


def test_refuses_unrelated_plist_and_symlink(install, tmp_path):
    root, data = install
    path = background.login_path(data)
    path.parent.mkdir(parents=True)
    path.write_bytes(plistlib.dumps({'Label': 'someone.else'}))
    for enable in (True, False):
        with pytest.raises(background.BackgroundError, match='unrelated'):
            background.set_login(root, data, enable)
    assert plistlib.loads(path.read_bytes()) == {'Label': 'someone.else'}
    path.write_bytes(plistlib.dumps(['not', 'a', 'job']))
    with pytest.raises(background.BackgroundError, match='unrelated'):
        background.set_login(root, data, True)
    assert plistlib.loads(path.read_bytes()) == ['not', 'a', 'job']
    path.unlink()
    target = tmp_path / 'unrelated'
    target.write_text('keep')
    path.symlink_to(target)
    with pytest.raises(background.BackgroundError):
        background.set_login(root, data, True)
    assert target.read_text() == 'keep'


def test_existing_job_is_not_bootstrapped_twice(install, monkeypatch):
    calls = []
    monkeypatch.setattr(background, 'launchctl', lambda *args:
        calls.append(args) or CompletedProcess(args, 0))
    background.start(*install)
    assert [args[0] for args in calls] == ['print', 'kickstart']
    assert '-k' not in calls[1]


def test_bootstrap_failure_is_clear(install, monkeypatch):
    monkeypatch.setattr(background, 'launchctl', lambda *args: CompletedProcess(args, 1))
    with pytest.raises(background.BackgroundError, match='macOS could not start'):
        background.start(*install)


def test_login_setting_is_authenticated_csrf_protected_and_explicit(tmp_path, master_key, monkeypatch):
    from fastapi.testclient import TestClient

    from erasure.app import create_app
    from erasure.config import Settings
    from erasure.crypto import generate_session_secret, hash_password
    from erasure.db import create_db_engine

    root = Path(__file__).parents[1]
    settings = Settings(_env_file=None, master_key=master_key,
        password_hash=hash_password('background test password'), session_secret=generate_session_secret(),
        catalog_dir=tmp_path, templates_dir=root / 'templates', static_dir=root / 'static')
    engine = create_db_engine(f'sqlite:///{tmp_path}/ui.db')
    writes = []
    monkeypatch.setattr(background, 'status', lambda _: {'enabled': bool(writes and writes[-1]), 'error': ''})
    monkeypatch.setattr(background, 'settings_paths', lambda _: (root, tmp_path))
    monkeypatch.setattr(background, 'set_login', lambda root, data, enabled: writes.append(enabled))
    with TestClient(create_app(settings, engine)) as client:
        assert client.post('/background/login', data={'enabled': 'true'}).status_code in {401, 403}
        client.post('/login', data={'password': 'background test password'})
        page = client.get('/campaign').text
        csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        assert 'Start erase when I log in' in page
        assert not writes  # Viewing a page never installs a login item.
        assert client.post('/background/login', data={'csrf': 'wrong', 'enabled': 'true'}).status_code == 403
        assert not writes
        response = client.post('/background/login', data={'csrf': csrf, 'enabled': 'true'})
        assert 'Startup preference saved.' in response.text
        assert writes == [True]
        client.post('/background/login', data={'csrf': csrf})
        assert writes == [True, False]
    engine.dispose()


@pytest.mark.skipif(sys.platform != 'darwin' or os.environ.get('ERASURE_TEST_LAUNCHD') != '1',
                    reason='Explicit, isolated macOS launchd smoke test')
def test_real_launchd_survives_launcher_exit_and_restarts_crash(install, monkeypatch):
    root, data = install
    # This test-only process has no app imports, keys, sockets or email access.
    (root / 'scripts/desktop_entry.py').write_text(
        "from pathlib import Path\nimport sys, time\n"
        "p = Path(sys.argv[-1]) / 'starts'\n"
        "n = int(p.read_text()) + 1 if p.exists() else 1\n"
        "p.write_text(str(n))\n"
        "time.sleep(11)\n"
        "if n == 1: raise SystemExit(1)\n"
        "time.sleep(90)\n")
    original = background.specification
    monkeypatch.setattr(background, 'specification', lambda *args:
        {**original(*args), 'ThrottleInterval': 10})
    target = f'gui/{os.getuid()}/' + background.label(data)
    try:
        background.start(root, data)
        # start() has returned; launchd, not the calling terminal, owns the child.
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            counter = data / 'starts'
            if counter.exists() and counter.read_text() == '2':
                break
            time.sleep(0.2)
        else:
            pytest.fail('Isolated launchd process did not restart after its synthetic crash')
        assert background.launchctl('print', target).returncode == 0
        assert not background.login_path(data).exists()
    finally:
        background.launchctl('bootout', target)
    assert background.launchctl('print', target).returncode != 0
