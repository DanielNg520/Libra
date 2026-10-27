"""Tests for CLI root resolution and catalog JSON output."""
import json
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
