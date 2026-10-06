"""Allowlisted source export. Never copy a working tree wholesale into a release."""

from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from pathlib import Path

TOP_FILES = {
    'README.md', 'SECURITY.md', 'CONTRIBUTING.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
    'pyproject.toml', 'uv.lock', 'requirements.lock', '.env.example', '.gitignore',
    '.dockerignore', 'Dockerfile', 'docker-compose.yml', 'docker-compose.demo.yml',
    'docs/assets/erase-banner.svg', 'docs/assets/erase-dashboard.png',
}
TREE_EXTENSIONS = {
    '.github': {'.yml', '.yaml'},
    'src': {'.py'}, 'templates': {'.html'},
    'static': {'.css', '.js', '.svg', '.woff2', '.txt'},
    'catalog': {'.yml', '.yaml', '.csv', '.json'}, 'docs': {'.md'},
    'tests': {'.py', '.json', '.csv'}, 'macos': {'.m'},
}
SCRIPTS = {'desktop_entry.py', 'build_macos.py', 'release_check.py', 'smoke_macos.py'}
SECRET_PATTERNS = [
    re.compile(rb'GOCSPX-[A-Za-z0-9_-]{20,}'),
    re.compile(rb'AIza[A-Za-z0-9_-]{30,}'),
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(rb'(?i)(?:access_token|refresh_token)["\s]*[:=]["\s]*ya29\.'),
    re.compile(rb'sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}'),
    re.compile(rb'(?:ghp_|github_pat_)[A-Za-z0-9_]{30,}'),
    re.compile(rb'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}'),
    re.compile(rb'AKIA[0-9A-Z]{16}'),
]


def source_files(root: Path):
    root = root.resolve()
    selected = [root / name for name in TOP_FILES if (root / name).is_file()]
    for tree, extensions in TREE_EXTENSIONS.items():
        directory = root / tree
        if directory.is_symlink():
            raise ValueError(f'Release source is a symlink: {tree}')
        for path in directory.rglob('*'):
            if path.is_symlink():
                raise ValueError(f'Release source is a symlink: {path.relative_to(root)}')
            if path.is_file() and path.suffix in extensions and '__pycache__' not in path.parts:
                selected.append(path)
    selected.extend(root / 'scripts' / name for name in SCRIPTS if (root / 'scripts' / name).is_file())
    for path in selected:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Release source escapes its project directory')
    return sorted(selected)


def inspect_source(root: Path, *, require_license=True):
    files = source_files(root)
    issues = []
    for required in ['src/erasure/app.py', 'templates/setup.html', 'requirements.lock',
                     'pyproject.toml', 'uv.lock', 'README.md', 'docs/assistant-setup.md',
                     'scripts/desktop_entry.py', '.github/workflows/ci.yml',
                     'docs/assets/erase-banner.svg', 'docs/assets/erase-dashboard.png']:
        if root / required not in files:
            issues.append(f'Missing required source: {required}')
    if require_license and root / 'LICENSE' not in files:
        issues.append('A maintainer-approved license is missing')
    for path in files:
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            # Report path only. Never reproduce matched credentials in diagnostics.
            issues.append(f'Possible credential in {path.relative_to(root)}')
    return files, issues


def export_source(root: Path, destination: Path, *, require_license=True):
    root = root.resolve()
    files, issues = inspect_source(root, require_license=require_license)
    if issues:
        raise ValueError('; '.join(issues))
    destination.mkdir(parents=True, exist_ok=False)
    for source in files:
        target = destination / source.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return len(files)


def source_archive(root: Path, destination: Path, *, require_license=True):
    root = root.resolve()
    files, issues = inspect_source(root, require_license=require_license)
    if issues:
        raise ValueError('; '.join(issues))
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'erase/' + path.relative_to(root).as_posix())
    return hashlib.sha256(destination.read_bytes()).hexdigest()
