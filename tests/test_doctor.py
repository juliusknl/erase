from __future__ import annotations

import subprocess
from pathlib import Path

from erasure import doctor


def test_read_env_ignores_comments_and_empty_values(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nERASURE_GOOGLE_CLIENT_ID='client-id'\n"
        'ERASURE_GOOGLE_CLIENT_SECRET="client-secret"\nEMPTY=\n',
        encoding="utf-8",
    )

    assert doctor.read_env(env) == {
        "ERASURE_GOOGLE_CLIENT_ID": "client-id",
        "ERASURE_GOOGLE_CLIENT_SECRET": "client-secret",
        "EMPTY": "",
    }


def test_inspect_reports_configuration_without_secret_values(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".env").write_text(
        "ERASURE_BASE_URL=http://127.0.0.1:8787\n"
        "ERASURE_GOOGLE_CLIENT_ID=private-client-id\n"
        "ERASURE_GOOGLE_CLIENT_SECRET=private-client-secret\n",
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(Path, "exists", lambda self: True)

    def runner(arguments, **_kwargs):  # type: ignore[no-untyped-def]
        stdout = "FileVault is On." if arguments[-1] == "status" else "available"
        return subprocess.CompletedProcess(arguments, 0, stdout=stdout, stderr="")

    checks = doctor.inspect(
        tmp_path,
        platform="darwin",
        which=lambda name: f"/usr/local/bin/{name}",
        runner=runner,
    )

    assert all(check.ok for check in checks)
    report = "\n".join(check.detail for check in checks)
    assert "private-client-id" not in report
    assert "private-client-secret" not in report


def test_inspect_rejects_nonlocal_base_url(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / ".env").write_text(
        "ERASURE_BASE_URL=https://public.example.com\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "exists", lambda self: False)

    checks = doctor.inspect(tmp_path, platform="linux", which=lambda _name: None)

    by_name = {check.name: check for check in checks}
    assert by_name["platform"].ok is False
    assert by_name["localhost binding"].ok is False
    assert by_name["ERASURE_GOOGLE_CLIENT_ID"].ok is True
    assert 'in-app setup' in by_name["ERASURE_GOOGLE_CLIENT_ID"].detail
