from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from erasure.keychain_cli import ACCOUNT, FILEVAULT, SECURITY, SERVICES


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


Runner = Callable[..., subprocess.CompletedProcess[str]]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _run_ok(runner: Runner, arguments: Sequence[str]) -> tuple[bool, str]:
    try:
        result = runner(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, type(exc).__name__
    output = (result.stdout or result.stderr).strip().splitlines()
    return result.returncode == 0, output[0] if output else f"exit {result.returncode}"


def inspect(
    root: Path,
    *,
    platform: str = sys.platform,
    which: Callable[[str], str | None] = shutil.which,
    runner: Runner = subprocess.run,
) -> list[Check]:
    checks: list[Check] = []
    checks.append(
        Check("platform", platform == "darwin", "macOS" if platform == "darwin" else platform)
    )

    docker = which("docker")
    checks.append(Check("docker", bool(docker), docker or "docker executable not found"))
    if docker:
        ok, detail = _run_ok(runner, [docker, "compose", "version"])
        checks.append(Check("docker compose", ok, detail))

    filevault_path = Path(FILEVAULT)
    if filevault_path.exists():
        ok, detail = _run_ok(runner, [FILEVAULT, "status"])
        enabled = ok and "FileVault is On" in detail
        checks.append(Check("FileVault", enabled, detail))
    else:
        checks.append(Check("FileVault", False, f"{FILEVAULT} not found"))

    security_path = Path(SECURITY)
    checks.append(Check("Keychain CLI", security_path.exists(), SECURITY))
    if security_path.exists():
        for variable, service in SERVICES.items():
            ok, _detail = _run_ok(
                runner,
                [SECURITY, "find-generic-password", "-a", ACCOUNT, "-s", service],
            )
            checks.append(
                Check(
                    variable,
                    ok,
                    "present in Keychain" if ok else "missing; run erasure-keychain init",
                )
            )

    env_path = root / ".env"
    env = read_env(env_path)
    checks.append(Check(".env", env_path.is_file(), str(env_path)))
    for variable in ("ERASURE_GOOGLE_CLIENT_ID", "ERASURE_GOOGLE_CLIENT_SECRET"):
        checks.append(
            Check(
                variable,
                True,
                "configured in environment" if env.get(variable) else "optional here; import the connection file during in-app setup",
            )
        )

    base_url = env.get("ERASURE_BASE_URL", "http://127.0.0.1:8787")
    parsed = urlsplit(base_url)
    local_url = parsed.scheme in {"http", "https"} and parsed.hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
    }
    checks.append(
        Check(
            "localhost binding",
            local_url,
            base_url if local_url else "ERASURE_BASE_URL must remain on localhost",
        )
    )

    data_dir = root / "data"
    writable_parent = data_dir if data_dir.exists() else root
    checks.append(
        Check(
            "data directory",
            writable_parent.is_dir() and os.access(writable_parent, os.W_OK),
            str(data_dir),
        )
    )
    return checks


def print_report(root: Path) -> bool:
    checks = inspect(root)
    for check in checks:
        marker = "ok" if check.ok else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")  # noqa: T201
    passed = all(check.ok for check in checks)
    print(  # noqa: T201
        "Ready for local startup." if passed else "Resolve failed checks before local startup."
    )
    return passed
