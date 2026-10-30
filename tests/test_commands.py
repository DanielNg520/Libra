"""Tests for the libra command handlers."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from libra import commands, lecture_fetch
from libra.config import Settings
from libra.read import ReadError

FetchResult = lecture_fetch.FetchResult


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "LIBRA_VAULT_DIR": str(tmp_path / "vault"),
            "LIBRA_TERM": "FA26",
        }
    )


def seed_cache(settings: Settings) -> None:
    index = settings.state_dir / "lecture_reads" / "source_index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("{}")


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fakes: dict[str, Any] = {}
    monkeypatch.setattr(
        commands.lecture_poll,
        "run_fetch_job",
        lambda *a: fakes["fetch"](*a),
    )
    monkeypatch.setattr(
        commands.lecture_poll,
        "run_whisper_job",
        lambda *a: fakes["whisper"](*a),
    )
    monkeypatch.setattr(
        commands.lecture_poll,
        "refresh_exports",
        lambda *a: fakes["exports"](*a),
    )
    return fakes


def test_fetch_refuses_without_cache(
    settings: Settings, patched: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    for command in (commands.cmd_fetch, commands.cmd_export):
        called: list[object] = []
        patched["fetch"] = lambda s: called.append(s) or FetchResult()
        patched["exports"] = lambda s: called.append(s)

        assert command(settings) == 2
        assert not called
        assert "refusing to touch vault exports" in capsys.readouterr().err


def test_fetch_summary_and_codes(
    settings: Settings, patched: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    seed_cache(settings)

    patched["fetch"] = lambda s: FetchResult(
        written=["a", "b"],
        queued=["c"],
        no_captions=[],
        errors=["ECE 108 Lecture 2026-10-20"],
    )
    assert commands.cmd_fetch(settings) == commands.EXIT_PARTIAL
    assert commands.EXIT_PARTIAL == 4
    out, _ = capsys.readouterr()
    lines = out.splitlines()
    assert lines[0] == "fetch FA26: 2 new, 1 queued for Whisper, 0 without captions, 1 errors"
    assert "  error: ECE 108 Lecture 2026-10-20" in out

    patched["fetch"] = lambda s: FetchResult(
        written=["a"], queued=[], no_captions=[], errors=[]
    )
    assert commands.cmd_fetch(settings) == 0

    patched["fetch"] = lambda s: FetchResult(
        written=[], queued=[], no_captions=[], errors=[], expired=True
    )
    assert commands.cmd_fetch(settings) == 3
    assert "libra login" in capsys.readouterr().err

    def raise_value_error(s: Settings) -> FetchResult:
        raise ValueError("LIBRA_TERM is not set")

    patched["fetch"] = raise_value_error
    assert commands.cmd_fetch(settings) == 2


def test_login_then_fetch(
    settings: Settings,
    patched: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_cache(settings)
    calls: list[Path] = []

    def fake_login(path: Path, timeout: float) -> int:
        calls.append(path)
        return 1

    monkeypatch.setattr(commands, "cmd_podcast_login", fake_login)
    monkeypatch.setattr(commands, "cmd_fetch", lambda s: 7)

    assert commands.cmd_login(settings, 30.0) == 1
    assert calls == [settings.state_dir / "ucsd-podcast-state.json"]

    def fake_login_ok(path: Path, timeout: float) -> int:
        calls.append(path)
        return 0

    monkeypatch.setattr(commands, "cmd_podcast_login", fake_login_ok)
    assert commands.cmd_login(settings, 30.0) == 7
    assert calls == [
        settings.state_dir / "ucsd-podcast-state.json",
        settings.state_dir / "ucsd-podcast-state.json",
    ]


def test_whisper_loop(
    settings: Settings,
    patched: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    start = datetime(2026, 1, 1, 0, tzinfo=settings.zone)
    times = [
        start + timedelta(hours=1),
        start + timedelta(hours=1),
        start + timedelta(hours=6),
    ]
    calls = 0

    def fake_now(zone: ZoneInfo) -> datetime:
        nonlocal calls
        result = times[min(calls, len(times) - 1)]
        calls += 1
        return result

    patched["whisper"] = lambda s: Path("out.m4a")
    assert commands.cmd_whisper(settings, 6, now=fake_now) == 0
    assert calls == 3
    assert capsys.readouterr().out.strip() == "whisper: 2 transcribed, 0 queued"

    outputs: list[Path | None] = [Path("out.m4a"), None]
    count = 0

    def fake_now_always(zone: ZoneInfo) -> datetime:
        return datetime(2026, 1, 1, 1, tzinfo=settings.zone)

    def fake_whisper_second(s: Settings) -> Path | None:
        nonlocal count
        result = outputs[count]
        count += 1
        return result

    patched["whisper"] = fake_whisper_second
    assert commands.cmd_whisper(settings, 6, now=fake_now_always) == 0
    assert count == 2
    assert capsys.readouterr().out.strip() == "whisper: 1 transcribed, 0 queued"

    audio_dir = settings.state_dir / "lecture_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "a.json").write_text("{}")
    (audio_dir / "a.m4a").write_bytes(b"")
    (audio_dir / "b.json").write_text("{}")
    assert commands.cmd_whisper(settings, 1, now=fake_now_always) == 0
    assert capsys.readouterr().out.strip() == "whisper: 0 transcribed, 1 queued"


def test_parse_pages() -> None:
    assert commands.parse_pages(None) == (None, None)
    assert commands.parse_pages("4") == (4, 4)
    assert commands.parse_pages("2-5") == (2, 5)

    for bad in ("x", "2-", "-3", "a-b"):
        with pytest.raises(ReadError) as exc:
            commands.parse_pages(bad)
        assert exc.value.code == "invalid_pages"


def test_read_json(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = {"ok": True, "pages": []}
    secret_calls: list[Settings] = []

    def fake_load_secrets(s: Settings) -> Settings:
        secret_calls.append(s)
        return s

    monkeypatch.setattr(commands, "read_pages", lambda *a, **kw: result)
    monkeypatch.setattr(commands, "load_secrets", fake_load_secrets)

    assert commands.cmd_read(settings, "ECE 108", "lecture.md", None, False) == 0
    out, _ = capsys.readouterr()
    assert out.strip() == '{\n  "ok": true,\n  "pages": []\n}'
    assert secret_calls == []

    assert commands.cmd_read(settings, "ECE 108", "lecture.md", None, True) == 0
    out, _ = capsys.readouterr()
    assert out.strip() == '{\n  "ok": true,\n  "pages": []\n}'
    assert len(secret_calls) == 1

    def fake_read_pages(*a: object, **kw: object) -> dict[str, object]:
        raise ReadError("unknown_source")

    monkeypatch.setattr(commands, "read_pages", fake_read_pages)
    assert commands.cmd_read(settings, "ECE 108", "lecture.md", None, False) == 1
    out, _ = capsys.readouterr()
    assert out.strip() == '{"ok": false, "error": "unknown_source"}'

    monkeypatch.setattr(commands, "read_pages", lambda *a, **kw: result)
    assert commands.cmd_read(settings, "ECE 108", "lecture.md", "x", True) == 1
    out, _ = capsys.readouterr()
    assert "invalid_pages" in out


def test_read_chapter_and_printed(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    def fake_read_pages(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"ok": True}

    def failing_read_pages(*args: object, **kwargs: object) -> dict[str, object]:
        raise ReadError("ambiguous_chapter", chapters=("A", "B"))

    monkeypatch.setattr(commands, "read_pages", fake_read_pages)

    assert commands.cmd_read(settings, "ECE 271A", "b.pdf", None, False, chapter="2") == 0
    assert calls[-1]["chapter"] == "2"
    assert calls[-1]["printed"] is None

    assert commands.cmd_read(settings, "ECE 271A", "b.pdf", None, False, printed="5-7") == 0
    assert calls[-1]["printed"] == (5, 7)
    assert calls[-1]["chapter"] is None

    assert commands.cmd_read(settings, "ECE 271A", "b.pdf", None, False, printed="9") == 0
    assert calls[-1]["printed"] == (9, 9)

    capsys.readouterr()
    assert commands.cmd_read(settings, "ECE 271A", "b.pdf", None, False, printed="x") == 1
    out, _ = capsys.readouterr()
    assert "invalid_pages" in out
    assert len(calls) == 3

    monkeypatch.setattr(commands, "read_pages", failing_read_pages)
    capsys.readouterr()
    assert commands.cmd_read(settings, "ECE 271A", "b.pdf", None, False, chapter="2") == 1
    out, _ = capsys.readouterr()
    assert out.strip() == '{"ok": false, "error": "ambiguous_chapter", "chapters": ["A", "B"]}'


def test_status(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime(2026, 1, 1, 0, tzinfo=settings.zone)
    monkeypatch.setattr(commands, "state_path", lambda s: s.state_dir / "ucsd-podcast-state.json")

    assert commands.cmd_status(settings, now=lambda zone: now) == 0
    out = capsys.readouterr().out
    assert "login state: none" in out
    assert f"vault: {settings.obsidian_academic_vault_dir}" in out
    assert "term: FA26" in out
    assert "whisper queue: 0" in out

    state = settings.state_dir / "ucsd-podcast-state.json"
    state.write_text("{}")
    os.utime(state, (now.timestamp(), now.timestamp()))
    later = now + timedelta(hours=2)

    assert commands.cmd_status(settings, now=lambda zone: later) == 0
    out = capsys.readouterr().out
    assert "login state: saved 2.0 h ago" in out
