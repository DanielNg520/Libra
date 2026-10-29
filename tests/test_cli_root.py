"""Tests for CLI root resolution and catalog JSON output."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import libra.config
from libra import cli


@pytest.fixture(autouse=True)
def isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(libra.config, "_read_config_env", lambda: {})
    monkeypatch.setenv("LIBRA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("LIBRA_VAULT_DIR", raising=False)
    monkeypatch.delenv("LIBRA_TERM", raising=False)
    monkeypatch.delenv("LIBRA_TZ", raising=False)


def test_explicit_root_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBRA_VAULT_DIR", str(tmp_path / "other"))
    assert cli._vault_root(tmp_path) == tmp_path


def test_env_vault_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("LIBRA_VAULT_DIR", str(vault))
    assert cli._vault_root(None) == vault.resolve()


def test_unset_vault_reports_and_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["catalog", "--json"]) == 2
    assert "LIBRA_VAULT_DIR is not set" in capsys.readouterr().err


def test_bad_settings_reports(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LIBRA_TZ", "Nowhere/Zone")
    assert cli._vault_root(None) is None
    assert capsys.readouterr().err.startswith("libra: LIBRA_TZ")


def test_main_uses_env_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "vault"
    (vault / "ECE 108" / "Transcripts").mkdir(parents=True)
    monkeypatch.setenv("LIBRA_VAULT_DIR", str(vault))
    assert cli.main(["catalog", "--json"]) == 0
    json.loads(capsys.readouterr().out)


_BLOCKED_IMPORT_CODE = r"""
import sys

class _BlockedFinder:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"httpx", "PIL", "playwright", "faster_whisper", "numpy"}:
            raise ImportError(f"blocked import: {name}")
        return None

sys.meta_path.insert(0, _BlockedFinder())

from libra import cli
raise SystemExit(cli.main(["--root", sys.argv[1], "catalog", "--json"]))
"""


def test_vault_commands_run_without_fedora_extra(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "ECE 108" / "Transcripts").mkdir(parents=True)

    env = os.environ.copy()
    env["LIBRA_STATE_DIR"] = str(tmp_path / "state")
    for key in ("LIBRA_VAULT_DIR", "LIBRA_TERM", "LIBRA_TZ"):
        env.pop(key, None)

    result = subprocess.run(
        [sys.executable, "-c", _BLOCKED_IMPORT_CODE, str(vault)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    json.loads(result.stdout)


def test_fetch_commands_report_missing_extra(tmp_path: Path) -> None:
    code = _BLOCKED_IMPORT_CODE.replace(
        '"--root", sys.argv[1], "catalog", "--json"', '"status"'
    )
    assert code != _BLOCKED_IMPORT_CODE
    env = os.environ.copy()
    env["LIBRA_STATE_DIR"] = str(tmp_path / "state")
    env.pop("LIBRA_VAULT_DIR", None)
    env.pop("LIBRA_TERM", None)
    env.pop("LIBRA_TZ", None)
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 2
    assert "needs the fedora extra" in result.stderr
    assert "ssh dyne@fedora libra status" in result.stderr
    assert "Traceback" not in result.stderr


def test_fetch_command_bad_settings_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LIBRA_TERM", "bad")
    assert cli.main(["status"]) == 2
    assert capsys.readouterr().err.startswith("libra: LIBRA_TERM")


def test_internal_import_error_is_not_masked(tmp_path: Path) -> None:
    code = """
import sys

class BlockLibraLecturePoll:
    def find_spec(self, name, path=None, target=None):
        if name == "libra.lecture_poll":
            raise ModuleNotFoundError(f"blocked import: {name}", name=name)
        return None

sys.meta_path.insert(0, BlockLibraLecturePoll())

from libra import cli
raise SystemExit(cli.main(["status"]))
"""
    env = os.environ.copy()
    env["LIBRA_STATE_DIR"] = str(tmp_path / "state")
    env.pop("LIBRA_VAULT_DIR", None)
    env.pop("LIBRA_TERM", None)
    env.pop("LIBRA_TZ", None)
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert result.returncode == 1
    assert "Traceback" in result.stderr
    assert "cannot import name 'lecture_poll'" in result.stderr
    assert "needs the fedora extra" not in result.stderr
