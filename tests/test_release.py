import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from erasure.release import export_source, inspect_source, source_archive

ROOT = Path(__file__).parents[1]


def test_source_export_excludes_private_state_and_parent_history(tmp_path):
    destination = tmp_path / 'source'
    count = export_source(ROOT, destination)
    assert count > 150
    assert (destination / 'src/erasure/app.py').is_file()
    assert (destination / 'catalog/major-brokers.yml').is_file()
    assert (destination / 'scripts/desktop_entry.py').is_file()
    for name in ('.github/workflows/ci.yml', '.github/dependabot.yml', 'docs/assistant-setup.md',
                 'docs/assets/erase-banner.svg', 'docs/assets/erase-dashboard.png'):
        assert (destination / name).read_bytes() == (ROOT / name).read_bytes()
    assert (destination / 'src/erasure/chatgpt.py').read_bytes() == (ROOT / 'src/erasure/chatgpt.py').read_bytes()
    assert (destination / 'LICENSE').read_text() == (ROOT / 'LICENSE').read_text()
    assert 'MIT License' in (destination / 'LICENSE').read_text()
    for forbidden in ('.env', 'data', 'backups', '.git', '.claude', '.venv', 'dist', '.research-cache'):
        assert not (destination / forbidden).exists()
    assert not list(destination.rglob('*.db'))
    assert not list(destination.rglob('*.eml'))
    with pytest.raises(FileExistsError):
        export_source(ROOT, destination, require_license=False)
    archive = tmp_path / 'source.zip'
    digest = source_archive(ROOT, archive)
    assert len(digest) == 64
    with ZipFile(archive) as z:
        assert len(z.namelist()) == count
        assert z.read('erase/LICENSE') == (ROOT / 'LICENSE').read_bytes()
        assert z.read('erase/.github/workflows/ci.yml') == (ROOT / '.github/workflows/ci.yml').read_bytes()
        assert z.read('erase/src/erasure/chatgpt.py') == (ROOT / 'src/erasure/chatgpt.py').read_bytes()
        assert z.read('erase/docs/assets/erase-dashboard.png') == (ROOT / 'docs/assets/erase-dashboard.png').read_bytes()
        assert all(n.startswith('erase/') and '..' not in n.split('/') for n in z.namelist())
    with pytest.raises(FileExistsError):
        source_archive(ROOT, archive, require_license=False)


def test_release_scan_flags_credentials_without_echoing_them(tmp_path):
    (tmp_path / 'src/erasure').mkdir(parents=True)
    secret = 'GOCSPX-' + 'x' * 24
    (tmp_path / 'src/erasure/app.py').write_text(secret)
    _, issues = inspect_source(tmp_path)
    assert any('Possible credential' in i for i in issues)
    assert secret not in str(issues)
    assert any('license' in i for i in issues)
    with pytest.raises(ValueError, match='credential'):
        export_source(tmp_path, tmp_path / 'export')
    assert not (tmp_path / 'export').exists()


def test_export_refuses_symlinks(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/escape.py').symlink_to(ROOT / '.env')
    with pytest.raises(ValueError, match='symlink'):
        inspect_source(tmp_path)


def test_export_refuses_github_symlinks(tmp_path):
    (tmp_path / '.github').symlink_to(ROOT / '.github', target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        inspect_source(tmp_path)


def test_readme_media_allowlist_does_not_include_arbitrary_screenshots(tmp_path):
    assets = tmp_path / 'docs/assets'
    assets.mkdir(parents=True)
    (assets / 'erase-dashboard.png').write_bytes(b'fictional approved demo image')
    (assets / 'personal-mailbox.png').write_bytes(b'not approved for export')
    files, _ = inspect_source(tmp_path, require_license=False)
    assert assets / 'erase-dashboard.png' in files
    assert assets / 'personal-mailbox.png' not in files


def test_ci_installs_both_browsers_and_prepares_nonsecret_compose_environment():
    import yaml

    jobs = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())['jobs']
    browser_runs = [step.get('run', '') for step in jobs['visual']['steps']]
    assert 'uv run playwright install --with-deps chromium webkit' in browser_runs
    compose = next(step for step in jobs['container']['steps'] if step.get('name') == 'Validate Compose configuration')
    assert 'cp .env.example .env' in compose['run']
    assert 'docker compose config --quiet' in compose['run']
    assert set(compose['env'].values()) == {'ci-placeholder'}


def test_clean_export_compose_validation_with_only_example_and_placeholder_keys(tmp_path):
    docker = shutil.which('docker')
    if not docker:
        pytest.skip('Docker CLI not installed; configuration only, never starts a container')
    destination = tmp_path / 'source'
    export_source(ROOT, destination)
    shutil.copyfile(destination / '.env.example', destination / '.env')
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith('ERASURE_') and key != 'TYPESAFE_API_KEY'}
    environment.update({name: 'ci-placeholder' for name in (
        'ERASURE_MASTER_KEY', 'ERASURE_PASSWORD_HASH', 'ERASURE_SESSION_SECRET')})
    result = subprocess.run(  # noqa: S603 - trusted local Docker CLI; config only, synthetic environment
        [docker, 'compose', 'config', '--quiet'], cwd=destination, env=environment,
        capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('prefix,length', [('sk-proj-', 60), ('ghp_', 40), ('github_pat_', 60), ('AKIA', 16)])
def test_release_scan_also_rejects_other_common_credentials(tmp_path, prefix, length):
    secret = prefix + ('A' if prefix == 'AKIA' else 'x') * length
    (tmp_path / 'README.md').write_text(secret)
    _, issues = inspect_source(tmp_path)
    assert any('Possible credential in README.md' in issue for issue in issues)
    assert secret not in str(issues)


def test_browser_errors_and_host_boundary(tmp_path, master_key):
    from fastapi.testclient import TestClient

    from erasure.app import create_app
    from erasure.config import Settings
    from erasure.crypto import generate_session_secret, hash_password
    from erasure.db import create_db_engine

    settings = Settings(_env_file=None, master_key=master_key,
        password_hash=hash_password('synthetic release password'), session_secret=generate_session_secret(),
        templates_dir=ROOT / 'templates', static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    engine = create_db_engine(f'sqlite:///{tmp_path}/boundary.db')
    with TestClient(create_app(settings, engine)) as client:
        browser = {'Accept': 'text/html'}
        assert client.get('/health', headers={'Host': 'attacker.invalid'}).status_code == 400
        assert client.get('/health').json()['application'] == 'erase'
        missing = client.get('/no-such-page', headers=browser)
        assert missing.status_code == 404
        assert 'Back to dashboard' in missing.text and 'text/html' in missing.headers['content-type']
        invalid = client.post('/login', data={}, headers=browser)
        assert invalid.status_code == 422 and 'Go back' in invalid.text
        client.post('/login', data={'password': 'synthetic release password'})
        expired = client.post('/quick-wins/caci-uk', data={'csrf': 'wrong'}, headers=browser)
        assert expired.status_code == 403 and 'page has expired' in expired.text
        api_error = client.post('/login', data={})
        assert api_error.status_code == 422 and set(api_error.json()) == {'detail'}
    engine.dispose()
