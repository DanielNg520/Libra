"""Lecture transcript fetch and Whisper jobs, run by the `libra` CLI and its timers."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from libra.obsidian_vault import commit_paths, has_uncommitted_changes
from libra.config import Settings
from libra.lecture_map import MAPS_DIR, write_maps
from libra.reading_export import write_readings
from libra.sources import TRANSCRIPTS_DIR
from libra.lecture_fetch import AUDIO_DIR, FetchResult, fetch_transcripts
from libra.lecture_whisper import transcribe_next

log = logging.getLogger(__name__)

COURSE_CODE_RE = re.compile(r"[A-Z]{2,5} [0-9]{1,4}[A-Z]{0,3}")
TOOLS_DIR = "Tools"


def wanted_courses(settings: Settings) -> set[str]:
    vault = settings.obsidian_academic_vault_dir
    if vault is None or not vault.is_dir():
        return set()
    return {
        child.name
        for child in vault.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and child.name != TOOLS_DIR
        and COURSE_CODE_RE.fullmatch(child.name) is not None
    }


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


def run_fetch_job(settings: Settings, wanted: set[str] | None = None) -> FetchResult:
    if settings.term is None:
        raise ValueError("LIBRA_TERM is not set")
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        raise ValueError("LIBRA_VAULT_DIR is not set")
    courses = wanted if wanted is not None else wanted_courses(settings)
    result = fetch_transcripts(settings, courses, settings.term)
    message = f"Lecture transcripts: {len(result.written)} new" if result.written else "Lecture transcripts: earlier uncommitted"
    _commit_transcripts(vault, message)
    _refresh_maps(settings, vault)
    _refresh_readings(settings)
    return result


def run_whisper_job(settings: Settings) -> Path | None:
    try:
        path = transcribe_next(settings.state_dir / AUDIO_DIR)
    except Exception as exc:
        log.warning("lecture Whisper failed: %s", type(exc).__name__)
        return None
    if path is None:
        return None
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        return path
    _commit_transcripts(vault, "Lecture transcript (Whisper)")
    _refresh_maps(settings, vault)
    _refresh_readings(settings)
    return path
