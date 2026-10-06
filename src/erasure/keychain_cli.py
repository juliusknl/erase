from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from erasure.crypto import generate_master_key, generate_session_secret, hash_password
from erasure.macos_keychain import KeychainError, store_secret

ACCOUNT = os.environ.get("USER", "personal-erasure")
SECURITY = "/usr/bin/security"
DOCKER = "/usr/local/bin/docker"
FILEVAULT = "/usr/bin/fdesetup"
SERVICES = {
    "ERASURE_MASTER_KEY": "personal-erasure.master-key",
    "ERASURE_PASSWORD_HASH": "personal-erasure.password-hash",
    "ERASURE_SESSION_SECRET": "personal-erasure.session-secret",
}


def _store(service: str, value: str) -> None:
    store_secret(service, ACCOUNT, value)


def _read(service: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed macOS security executable and argument vector
        [SECURITY, "find-generic-password", "-a", ACCOUNT, "-s", service, "-w"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def initialize() -> None:
    # Reinitializing one missing value must never replace an existing master key.
    for service in SERVICES.values():
        existing = subprocess.run(  # noqa: S603 - fixed Keychain lookup, no secret output
            [SECURITY, "find-generic-password", "-a", ACCOUNT, "-s", service],
            check=False, capture_output=True, text=True,
        )
        if existing.returncode == 0:
            raise SystemExit(
                "Existing erase keys found. Setup will not overwrite them. "
                "Use erasure-keychain doctor and erasure-keychain up. "
                "If keys are incomplete, recover the original keys before continuing."
            )
        # 44 is Keychain's item-not-found exit status. Permission errors are not
        # evidence of an empty Keychain, and must never authorize replacement.
        if existing.returncode != 44:
            raise SystemExit("Cannot check existing Keychain entries; no keys were changed.")
    password = getpass.getpass("Dashboard password (12+ characters): ")
    confirmation = getpass.getpass("Repeat password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match")
    if len(password) < 12:
        raise SystemExit('Choose a dashboard password with at least 12 characters. No keys were created.')
    values = {
        "ERASURE_MASTER_KEY": generate_master_key(),
        "ERASURE_PASSWORD_HASH": hash_password(password),
        "ERASURE_SESSION_SECRET": generate_session_secret(),
    }
    for key, value in values.items():
        _store(SERVICES[key], value)
    print("Stored application secrets in macOS Keychain.")  # noqa: T201


def keychain_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key, service in SERVICES.items():
        environment[key] = _read(service)
    return environment


def compose_up(*, enable_sending: bool = False) -> None:
    filevault = subprocess.run(  # noqa: S603 - fixed FileVault status command
        [FILEVAULT, "status"], check=True, capture_output=True, text=True
    )
    if "FileVault is On" not in filevault.stdout:
        raise SystemExit("FileVault must be enabled before unattended operation")
    environment = keychain_environment()
    if enable_sending:
        environment['ERASURE_LIVE_SUBMISSIONS'] = 'true'
    subprocess.run(  # noqa: S603 - fixed Docker executable and compose arguments
        [DOCKER, "compose", "up", "-d", "--build", "--remove-orphans", '--wait', '--wait-timeout', '90'],
        check=True,
        env=environment,
    )


def setup_local(*, enable_sending: bool = False) -> None:
    """Prepare a local checkout without asking users to edit secrets/config files."""
    if sys.platform != 'darwin':
        raise SystemExit('The guided launcher currently supports macOS. No files were changed.')
    root = Path.cwd()
    template = root / '.env.example'
    if not template.is_file() or not (root / 'src/erasure/app.py').is_file():
        raise SystemExit('Run this command inside the tools/erasure project directory.')
    if not Path(DOCKER).exists():
        raise SystemExit('Install and open Docker Desktop first, then run this command again.')
    result = subprocess.run([FILEVAULT, 'status'], check=True, capture_output=True, text=True)  # noqa: S603
    if 'FileVault is On' not in result.stdout:
        raise SystemExit('Enable FileVault in macOS System Settings → Privacy & Security, then try again.')
    codes = [subprocess.run([SECURITY, 'find-generic-password', '-a', ACCOUNT, '-s', service],  # noqa: S603
                           check=False, capture_output=True, text=True).returncode
             for service in SERVICES.values()]
    if all(code == 44 for code in codes):
        from erasure.doctor import read_env

        previous = read_env(root / '.env')
        if (root / 'data/erasure.db').exists() or any(previous.get(key) for key in SERVICES):
            raise SystemExit('Existing app data or manual keys found. Recover or migrate the original keys before using guided setup; nothing was overwritten.')
        initialize()
    elif not all(code == 0 for code in codes):
        raise SystemExit('Existing keys are incomplete or inaccessible. Recover them before continuing; nothing was overwritten.')
    config = root / '.env'
    try:
        descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass  # Existing credentials and preferences belong to the user.
    else:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(template.read_text())
    compose_up(enable_sending=enable_sending)
    print('Open http://127.0.0.1:8787/setup after startup. Nothing sends without your in-app permission.')  # noqa: T201
    webbrowser.open('http://127.0.0.1:8787/setup')


def run_backup(command: str, path: Path) -> None:
    arguments = [sys.executable, "-m", "erasure.backup_cli", command, str(path)]
    if command == "restore":
        arguments.append("--confirm-overwrite")
    subprocess.run(arguments, check=True, env=keychain_environment())  # noqa: S603


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage erase secrets in macOS Keychain"
    )
    parser.add_argument("command", choices=("setup", "init", "doctor", "up", "backup", "restore"))
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument('--enable-sending', action='store_true',
                        help='Allow sending in this launch; in-app permission is still required')
    args = parser.parse_args()
    if args.command == 'setup':
        try:
            setup_local(enable_sending=args.enable_sending)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SystemExit('Could not finish local startup. Make sure Docker Desktop is running and Keychain access is allowed, then try again. Existing data and keys are kept.') from exc
    elif args.command == "init":
        try:
            initialize()
        except (KeychainError, subprocess.SubprocessError):
            raise SystemExit('Keychain setup failed. Unlock your login Keychain and retry; existing keys were kept.') from None
    elif args.command == "doctor":
        from erasure.doctor import print_report

        if not print_report(Path.cwd()):
            raise SystemExit(1)
    elif args.command == "up":
        compose_up(enable_sending=args.enable_sending)
    elif args.path is None:
        raise SystemExit(f"{args.command} requires a backup path")
    else:
        run_backup("create" if args.command == "backup" else "restore", args.path)


if __name__ == "__main__":
    main()
