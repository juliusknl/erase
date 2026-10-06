from subprocess import CompletedProcess

import pytest

from erasure import keychain_cli
from erasure import macos_keychain as native


@pytest.mark.parametrize("codes", [[0], [44, 0], [44, 44, 0], [1], [36]])
def test_initialize_never_overwrites_existing_or_unreadable_keys(monkeypatch, codes):
    responses = iter(codes)
    monkeypatch.setattr(keychain_cli.subprocess, "run",
                        lambda args, **kwargs: CompletedProcess(args, next(responses), "", ""))
    monkeypatch.setattr(keychain_cli, "_store", lambda *args: pytest.fail("Overwrote a key"))
    monkeypatch.setattr(keychain_cli.getpass, "getpass", lambda *args: pytest.fail("Asked for password"))
    with pytest.raises(SystemExit):
        keychain_cli.initialize()


def test_new_keychain_setup_still_creates_all_three_keys(monkeypatch):
    stored = {}
    monkeypatch.setattr(keychain_cli.subprocess, "run",
                        lambda args, **kwargs: CompletedProcess(args, 44, "", ""))
    monkeypatch.setattr(keychain_cli.getpass, "getpass", lambda *args: "synthetic long password")
    monkeypatch.setattr(keychain_cli, "_store", lambda service, value: stored.update({service: value}))
    keychain_cli.initialize()
    assert set(stored) == set(keychain_cli.SERVICES.values())
    assert all(stored.values())


def test_launcher_can_enable_capability_without_granting_campaign_permission(monkeypatch):
    calls = []
    monkeypatch.setattr(keychain_cli, 'keychain_environment', lambda: {'EXAMPLE': 'synthetic'})
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return CompletedProcess(args, 0, 'FileVault is On', '')
    monkeypatch.setattr(keychain_cli.subprocess, 'run', run)
    keychain_cli.compose_up(enable_sending=True)
    assert calls[-1][1]['env']['ERASURE_LIVE_SUBMISSIONS'] == 'true'
    assert calls[-1][1]['env']['EXAMPLE'] == 'synthetic'
    keychain_cli.compose_up()
    assert 'ERASURE_LIVE_SUBMISSIONS' not in calls[-1][1]['env']


@pytest.mark.parametrize('existing', [True, False])
def test_guided_launcher_preserves_keys_and_existing_configuration(tmp_path, monkeypatch, existing):
    (tmp_path / 'src/erasure').mkdir(parents=True)
    (tmp_path / 'src/erasure/app.py').touch()
    (tmp_path / '.env.example').write_text('ERASURE_LIVE_SUBMISSIONS=false\n')
    if existing:
        (tmp_path / '.env').write_text('EXISTING=user-owned\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(keychain_cli.sys, 'platform', 'darwin')
    docker = tmp_path / 'docker'
    docker.touch()
    monkeypatch.setattr(keychain_cli, 'DOCKER', str(docker))
    initialized, launched, opened = [], [], []
    def run(args, **kwargs):
        return CompletedProcess(args, 0 if args[0] == keychain_cli.FILEVAULT or existing else 44,
                                'FileVault is On', '')
    monkeypatch.setattr(keychain_cli.subprocess, 'run', run)
    monkeypatch.setattr(keychain_cli, 'initialize', lambda: initialized.append(True))
    monkeypatch.setattr(keychain_cli, 'compose_up', lambda **kwargs: launched.append(kwargs))
    monkeypatch.setattr(keychain_cli.webbrowser, 'open', lambda url: opened.append(url))
    keychain_cli.setup_local(enable_sending=True)
    assert initialized == ([] if existing else [True])
    assert launched == [{'enable_sending': True}]
    assert opened == ['http://127.0.0.1:8787/setup']
    assert (tmp_path / '.env').read_text() == ('EXISTING=user-owned\n' if existing else 'ERASURE_LIVE_SUBMISSIONS=false\n')
    if not existing:
        assert (tmp_path / '.env').stat().st_mode & 0o777 == 0o600


def test_guided_launcher_does_not_generate_new_keys_over_existing_data(tmp_path, monkeypatch):
    (tmp_path / 'src/erasure').mkdir(parents=True)
    (tmp_path / 'src/erasure/app.py').touch()
    (tmp_path / '.env.example').touch()
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/erasure.db').touch()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(keychain_cli.sys, 'platform', 'darwin')
    monkeypatch.setattr(keychain_cli, 'DOCKER', str(tmp_path / 'src/erasure/app.py'))
    def run(args, **kwargs):
        return CompletedProcess(args, 0 if args[0] == keychain_cli.FILEVAULT else 44, 'FileVault is On', '')
    monkeypatch.setattr(keychain_cli.subprocess, 'run', run)
    monkeypatch.setattr(keychain_cli, 'initialize', lambda: pytest.fail('Replaced existing encryption keys'))
    with pytest.raises(SystemExit, match='Existing app data'):
        keychain_cli.setup_local()
    assert not (tmp_path / '.env').exists()


@pytest.mark.parametrize('lookup_status', [0, -25300, -25293])
def test_keychain_write_never_uses_subprocess_or_leaks_secret(monkeypatch, lookup_status):
    import ctypes
    from types import SimpleNamespace

    calls, released = [], []
    value = 'synthetic secret with quotes " and unicode ü and\nnewline'
    def find(*args):
        if lookup_status == 0:
            ctypes.cast(args[-1], ctypes.POINTER(ctypes.c_void_p))[0] = 123
        return lookup_status
    def add(*args):
        calls.append(('add', args))
        return 0
    def update(*args):
        calls.append(('update', args))
        return 0
    security = SimpleNamespace(SecKeychainFindGenericPassword=find,
        SecKeychainAddGenericPassword=add, SecKeychainItemModifyAttributesAndData=update)
    monkeypatch.setattr(native, 'frameworks', lambda: (security, SimpleNamespace(CFRelease=lambda item: released.append(item.value))))
    monkeypatch.setattr(keychain_cli.subprocess, 'run', lambda *args, **kwargs: pytest.fail('Secret passed to subprocess'))
    if lookup_status == -25293:
        with pytest.raises(native.KeychainError) as caught:
            keychain_cli._store('synthetic service', value)
        assert value not in str(caught.value)
        assert not calls
    else:
        keychain_cli._store('synthetic service', value)
        kind, args = calls[0]
        assert kind == ('add' if lookup_status == -25300 else 'update')
        assert value.encode() in args
        assert len(value.encode()) in args
        assert released == ([] if lookup_status == -25300 else [123])


def test_legacy_init_error_is_sanitized(monkeypatch, capsys):
    from subprocess import CalledProcessError
    monkeypatch.setattr(keychain_cli.sys, 'argv', ['erasure-keychain', 'init'])
    def fail():
        raise CalledProcessError(1, ['synthetic secret'])
    monkeypatch.setattr(keychain_cli, 'initialize', fail)
    with pytest.raises(SystemExit) as caught:
        keychain_cli.main()
    assert 'synthetic secret' not in str(caught.value)
    assert caught.value.__suppress_context__
    assert not capsys.readouterr().out
