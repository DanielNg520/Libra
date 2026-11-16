"""Tests for `libra study cards` command."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from libra import cli
from libra.config import Settings
from libra.study import commands
from libra.study.anki_sync import AnkiAuth
from libra.study.cards import CardPreview, meta_path


def _settings(tmp_path: Path, **kw: object) -> Settings:
    defaults: dict[str, object] = {
        "state_dir": tmp_path / "state",
        "anki_hkey": "",
        "tz": "UTC",
    }
    defaults.update(kw)
    return Settings(**defaults)


def test_dry_run_prints_preview_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    previews = [
        CardPreview(
            path=str(vault / "a.md"),
            source=str(vault / "source.md"),
            fronts=("front one", "front two"),
            needs_claude=False,
        ),
        CardPreview(
            path=str(vault / "b.md"),
            source=str(vault / "b.md"),
            fronts=(),
            needs_claude=True,
        ),
    ]
    monkeypatch.setattr(commands, "preview_cards", lambda *a, **k: previews)
    monkeypatch.setattr(commands, "load_secrets", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(commands, "claude_runner", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(commands, "make_cards", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))

    code = commands.cmd_study_cards(settings, vault, date(2026, 11, 10), True)
    out = capsys.readouterr().out

    assert code == 0
    assert str(vault / "a.md") in out
    assert f"(from {vault / 'source.md'})" in out
    assert str(vault / "b.md") in out
    assert "  card: front one" in out
    assert "  card: front two" in out
    assert "  needs Claude: Recall or Reading answers" in out
    assert (
        "study cards --dry-run 2026-11-10: 2 lessons, 2 cards without Claude, 1 need Claude"
        in out
    )
    assert not meta_path(settings.state_dir).exists()


def test_bad_meta_file_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    meta_dir = meta_path(settings.state_dir).parent
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path(settings.state_dir).write_text("{not valid json")

    code = commands.cmd_study_cards(settings, vault, date(2026, 11, 10), True)
    err = capsys.readouterr().err

    assert code == 2
    assert err.startswith("study cards:")


def test_real_run_without_anki_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(commands.importlib.util, "find_spec", lambda *a, **k: None)

    code = commands.cmd_study_cards(settings, vault, date(2026, 11, 10), False)
    err = capsys.readouterr().err

    assert code == 2
    assert "anki extra" in err


def test_real_run_without_key_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    sentinel = object()
    monkeypatch.setattr(commands.importlib.util, "find_spec", lambda *a, **k: sentinel)
    monkeypatch.setattr(commands, "load_secrets", lambda s: s)

    code = commands.cmd_study_cards(settings, vault, date(2026, 11, 10), False)
    err = capsys.readouterr().err

    assert code == 2
    assert "LIBRA_ANKIWEB_HKEY" in err


def test_real_run_calls_make_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path, anki_hkey="k")
    vault = tmp_path / "vault"
    vault.mkdir()
    sentinel = object()
    monkeypatch.setattr(commands.importlib.util, "find_spec", lambda *a, **k: sentinel)
    monkeypatch.setattr(commands, "load_secrets", lambda s: s)

    runner_records: list[tuple[Path, tuple[Path, ...]]] = []
    captured_runner = lambda *a, **k: lambda *a2, **k2: None
    def _runner(v: Path, dirs: tuple[Path, ...]) -> object:
        runner_records.append((v, dirs))
        return captured_runner
    monkeypatch.setattr(commands, "claude_runner", _runner)

    make_records: list[tuple[object, ...]] = []
    def _make_cards(*args: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
        make_records.append(args)
        return (("a.md",), ("b.md",))
    monkeypatch.setattr(commands, "make_cards", _make_cards)

    code = commands.cmd_study_cards(settings, vault, date(2026, 11, 10), False)
    out = capsys.readouterr().out

    assert code == 1
    assert "study cards 2026-11-10: carded 1, failed 1" in out
    assert "  carded: a.md" in out
    assert "  failed: b.md" in out
    assert runner_records == [(vault, commands.CLAUDE_READ_DIRS)]

    make_args = make_records[0]
    assert make_args[0] == vault
    assert make_args[1] == settings.state_dir
    assert make_args[3] == date(2026, 11, 10)
    assert make_args[4] is captured_runner
    assert isinstance(make_args[5], AnkiAuth)
    assert make_args[5].hkey == "k"


def test_cli_routes_cards_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("LIBRA_STATE_DIR", str(state_dir))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("LIBRA_OWNER_OK", raising=False)

    vault = tmp_path / "vault"
    vault.mkdir()

    records: list[tuple[Path, date, bool]] = []
    monkeypatch.setattr(
        commands,
        "cmd_study_cards",
        lambda settings, v, day, dry_run: records.append((v, day, dry_run)) or 0,
    )

    code = cli.main(
        ["--root", str(vault), "study", "cards", "--dry-run", "--date", "2026-11-10"]
    )

    assert code == 0
    assert records == [(vault, date(2026, 11, 10), True)]


def test_cli_refuses_real_cards_for_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("LIBRA_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.delenv("LIBRA_OWNER_OK", raising=False)

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(
        commands,
        "cmd_study_cards",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError()),
    )

    code = cli.main(["--root", str(vault), "study", "cards"])
    err = capsys.readouterr().err

    assert code == 2
    assert "study cards is owner-only" in err
