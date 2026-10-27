"""Vault course discovery and transcript and reading loaders (ported from vault Tools/librarian.py)."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Pattern, Tuple


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    course: str
    date: date
    kind: str
    path: Path
    segments: Tuple[Segment, ...]


@dataclass(frozen=True)
class Term:
    raw: str
    pattern: Pattern[str]


@dataclass
class Hit:
    transcript: Transcript
    first: int
    last: int
    terms_matched: int
    occurrences: int


@dataclass(frozen=True)
class Page:
    course: str
    rel: str
    kind: str
    number: int
    lines: Tuple[str, ...]


@dataclass
class PageHit:
    page: Page
    hit_lines: Tuple[int, ...]
    terms_matched: int
    occurrences: int


MATERIAL_DIRS = ("Slides", "Discussion", "Homework", "Textbooks", "Readings")


EXCLUDED_DIRS = frozenset({"Study notes", "Agent scratch", "Personal", "Academic Planning"})


def find_courses(root: Path, *, catalog: bool = False) -> dict:
    """Map course name to course directory.

    Default mode keeps only dirs with Transcripts/. Catalog mode keeps dirs
    with Transcripts/ or any material directory.
    """
    courses = {}
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        if catalog and entry.name in EXCLUDED_DIRS:
            continue
        if (entry / "Transcripts").is_dir():
            courses[entry.name] = entry
            continue
        if catalog:
            for material_dir in MATERIAL_DIRS:
                if (entry / material_dir).is_dir():
                    courses[entry.name] = entry
                    break
    return courses


def match_course(name: str, courses: dict) -> Optional[str]:
    """Match a course name case-insensitively, ignoring whitespace."""
    target = re.sub(r"\s+", "", name).lower()
    for course in courses:
        if re.sub(r"\s+", "", course).lower() == target:
            return course
    return None


def _transcript_name(path: Path) -> Optional[Tuple[date, str]]:
    """Return (date, kind) for a transcript file name, or None if invalid."""
    stem = path.stem
    parts = stem.split("-")
    if len(parts) == 3:
        date_str = stem
        kind = "lecture"
    elif len(parts) == 4 and parts[3] == "DI":
        date_str = "-".join(parts[:3])
        kind = "discussion"
    else:
        return None

    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    return d, kind


def _parse_transcript_file(path: Path) -> Optional[Tuple[date, str, List[Segment]]]:
    """Parse one transcript file; return None if it should be skipped."""
    parsed_name = _transcript_name(path)
    if parsed_name is None:
        return None
    d, kind = parsed_name

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        print(f"warning: skipping {path}: {exc}", file=sys.stderr)
        return None

    if not isinstance(data, list):
        print(f"warning: skipping {path}: not a list", file=sys.stderr)
        return None

    segments = []
    for item in data:
        try:
            if not isinstance(item, dict):
                continue
            start = item.get("start")
            end = item.get("end")
            text = item.get("text")
            if not isinstance(start, (int, float)) or not isinstance(text, str):
                continue
            end = end if isinstance(end, (int, float)) else float(start)
            segments.append(Segment(float(start), float(end), text))
        except (KeyError, TypeError, ValueError):
            continue
    if data and not segments:
        print(f"warning: skipping {path}: no valid segments", file=sys.stderr)
        return None
    return d, kind, segments


def load_transcripts(
    course: str,
    course_dir: Path,
    *,
    since: Optional[date] = None,
    until: Optional[date] = None,
    kind: str = "all",
) -> List[Transcript]:
    """Load transcripts for a course, filtered by date and kind."""
    transcripts = []
    transcript_dir = course_dir / "Transcripts"
    for path in sorted(transcript_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file():
            continue
        parsed = _parse_transcript_file(path)
        if parsed is None:
            continue
        d, k, segments = parsed
        if kind != "all" and k != kind:
            continue
        if since is not None and d < since:
            continue
        if until is not None and d > until:
            continue
        transcripts.append(
            Transcript(
                course=course,
                date=d,
                kind=k,
                path=path,
                segments=tuple(segments),
            )
        )
    transcripts.sort(key=lambda t: (t.date, t.kind))
    return transcripts


def format_ts(seconds: float) -> str:
    """Format seconds as mm:ss (total minutes, floor of seconds)."""
    total = int(seconds)
    minutes = total // 60
    secs = total % 60
    return f"{minutes:02d}:{secs:02d}"


def readings_dir(root: Path) -> Path:
    return root / "Tools" / "readings"


def load_pages(root: Path, course: str, kinds: set) -> List[Page]:
    base = readings_dir(root) / course
    if not base.is_dir():
        return []
    pages = []
    for path in sorted(base.rglob("*.md")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if len(lines) < 2 or not lines[0].startswith("# ") or lines[1] not in (
            "Kind: reading",
            "Kind: textbook",
        ):
            rel = path.relative_to(root)
            print(f"warning: skipping malformed reading {rel}", file=sys.stderr)
            continue
        kind = lines[1].split(":", 1)[1].strip()
        if (kind == "reading" and "readings" not in kinds) or (
            kind == "textbook" and "textbooks" not in kinds
        ):
            continue
        rel = lines[0][2:].strip()
        page_lines = []
        number = 0
        body = lines[2:]
        if body and body[0] == "":
            body = body[1:]
        in_page = False
        for line in body:
            match = re.match(r"^### Page (\d+)\s*$", line)
            if match:
                if in_page:
                    pages.append(
                        Page(
                            course=course,
                            rel=rel,
                            kind=kind,
                            number=number,
                            lines=tuple(page_lines),
                        )
                    )
                    page_lines = []
                number = int(match.group(1))
                in_page = True
            elif in_page:
                stripped = line.strip()
                if stripped:
                    page_lines.append(stripped)
        if in_page:
            pages.append(
                Page(
                    course=course,
                    rel=rel,
                    kind=kind,
                    number=number,
                    lines=tuple(page_lines),
                )
            )
    return pages
