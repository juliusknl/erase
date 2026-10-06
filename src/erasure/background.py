"""User-scoped macOS supervision. No credentials are written to launchd files."""

import hashlib
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path


class BackgroundError(RuntimeError):
    pass


def label(data_dir):
    return 'local.erase.' + hashlib.sha256(str(data_dir.resolve()).encode()).hexdigest()[:16]


def login_path(data_dir):
    return Path.home() / 'Library/LaunchAgents' / (label(data_dir) + '.plist')


def specification(root, data_dir):
    entry = root / 'scripts/desktop_entry.py'
    if not entry.is_file() or not data_dir.is_dir() or data_dir.is_symlink():
        raise BackgroundError('The local installation could not be found. Reopen erase from its original folder.')
    return {
        'Label': label(data_dir),
        'ProgramArguments': [sys.executable, '-I', '-B', str(entry), '--foreground',
                             '--no-open', '--root', str(root), '--data-dir', str(data_dir)],
        'RunAtLoad': True,
        'KeepAlive': {'SuccessfulExit': False},
        'ThrottleInterval': 60,
        'WorkingDirectory': str(data_dir),
        'StandardOutPath': '/dev/null',
        'StandardErrorPath': '/dev/null',
        'Umask': 0o077,
    }


def owned(path, data_dir):
    if not path.exists() and not path.is_symlink():
        return False
    try:
        if path.is_symlink() or path.stat().st_uid != os.getuid():
            raise ValueError
        value = plistlib.loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError
        args = value.get('ProgramArguments', [])
        if (not isinstance(args, list) or value.get('Label') != label(data_dir) or '--data-dir' not in args
                or args[args.index('--data-dir') + 1] != str(data_dir)):
            raise ValueError
    except (ValueError, IndexError, OSError, plistlib.InvalidFileException) as exc:
        raise BackgroundError('An unrelated startup file occupies erase’s path. Nothing was replaced.') from exc
    return True


def write_spec(path, root, data_dir):
    spec = specification(root, data_dir)
    owned(path, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink():
        raise BackgroundError('The startup folder must not be a symbolic link.')
    fd, temporary = tempfile.mkstemp(prefix='.erase-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            plistlib.dump(spec, stream)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def set_login(root, data_dir, enabled):
    path = login_path(data_dir)
    if enabled:
        write_spec(path, root, data_dir)
    elif owned(path, data_dir):
        # Only our exact startup manifest; data, keys and current job stay intact.
        path.unlink()


def launchctl(*args):
    return subprocess.run(['/bin/launchctl', *args], capture_output=True,  # noqa: S603
                          text=True, timeout=15, check=False)


def start(root, data_dir):
    domain = f'gui/{os.getuid()}'
    target = domain + '/' + label(data_dir)
    if launchctl('print', target).returncode == 0:
        # No -k: start an exited job without terminating an existing process.
        if launchctl('kickstart', target).returncode:
            raise BackgroundError('macOS could not reopen erase. Check Login Items in System Settings.')
        return
    persistent = login_path(data_dir)
    path = persistent if owned(persistent, data_dir) else data_dir / 'background.plist'
    write_spec(path, root, data_dir)
    if launchctl('bootstrap', domain, str(path)).returncode:
        raise BackgroundError('macOS could not start erase in the background. Check System Settings → General → Login Items, then reopen erase.')


def stop(data_dir):
    target = f'gui/{os.getuid()}/' + label(data_dir)
    if launchctl('print', target).returncode and not owned(login_path(data_dir), data_dir):
        raise BackgroundError('No managed erase background process was found. Nothing was stopped.')
    if launchctl('bootout', target).returncode:
        raise BackgroundError('The background process could not be stopped. No other process was touched.')


def settings_paths(settings):
    if (sys.platform != 'darwin' or not settings.desktop_mode or settings.demo_mode
            or not settings.desktop_root or not settings.desktop_data_dir):
        return None
    return Path(settings.desktop_root), Path(settings.desktop_data_dir)


def status(settings):
    paths = settings_paths(settings)
    if not paths:
        return None
    try:
        return {'enabled': owned(login_path(paths[1]), paths[1]), 'error': ''}
    except BackgroundError as exc:
        return {'enabled': False, 'error': str(exc)}
