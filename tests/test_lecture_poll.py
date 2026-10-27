"""Tests for libra.lecture_poll and the daemon tick that drives it."""

from __future__ import annotations

import asyncio
import logging
import threading
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

import semai.adapters.daemon as daemon_module
import libra.lecture_poll as lp
from libra.config import Settings
from libra.courses import CourseStore
from semai.state.task_store import TaskStore
from libra.lecture_fetch import FetchResult, transcript_path

TZ = ZoneInfo("America/Los_Angeles")


def make_settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir()
    return Settings.load(
        {
            "SEMAI_STATE_DIR": str(tmp_path / "state"),
            "SEMAI_OBSIDIAN_ACADEMIC_VAULT_DIR": str(vault),
            "GEMINI_API_KEY": "gem",
            "OPENROUTER_API_KEY": "or",
        }
    )


def make_settings_no_vault(tmp_path: Path) -> Settings:
    return Settings.load({"SEMAI_STATE_DIR": str(tmp_path / "state")})


LECTURE_158A: dict[str, Any] = {
    "code": "ECE 158A",
    "type": "Lecture",
    "weekday": 1,
    "start_time": "14:00",
    "end_time": "15:20",
    "location": "",
    "first_date": "2026-09-29",
    "last_date": "2026-12-01",
}


def seed_course(tmp_path: Path) -> tuple[Settings, CourseStore]:
    settings = make_settings(tmp_path)
    (settings.obsidian_academic_vault_dir / "ECE 158A").mkdir(parents=True)
    store = CourseStore(settings.db_path)
    store.upsert_course("ECE 158A")
    store.replace_term_meetings("FA26", [LECTURE_158A])
    store.resolve_terms()
    return settings, store


def seed_queue_entry(settings: Settings, entry_id: str = "q1") -> None:
    audio_dir = settings.state_dir / "lecture_audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / f"{entry_id}.m4a").write_text("audio")
    (audio_dir / f"{entry_id}.json").write_text("{}")


def test_wanted_by_term(tmp_path: Path) -> None:
    settings, course_store = seed_course(tmp_path)
    course_store.upsert_course("ECE 253")
    ece253_lecture = {
        "code": "ECE 253",
        "type": "Lecture",
        "weekday": 1,
        "start_time": "14:00",
        "end_time": "15:20",
        "location": "",
        "first_date": "2026-09-29",
        "last_date": "2026-12-01",
    }
    course_store.upsert_course("ECE 116")
    ece116_lab = {
        "code": "ECE 116",
        "type": "Lab",
        "weekday": 2,
        "start_time": "09:00",
        "end_time": "11:00",
        "location": "",
        "first_date": "2026-09-30",
        "last_date": "2026-12-02",
    }
    (settings.obsidian_academic_vault_dir / "ECE 116").mkdir(parents=True)
    course_store.replace_term_meetings("FA26", [LECTURE_158A, ece253_lecture, ece116_lab])
    course_store.resolve_terms()
    try:
        assert lp.wanted_by_term(settings, course_store) == {"FA26": {"ECE 158A"}}
    finally:
        course_store.close()


def test_last_meeting_day(tmp_path: Path) -> None:
    _, course_store = seed_course(tmp_path)
    try:
        meeting = course_store.list_meetings("ECE 158A", "FA26")[0]
        now = datetime(2026, 10, 20, 15, 49, tzinfo=TZ)
        assert lp.last_meeting_day(meeting, now) == date(2026, 10, 13)
        now = datetime(2026, 10, 20, 15, 50, tzinfo=TZ)
        assert lp.last_meeting_day(meeting, now) == date(2026, 10, 20)
        now = datetime(2026, 9, 28, 12, 0, tzinfo=TZ)
        assert lp.last_meeting_day(meeting, now) is None
        now = datetime(2026, 12, 20, 12, 0, tzinfo=TZ)
        assert lp.last_meeting_day(meeting, now) == date(2026, 12, 1)
    finally:
        course_store.close()


def test_fetch_due(tmp_path: Path) -> None:
    settings, course_store = seed_course(tmp_path)
    store = TaskStore(settings.db_path)
    wanted = {"FA26": {"ECE 158A"}}
    try:
        assert lp.fetch_due(settings, store, course_store, {}, datetime(2026, 10, 20, 16, 0, tzinfo=TZ)) is False

        now = datetime(2026, 10, 20, 16, 0, tzinfo=TZ)
        assert lp.fetch_due(settings, store, course_store, wanted, now) is True

        store.meta_set(lp.FETCH_META_KEY, str(now.timestamp() - 30 * 60))
        assert lp.fetch_due(settings, store, course_store, wanted, now) is False

        store.meta_set(lp.FETCH_META_KEY, str(now.timestamp() - 2 * 3600))
        assert lp.fetch_due(settings, store, course_store, wanted, now) is True

        transcript_path(
            settings.obsidian_academic_vault_dir, "ECE 158A", "Lecture", date(2026, 10, 20)
        ).parent.mkdir(parents=True)
        transcript_path(
            settings.obsidian_academic_vault_dir, "ECE 158A", "Lecture", date(2026, 10, 20)
        ).write_text("{}")
        assert lp.fetch_due(settings, store, course_store, wanted, now) is False

        store.meta_set(lp.FETCH_META_KEY, str(now.timestamp() - 25 * 3600))
        assert lp.fetch_due(settings, store, course_store, wanted, now) is True

        later = datetime(2026, 10, 22, 18, 0, tzinfo=TZ)
        store.meta_set(lp.FETCH_META_KEY, str((later - timedelta(hours=2)).timestamp()))
        assert lp.fetch_due(settings, store, course_store, wanted, later) is False
    finally:
        store.close()
        course_store.close()


def test_whisper_due(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    seed_queue_entry(settings)
    assert lp.whisper_due(settings, datetime(2026, 10, 20, 3, 0, tzinfo=TZ)) is True
    assert lp.whisper_due(settings, datetime(2026, 10, 20, 7, 0, tzinfo=TZ)) is False
    (settings.state_dir / "lecture_audio" / "q1.m4a").unlink()
    (settings.state_dir / "lecture_audio" / "q1.json").unlink()
    assert lp.whisper_due(settings, datetime(2026, 10, 20, 3, 0, tzinfo=TZ)) is False


def test_plan_lecture_job_no_vault(tmp_path: Path) -> None:
    settings = make_settings_no_vault(tmp_path)
    store = TaskStore(settings.db_path)
    try:
        result = lp.plan_lecture_job(settings, store, datetime(2026, 10, 20, 15, 0, tzinfo=TZ))
        assert result is None
        assert store.meta_get(lp.FETCH_META_KEY) is None
    finally:
        store.close()


def test_plan_lecture_job_fetch(tmp_path: Path) -> None:
    settings, _ = seed_course(tmp_path)
    store = TaskStore(settings.db_path)
    now = datetime(2026, 10, 20, 15, 0, tzinfo=TZ)
    try:
        job = lp.plan_lecture_job(settings, store, now)
        assert callable(job)
        assert store.meta_get(lp.FETCH_META_KEY) == str(now.timestamp())
        assert lp.plan_lecture_job(settings, store, now) is None
    finally:
        store.close()


def test_plan_lecture_job_whisper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, _ = seed_course(tmp_path)
    store = TaskStore(settings.db_path)
    now = datetime(2026, 10, 20, 3, 0, tzinfo=TZ)
    store.meta_set(lp.FETCH_META_KEY, str(now.timestamp() - 10 * 60))
    seed_queue_entry(settings)
    calls: list[Path] = []
    monkeypatch.setattr(lp, "transcribe_next", lambda p: calls.append(p) or None)
    try:
        job = lp.plan_lecture_job(settings, store, now)
        assert callable(job)
        job()
        assert calls == [settings.state_dir / "lecture_audio"]
    finally:
        store.close()


def test_run_fetch_job_expired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, _ = seed_course(tmp_path)
    store = TaskStore(settings.db_path)
    deliver_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(lp, "fetch_transcripts", lambda s, c, t: FetchResult(expired=True))
    monkeypatch.setattr(lp, "deliver", lambda *args: deliver_calls.append(args))

    lp.run_fetch_job(settings, store, {"FA26": {"ECE 158A"}})
    assert deliver_calls == [
        (settings, store, "academic", lp.LOGIN_PUSH_TITLE, lp.LOGIN_PUSH_MESSAGE)
    ]
    assert store.meta_get(lp.LOGIN_EXPIRED_META_KEY) == "1"

    lp.run_fetch_job(settings, store, {"FA26": {"ECE 158A"}})
    assert len(deliver_calls) == 1
    store.close()


def test_run_fetch_job_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, _ = seed_course(tmp_path)
    store = TaskStore(settings.db_path)
    store.meta_set(lp.LOGIN_EXPIRED_META_KEY, "1")
    monkeypatch.setattr(lp, "fetch_transcripts", lambda s, c, t: FetchResult())
    monkeypatch.setattr(lp, "deliver", lambda *args: pytest.fail("deliver called"))

    lp.run_fetch_job(settings, store, {"FA26": {"ECE 158A"}})
    assert store.meta_get(lp.LOGIN_EXPIRED_META_KEY) == ""
    store.close()


def test_run_fetch_job_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings, _ = seed_course(tmp_path)
    store = TaskStore(settings.db_path)
    store.meta_set(lp.LOGIN_EXPIRED_META_KEY, "1")
    monkeypatch.setattr(
        lp,
        "fetch_transcripts",
        lambda s, c, t: (_ for _ in ()).throw(RuntimeError("https://secret-url")),
    )
    monkeypatch.setattr(lp, "deliver", lambda *args: pytest.fail("deliver called"))

    with caplog.at_level(logging.WARNING):
        lp.run_fetch_job(settings, store, {"FA26": {"ECE 158A"}})
    assert store.meta_get(lp.LOGIN_EXPIRED_META_KEY) == "1"
    assert "secret-url" not in caplog.text
    store.close()


def test_run_fetch_job_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, _ = seed_course(tmp_path)
    store = TaskStore(settings.db_path)
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

    monkeypatch.setattr(lp, "fetch_transcripts", lambda s, c, t: FetchResult(written=[p1, p2]))
    lp.run_fetch_job(settings, store, {"FA26": {"ECE 158A"}})
    assert commit_calls == [(vault, [tdir108, tdir], "Lecture transcripts: 2 new")]

    commit_calls.clear()
    monkeypatch.setattr(lp, "fetch_transcripts", lambda s, c, t: FetchResult())
    lp.run_fetch_job(settings, store, {"FA26": {"ECE 158A"}})
    assert commit_calls == [(vault, [tdir108, tdir], "Lecture transcripts: earlier uncommitted")]

    commit_calls.clear()
    dirty[0] = False
    lp.run_fetch_job(settings, store, {"FA26": {"ECE 158A"}})
    assert commit_calls == []
    store.close()


def test_run_whisper_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    commit_calls: list[tuple[Any, ...]] = []
    (settings.obsidian_academic_vault_dir / "ECE 158A" / "Transcripts").mkdir(
        parents=True, exist_ok=True
    )

    monkeypatch.setattr(lp, "transcribe_next", lambda p: Path("/tmp/w.json"))
    monkeypatch.setattr(lp, "has_uncommitted_changes", lambda *args: True)
    monkeypatch.setattr(lp, "commit_paths", lambda *args: commit_calls.append(args))
    lp.run_whisper_job(settings)
    assert commit_calls == [
        (
            settings.obsidian_academic_vault_dir,
            [settings.obsidian_academic_vault_dir / "ECE 158A" / "Transcripts"],
            "Lecture transcript (Whisper)",
        )
    ]

    commit_calls.clear()
    monkeypatch.setattr(lp, "transcribe_next", lambda p: None)
    lp.run_whisper_job(settings)
    assert commit_calls == []

    commit_calls.clear()
    monkeypatch.setattr(
        lp,
        "transcribe_next",
        lambda p: (_ for _ in ()).throw(RuntimeError("bad")),
    )
    lp.run_whisper_job(settings)
    assert commit_calls == []


def test_log_job_result_exception(caplog: pytest.LogCaptureFixture) -> None:
    loop = asyncio.new_event_loop()
    try:
        fut = loop.create_future()
        fut.set_exception(ValueError("sensitive message"))
        with caplog.at_level(logging.WARNING):
            lp.log_job_result(fut)
    finally:
        loop.close()
    assert "ValueError" in caplog.text
    assert "sensitive message" not in caplog.text


def test_log_job_result_cancelled(caplog: pytest.LogCaptureFixture) -> None:
    loop = asyncio.new_event_loop()
    try:
        fut = loop.create_future()
        fut.cancel()
        with caplog.at_level(logging.WARNING):
            lp.log_job_result(fut)
    finally:
        loop.close()
    assert caplog.text == ""


@pytest.mark.asyncio
async def test_tick_lecture_fetch_runs_and_dedupes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, _ = seed_course(tmp_path)
    store = TaskStore(settings.db_path)
    fake_self = types.SimpleNamespace(settings=settings, _lecture_job=None)
    release = threading.Event()
    plan_calls = 0

    def fake_job() -> None:
        release.wait(10)

    def fake_plan(settings: Settings, store: TaskStore) -> Any:
        nonlocal plan_calls
        plan_calls += 1
        return fake_job if plan_calls == 1 else None

    monkeypatch.setattr(daemon_module, "plan_lecture_job", fake_plan)

    await asyncio.wait_for(
        daemon_module.AsyncDaemon._tick_lecture_fetch(fake_self, store, store, 0.0), 1
    )
    assert fake_self._lecture_job is not None
    assert not fake_self._lecture_job.done()
    assert plan_calls == 1

    await asyncio.wait_for(
        daemon_module.AsyncDaemon._tick_lecture_fetch(fake_self, store, store, 0.0), 1
    )
    assert plan_calls == 1

    release.set()
    await fake_self._lecture_job

    await daemon_module.AsyncDaemon._tick_lecture_fetch(fake_self, store, store, 0.0)
    assert plan_calls == 2
    assert fake_self._lecture_job is not None
    assert fake_self._lecture_job.done()
    store.close()


@pytest.mark.asyncio
async def test_tick_lecture_fetch_plan_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, _ = seed_course(tmp_path)
    store = TaskStore(settings.db_path)
    fake_self = types.SimpleNamespace(settings=settings, _lecture_job=None)
    monkeypatch.setattr(daemon_module, "plan_lecture_job", lambda s, st: None)

    await daemon_module.AsyncDaemon._tick_lecture_fetch(fake_self, store, store, 0.0)
    assert fake_self._lecture_job is None
    store.close()


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
