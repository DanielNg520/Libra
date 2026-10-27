"""Tests for libra.lecture_poll fetch and Whisper jobs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

import libra.lecture_poll as lp
from libra.config import Settings
from libra.lecture_fetch import FetchResult


def make_settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir()
    return Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "LIBRA_VAULT_DIR": str(vault),
            "LIBRA_TERM": "FA26",
            "GEMINI_API_KEY": "gem",
            "OPENROUTER_API_KEY": "or",
        }
    )


def make_settings_no_vault(tmp_path: Path) -> Settings:
    return Settings.load(
        {"LIBRA_STATE_DIR": str(tmp_path / "state"), "LIBRA_TERM": "FA26"}
    )


def test_refresh_maps_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir

    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        lp, "write_maps", lambda _settings: [vault / "Tools/maps/ECE 1.json"]
    )
    monkeypatch.setattr(lp, "has_uncommitted_changes", lambda _vault, _maps: True)
    monkeypatch.setattr(
        lp,
        "commit_paths",
        lambda _vault, _maps, _message: calls.append((_vault, _maps, _message)),
    )

    lp._refresh_maps(settings, vault)
    assert calls == [(vault, [vault / "Tools/maps"], "Lecture maps: 1 updated")]

    calls.clear()
    monkeypatch.setattr(lp, "write_maps", lambda _settings: [])
    lp._refresh_maps(settings, vault)
    assert calls == []

    def boom(_settings: Any) -> list[Path]:
        raise RuntimeError("boom")

    monkeypatch.setattr(lp, "write_maps", boom)
    with caplog.at_level(logging.WARNING):
        lp._refresh_maps(settings, vault)
    assert "lecture map rebuild failed: RuntimeError" in caplog.text
    assert calls == []

    write_maps_calls: list[Any] = []
    monkeypatch.setattr(lp, "transcribe_next", lambda _audio_dir: Path("/tmp/w.json"))
    monkeypatch.setattr(
        lp,
        "write_maps",
        lambda _settings: write_maps_calls.append(_settings) or [],
    )
    lp.run_whisper_job(settings)
    assert len(write_maps_calls) == 1


def test_refresh_readings_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = make_settings(tmp_path)

    write_readings_calls: list[Any] = []
    monkeypatch.setattr(
        lp,
        "write_readings",
        lambda _settings: write_readings_calls.append(_settings) or [],
    )
    lp._refresh_readings(settings)
    assert len(write_readings_calls) == 1
    assert write_readings_calls[0] is settings

    def boom(_settings: Any) -> list[Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(lp, "write_readings", boom)
    with caplog.at_level(logging.WARNING):
        lp._refresh_readings(settings)
    assert "readings export failed: RuntimeError" in caplog.text

    whisper_readings_calls: list[Any] = []
    monkeypatch.setattr(lp, "transcribe_next", lambda _audio_dir: Path("/tmp/w.json"))
    monkeypatch.setattr(lp, "write_maps", lambda _settings: [])
    monkeypatch.setattr(lp, "_commit_transcripts", lambda _vault, _message: None)
    monkeypatch.setattr(
        lp,
        "write_readings",
        lambda _settings: whisper_readings_calls.append(_settings) or [],
    )
    lp.run_whisper_job(settings)
    assert len(whisper_readings_calls) == 1


def test_run_whisper_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    commit_calls: list[tuple[Any, ...]] = []
    (settings.obsidian_academic_vault_dir / "ECE 158A" / "Transcripts").mkdir(
        parents=True, exist_ok=True
    )

    monkeypatch.setattr(lp, "transcribe_next", lambda p: Path("/tmp/w.json"))
    monkeypatch.setattr(lp, "has_uncommitted_changes", lambda *args: True)
    monkeypatch.setattr(lp, "commit_paths", lambda *args: commit_calls.append(args))
    assert lp.run_whisper_job(settings) == Path("/tmp/w.json")
    assert commit_calls == [
        (
            settings.obsidian_academic_vault_dir,
            [settings.obsidian_academic_vault_dir / "ECE 158A" / "Transcripts"],
            "Lecture transcript (Whisper)",
        )
    ]

    commit_calls.clear()
    monkeypatch.setattr(lp, "transcribe_next", lambda p: None)
    assert lp.run_whisper_job(settings) is None
    assert commit_calls == []

    commit_calls.clear()
    monkeypatch.setattr(
        lp,
        "transcribe_next",
        lambda p: (_ for _ in ()).throw(RuntimeError("bad")),
    )
    assert lp.run_whisper_job(settings) is None
    assert commit_calls == []


def test_wanted_courses(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    (vault / "ECE 158A").mkdir()
    (vault / "ECE 271A").mkdir()
    (vault / "Tools").mkdir()
    (vault / "Personal").mkdir()
    (vault / "Academic Planning").mkdir()
    (vault / ".obsidian").mkdir()
    (vault / "ECE 999").write_text("not a dir")
    assert lp.wanted_courses(settings) == {"ECE 158A", "ECE 271A"}

    no_vault = make_settings_no_vault(tmp_path)
    assert lp.wanted_courses(no_vault) == set()


def test_run_fetch_job_requires_term_and_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> FetchResult:
        pytest.fail("fetch_transcripts should not be called")

    monkeypatch.setattr(lp, "fetch_transcripts", fail)

    vault = tmp_path / "vault"
    vault.mkdir()
    settings_no_term = Settings.load({"LIBRA_STATE_DIR": str(tmp_path / "state"), "LIBRA_VAULT_DIR": str(vault)})
    with pytest.raises(ValueError, match="LIBRA_TERM"):
        lp.run_fetch_job(settings_no_term)

    settings_no_vault = make_settings_no_vault(tmp_path)
    with pytest.raises(ValueError, match="LIBRA_VAULT_DIR"):
        lp.run_fetch_job(settings_no_vault)


def test_run_fetch_job_passes_courses_and_term(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    (vault / "ECE 158A").mkdir()
    (vault / "ECE 108").mkdir()

    fetch_calls: list[tuple[set[str], str]] = []
    result = FetchResult(expired=True)
    monkeypatch.setattr(
        lp,
        "fetch_transcripts",
        lambda s, courses, term: fetch_calls.append((courses, term)) or result,
    )
    hook_calls: list[str] = []
    monkeypatch.setattr(
        lp, "_commit_transcripts", lambda v, m: hook_calls.append("commit")
    )
    monkeypatch.setattr(
        lp, "_refresh_maps", lambda s, v: hook_calls.append("maps")
    )
    monkeypatch.setattr(
        lp, "_refresh_readings", lambda s: hook_calls.append("readings")
    )

    returned = lp.run_fetch_job(settings)
    assert returned is result
    assert fetch_calls == [({"ECE 108", "ECE 158A"}, "FA26")]
    assert hook_calls == ["commit", "maps", "readings"]

    fetch_calls.clear()
    hook_calls.clear()
    lp.run_fetch_job(settings, {"ECE 108"})
    assert fetch_calls == [({"ECE 108"}, "FA26")]
    assert hook_calls == ["commit", "maps", "readings"]


def test_run_fetch_job_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    tdir = vault / "ECE 158A" / "Transcripts"
    tdir.mkdir(parents=True)
    tdir108 = vault / "ECE 108" / "Transcripts"
    tdir108.mkdir(parents=True)
    p1, p2 = Path("/tmp/p1.json"), Path("/tmp/p2.json")
    dirty = [True]
    monkeypatch.setattr(lp, "has_uncommitted_changes", lambda *args: dirty[0])
    commit_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(lp, "commit_paths", lambda *args: commit_calls.append(args))
    monkeypatch.setattr(lp, "_refresh_maps", lambda s, v: None)
    monkeypatch.setattr(lp, "_refresh_readings", lambda s: None)

    monkeypatch.setattr(lp, "fetch_transcripts", lambda s, c, t: FetchResult(written=[p1, p2]))
    lp.run_fetch_job(settings)
    assert commit_calls == [(vault, [tdir108, tdir], "Lecture transcripts: 2 new")]

    commit_calls.clear()
    monkeypatch.setattr(lp, "fetch_transcripts", lambda s, c, t: FetchResult())
    lp.run_fetch_job(settings)
    assert commit_calls == [(vault, [tdir108, tdir], "Lecture transcripts: earlier uncommitted")]

    commit_calls.clear()
    dirty[0] = False
    lp.run_fetch_job(settings)
    assert commit_calls == []
