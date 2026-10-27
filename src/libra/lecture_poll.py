"""Daemon gating and background jobs for lecture transcript fetch and Whisper."""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from libra.obsidian_vault import commit_paths, has_uncommitted_changes
from semai.adapters.push import deliver
from libra.config import Settings
from semai.mail.extract import event_tz
from libra.courses import CourseStore
from libra.lecture_map import MAPS_DIR, write_maps
from libra.reading_export import write_readings
from libra.sources import TRANSCRIPTS_DIR, course_dir
from semai.state.task_store import TaskStore
from libra.lecture_fetch import AUDIO_DIR, fetch_transcripts, transcript_path
from libra.lecture_whisper import next_queued, transcribe_next

log = logging.getLogger(__name__)

FETCH_META_KEY = "lecture_fetch_last_attempt"
LOGIN_EXPIRED_META_KEY = "lecture_login_expired"
FETCH_RETRY_S = 3600
CATCHUP_S = 24 * 3600
RECORDING_DELAY_S = 30 * 60
MEETING_KINDS = ("Lecture", "Discussion")
WHISPER_HOURS = (1, 6)
LOGIN_PUSH_TITLE = "UCSD podcast login expired"
LOGIN_PUSH_MESSAGE = (
    "Lecture transcripts are paused. Run `omll podcast-login` on Fedora to sign in again."
)


def wanted_by_term(settings: Settings, course_store: CourseStore) -> dict[str, set[str]]:
    wanted: dict[str, set[str]] = {}
    for row in course_store.list_courses():
        code = row["code"]
        term = row["term"]
        if not term:
            continue
        try:
            course_dir(settings, code)
        except ValueError:
            continue
        meetings = course_store.list_meetings(code, term)
        if not any(m["type"] in MEETING_KINDS for m in meetings):
            continue
        wanted.setdefault(term, set()).add(code)
    return wanted


def last_meeting_day(meeting: Mapping[str, Any], now: datetime) -> date | None:
    tz = now.tzinfo
    if tz is None:
        return None
    end = datetime.strptime(meeting["end_time"], "%H:%M").time()
    first = date.fromisoformat(meeting["first_date"])
    last = date.fromisoformat(meeting["last_date"])
    latest = min(now.date(), last)
    days_back = (latest.weekday() - int(meeting["weekday"])) % 7
    d = latest - timedelta(days=days_back)
    if d < first:
        return None
    if datetime.combine(d, end, tzinfo=tz) + timedelta(seconds=RECORDING_DELAY_S) > now:
        d -= timedelta(days=7)
        if d < first:
            return None
    return d


def recent_gap(
    settings: Settings,
    course_store: CourseStore,
    wanted: dict[str, set[str]],
    now: datetime,
) -> bool:
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        return False
    cutoff = now.timestamp() - CATCHUP_S
    for term, codes in wanted.items():
        for code in codes:
            for meeting in course_store.list_meetings(code, term):
                if meeting["type"] not in MEETING_KINDS:
                    continue
                day = last_meeting_day(meeting, now)
                if day is None:
                    continue
                end = datetime.strptime(meeting["end_time"], "%H:%M").time()
                end_dt = datetime.combine(day, end, tzinfo=now.tzinfo)
                ended = end_dt.timestamp() + RECORDING_DELAY_S
                if ended < cutoff:
                    continue
                if not transcript_path(vault, code, meeting["type"], day).exists():
                    return True
    return False


def fetch_due(
    settings: Settings,
    store: TaskStore,
    course_store: CourseStore,
    wanted: dict[str, set[str]],
    now: datetime,
) -> bool:
    if not wanted:
        return False
    raw = store.meta_get(FETCH_META_KEY)
    if raw is None:
        return True
    try:
        last = float(raw)
    except ValueError:
        return True
    age = now.timestamp() - last
    if age < FETCH_RETRY_S:
        return False
    if age >= CATCHUP_S:
        return True
    return recent_gap(settings, course_store, wanted, now)


def whisper_due(settings: Settings, now: datetime) -> bool:
    if not (WHISPER_HOURS[0] <= now.hour < WHISPER_HOURS[1]):
        return False
    return next_queued(settings.state_dir / AUDIO_DIR) is not None


def _commit_transcripts(vault: Path, message: str) -> None:
    transcripts = sorted(p for p in vault.glob(f"*/{TRANSCRIPTS_DIR}") if p.is_dir())
    if has_uncommitted_changes(vault, transcripts):
        commit_paths(vault, transcripts, message)


def _refresh_maps(settings: Settings, vault: Path) -> None:
    try:
        written = write_maps(settings)
    except Exception as exc:
        log.warning("lecture map rebuild failed: %s", type(exc).__name__)
        return
    if not written:
        return
    maps = [vault / MAPS_DIR]
    if has_uncommitted_changes(vault, maps):
        commit_paths(vault, maps, f"Lecture maps: {len(written)} updated")


def _refresh_readings(settings: Settings) -> None:
    try:
        write_readings(settings)
    except Exception as exc:
        log.warning("readings export failed: %s", type(exc).__name__)
        return


def run_fetch_job(settings: Settings, store: TaskStore, wanted: dict[str, set[str]]) -> None:
    written: list[Path] = []
    expired = False
    any_failed = False
    for term in sorted(wanted):
        try:
            result = fetch_transcripts(settings, wanted[term], term)
        except Exception as exc:
            log.warning("lecture fetch %s failed: %s", term, type(exc).__name__)
            any_failed = True
            continue
        expired = expired or result.expired
        written.extend(result.written)
    if expired:
        if not store.meta_get(LOGIN_EXPIRED_META_KEY):
            store.meta_set(LOGIN_EXPIRED_META_KEY, "1")
            try:
                deliver(settings, store, "academic", LOGIN_PUSH_TITLE, LOGIN_PUSH_MESSAGE)
            except Exception as exc:
                log.warning("login expiry push failed: %s", type(exc).__name__)
    elif not any_failed and store.meta_get(LOGIN_EXPIRED_META_KEY):
        store.meta_set(LOGIN_EXPIRED_META_KEY, "")
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        return
    message = f"Lecture transcripts: {len(written)} new" if written else "Lecture transcripts: earlier uncommitted"
    _commit_transcripts(vault, message)
    _refresh_maps(settings, vault)
    _refresh_readings(settings)


def run_whisper_job(settings: Settings) -> None:
    try:
        path = transcribe_next(settings.state_dir / AUDIO_DIR)
    except Exception as exc:
        log.warning("lecture Whisper failed: %s", type(exc).__name__)
        return
    if path is None:
        return
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        return
    _commit_transcripts(vault, "Lecture transcript (Whisper)")
    _refresh_maps(settings, vault)
    _refresh_readings(settings)


def plan_lecture_job(
    settings: Settings, store: TaskStore, now: datetime | None = None
) -> Callable[[], None] | None:
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        return None
    if now is None:
        now = datetime.now(event_tz(settings, store))
    course_store = CourseStore(settings.db_path)
    try:
        wanted = wanted_by_term(settings, course_store)
        if fetch_due(settings, store, course_store, wanted, now):
            store.meta_set(FETCH_META_KEY, str(now.timestamp()))
            return functools.partial(run_fetch_job, settings, store, wanted)
        return (
            functools.partial(run_whisper_job, settings)
            if whisper_due(settings, now)
            else None
        )
    finally:
        course_store.close()


def log_job_result(task: asyncio.Future[Any]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.warning("lecture job crashed: %s", type(exc).__name__)
