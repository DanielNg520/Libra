"""Lecture map IO: reads transcripts, cached deck pages and book maps; writes vault Tools/maps/<course>.json (ADR-0041 P2)."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from libra.config import Settings
from libra.lecture_align import (
    PAGE_MAX_DF,
    Anchor,
    Chapter,
    TermSpace,
    Window,
    align_track,
    chapter_links,
    clean_text,
    deck_order,
    spans_summary,
    tokenize,
    transcript_windows,
    unit_vectors,
    Unit,
)
from libra.source_pages import cached_pages
from libra.sources import (
    DISCUSSION_DIR,
    NON_COURSE_DIRS,
    SLIDES_DIR,
    TEXTBOOKS_DIR,
    TRANSCRIPTS_DIR,
    SourceFile,
    list_sources,
)
from libra.textbooks import BOOKS_DIR, load_cached_map, pdf_page_texts
from libra.lecture_docs import READS_DIR, sha256_file

log = logging.getLogger(__name__)

MAPS_DIR = "Tools/maps"
MAP_VERSION = 1
CONFIRMED_SUFFIX = ".confirmed.json"
TRACKS: tuple[tuple[str, str], ...] = (("lecture", SLIDES_DIR), ("discussion", DISCUSSION_DIR))
_TRANSCRIPT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-DI)?$")


@dataclass(frozen=True, slots=True)
class _TrackTranscript:
    id: str
    windows: list[Window]


def course_names(vault: Path) -> list[str]:
    names: list[str] = []
    for child in sorted(vault.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith(".") or name in NON_COURSE_DIRS or name == "Tools":
            continue
        if not (child / TRANSCRIPTS_DIR).is_dir():
            continue
        names.append(name)
    return names


def _transcript_files(vault: Path, course: str) -> list[Path]:
    return sorted(
        p
        for p in (vault / course / TRANSCRIPTS_DIR).glob("*.json")
        if _TRANSCRIPT_RE.match(p.stem)
    )


def _load_transcript(path: Path) -> list[Window] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        log.debug("lecture map: cannot read transcript %s", path)
        return None
    if not isinstance(raw, list):
        log.debug("lecture map: transcript %s is not a list", path)
        return None
    segments: list[dict[str, Any]] = []
    for item in raw:
        if (
            isinstance(item, dict)
            and isinstance(item.get("start"), (int, float))
            and isinstance(item.get("end"), (int, float))
            and isinstance(item.get("text"), str)
        ):
            segments.append(item)
        else:
            log.debug("lecture map: bad segment in %s", path)
            return None
    return transcript_windows(segments)


def _track_sources(sources: Sequence[SourceFile], course: str, folder: str) -> list[SourceFile]:
    prefix = f"{course}/{folder}/"
    return [s for s in sources if s.kind == "doc" and s.rel.startswith(prefix)]


def _books_mtime(settings: Settings) -> int:
    books_dir = settings.state_dir / READS_DIR / BOOKS_DIR
    try:
        files = list(books_dir.glob("*.json"))
    except OSError:
        return 0
    newest = 0
    for path in files:
        try:
            newest = max(newest, path.stat().st_mtime_ns)
        except OSError:
            continue
    return newest


def fingerprint(settings: Settings, course: str) -> str:
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        raise ValueError("Obsidian academic vault is not configured")
    sources = list_sources(settings, course)
    lines: list[str] = []
    for path in _transcript_files(vault, course):
        rel = f"{course}/{TRANSCRIPTS_DIR}/{path.name}"
        st = path.stat()
        lines.append(f"{rel}\t{st.st_size}\t{st.st_mtime_ns}\t0")
    for track, folder in TRACKS:
        for source in _track_sources(sources, course, folder):
            pages = len(cached_pages(settings, source))
            lines.append(f"{source.rel}\t{source.size}\t{source.mtime_ns}\t{pages}")
    for source in sources:
        if source.kind == "doc" and source.rel.startswith(f"{course}/{TEXTBOOKS_DIR}/") and source.rel.endswith(".pdf"):
            lines.append(f"{source.rel}\t{source.size}\t{source.mtime_ns}\t0")
    lines.append(f"books\t{_books_mtime(settings)}")
    confirmed_path = vault / MAPS_DIR / f"{course}{CONFIRMED_SUFFIX}"
    if confirmed_path.exists():
        st = confirmed_path.stat()
        lines.append(f"{st.st_size}\t{st.st_mtime_ns}")
    else:
        lines.append("")
    lines.append(f"v{MAP_VERSION}")
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def load_units(
    settings: Settings,
    course: str,
    sources: Sequence[SourceFile],
    folder: str,
    track: str,
) -> list[Unit]:
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        raise ValueError("Obsidian academic vault is not configured")
    grouped: dict[str, list[SourceFile]] = {}
    for source in _track_sources(sources, course, folder):
        path = vault / source.rel
        grouped.setdefault(sha256_file(path), []).append(source)
    units: list[Unit] = []
    for group in grouped.values():
        pages_by_rel: dict[str, Mapping[int, str]] = {}
        for source in group:
            pages = {
                n: clean_text(t)
                for n, t in cached_pages(settings, source).items()
                if clean_text(t).strip()
            }
            if pages:
                pages_by_rel[source.rel] = pages
        if not pages_by_rel:
            continue
        primary_rel = min(
            pages_by_rel,
            key=lambda rel: (deck_order(rel, track) is None, len(rel), rel),
        )
        duplicates = tuple(sorted(rel for rel in pages_by_rel if rel != primary_rel))
        units.append(
            Unit(
                rel=primary_rel,
                order=deck_order(primary_rel, track),
                pages=pages_by_rel[primary_rel],
                duplicates=duplicates,
            )
        )
    return sorted(units, key=lambda u: (u.order is None, u.order or (0, 0), u.rel))


def load_confirmed(vault: Path, course: str) -> list[dict[str, Any]]:
    path = vault / MAPS_DIR / f"{course}{CONFIRMED_SUFFIX}"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        log.warning("lecture map: cannot read confirmed file %s", path)
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("confirmed"), list):
        log.warning("lecture map: bad confirmed file %s", path)
        return []
    entries: list[dict[str, Any]] = []
    for item in raw["confirmed"]:
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("transcript"), str) or not isinstance(item.get("deck"), str):
            continue
        if "from_s" in item and not isinstance(item["from_s"], (int, float)):
            continue
        if "to_s" in item and not isinstance(item["to_s"], (int, float)):
            continue
        entries.append(item)
    return entries


def _anchors(
    confirmed: Sequence[dict[str, Any]],
    ordered: Sequence[Unit],
    transcript_ids: set[str],
) -> list[Anchor]:
    rel_to_index: dict[str, int] = {}
    for i, unit in enumerate(ordered):
        rel_to_index[unit.rel] = i
        for dup in unit.duplicates:
            rel_to_index[dup] = i
    anchors: list[Anchor] = []
    for entry in confirmed:
        transcript = entry["transcript"]
        deck = entry["deck"]
        if transcript not in transcript_ids or deck not in rel_to_index:
            log.warning("lecture map: confirmed %s -> %s not found", transcript, deck)
            continue
        from_s = float(entry.get("from_s", 0.0))
        to_s = float(entry.get("to_s", math.inf))
        anchors.append(
            Anchor(
                transcript=transcript,
                from_s=from_s,
                to_s=to_s,
                unit=rel_to_index[deck],
            )
        )
    return anchors


def load_chapters(settings: Settings, course: str, sources: Sequence[SourceFile]) -> list[Chapter]:
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        raise ValueError("Obsidian academic vault is not configured")
    chapters: list[Chapter] = []
    seen_shas: set[str] = set()
    for source in sources:
        if source.kind != "doc" or not source.rel.startswith(f"{course}/{TEXTBOOKS_DIR}/") or not source.rel.endswith(".pdf"):
            continue
        path = vault / source.rel
        sha = sha256_file(path)
        if sha in seen_shas:
            continue
        seen_shas.add(sha)
        cache_file = settings.state_dir / READS_DIR / BOOKS_DIR / f"{sha}.json"
        book_map = load_cached_map(cache_file, path)
        if book_map is None or not book_map.usable:
            continue
        try:
            texts = pdf_page_texts(path)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            log.warning("lecture map: no text for %s: %s", source.rel, type(exc).__name__)
            continue
        for entry in book_map.entries:
            tokens = tuple(tokenize(clean_text(" ".join(texts[entry.first - 1 : entry.last]))))
            if tokens:
                chapters.append(
                    Chapter(
                        book=source.rel,
                        title=entry.title,
                        first=entry.first,
                        last=entry.last,
                        tokens=tokens,
                    )
                )
    return chapters


def build_course_map(settings: Settings, course: str, inputs: str) -> dict[str, Any] | None:
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        return None
    sources = list_sources(settings, course)
    track_transcripts: dict[str, list[_TrackTranscript]] = {}
    all_transcripts: list[_TrackTranscript] = []
    for path in _transcript_files(vault, course):
        windows = _load_transcript(path)
        if windows is None:
            continue
        transcript = _TrackTranscript(id=path.stem, windows=windows)
        all_transcripts.append(transcript)
        if transcript.id.endswith("-DI"):
            track_transcripts.setdefault("discussion", []).append(transcript)
        else:
            track_transcripts.setdefault("lecture", []).append(transcript)
    if not all_transcripts:
        return None
    confirmed = load_confirmed(vault, course)
    spans: dict[str, list[dict[str, Any]]] = {}
    units_by_track: dict[str, list[Unit]] = {}
    ordered_by_track: dict[str, list[Unit]] = {}
    for track, folder in TRACKS:
        units = load_units(settings, course, sources, folder, track)
        ordered = [u for u in units if u.order is not None]
        units_by_track[track] = units
        ordered_by_track[track] = ordered
        space = TermSpace.build(
            [tokenize(p) for u in ordered for p in u.pages.values()],
            PAGE_MAX_DF,
        )
        vectors = [unit_vectors(u, space) for u in ordered]
        track_ids = {t.id for t in track_transcripts.get(track, [])}
        track_anchor_list = _anchors(confirmed, ordered, track_ids)
        track_sequences = [
            (t.id, t.windows) for t in track_transcripts.get(track, [])
        ]
        spans.update(
            align_track(
                track_sequences,
                ordered,
                vectors,
                space,
                track_anchor_list,
            )
        )
    all_units = [u for track, _ in TRACKS for u in units_by_track.get(track, [])]
    links = chapter_links(all_units, load_chapters(settings, course, sources))
    transcripts_output: list[dict[str, Any]] = []
    for transcript in sorted(all_transcripts, key=lambda t: t.id):
        kind = "discussion" if transcript.id.endswith("-DI") else "lecture"
        transcripts_output.append(
            {
                "id": transcript.id,
                "kind": kind,
                "path": f"{course}/{TRANSCRIPTS_DIR}/{transcript.id}.json",
                "spans": spans.get(transcript.id, []),
            }
        )
    decks_output: list[dict[str, Any]] = []
    for track, _ in TRACKS:
        for unit in units_by_track.get(track, []):
            deck_transcripts = sorted(
                t.id
                for t in track_transcripts.get(track, [])
                if unit.rel in {span.get("deck") for span in spans.get(t.id, [])}
            )
            decks_output.append(
                {
                    "rel": unit.rel,
                    "track": track,
                    "duplicates": list(unit.duplicates),
                    "transcripts": deck_transcripts,
                    "chapters": links.get(unit.rel, []),
                }
            )
    return {
        "version": MAP_VERSION,
        "course": course,
        "inputs": inputs,
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "transcripts": transcripts_output,
        "decks": decks_output,
    }


def _stored_inputs(path: Path) -> str | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(raw, dict) and isinstance(raw.get("inputs"), str):
        return raw["inputs"]
    return None


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def write_maps(settings: Settings) -> list[Path]:
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        return []
    maps = vault / MAPS_DIR
    maps.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for course in course_names(vault):
        try:
            inputs = fingerprint(settings, course)
            path = maps / f"{course}.json"
            if _stored_inputs(path) == inputs:
                continue
            data = build_course_map(settings, course, inputs)
            if data is None:
                continue
            _write_json(path, data)
            written.append(path)
            matched, unmatched = spans_summary(
                {t["id"]: t["spans"] for t in data["transcripts"]}
            )
            log.info(
                "lecture map %s: %d transcripts, %d spans matched, %d unmatched",
                course,
                len(data["transcripts"]),
                matched,
                unmatched,
            )
        except Exception as exc:
            log.warning("lecture map %s failed: %s", course, type(exc).__name__, exc_info=True)
            continue
    return written
