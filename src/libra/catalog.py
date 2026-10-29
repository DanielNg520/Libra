"""Course material catalog for `libra catalog` (ported from vault Tools/librarian.py)."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from libra.library import (
    MATERIAL_DIRS,
    OUTDATED_DIR,
    Segment,
    _parse_transcript_file,
    _transcript_name,
    find_courses,
    format_ts,
    match_course,
)


def _opening_text(segments: List[Segment]) -> str:
    """Build the opening text for a transcript."""
    if not segments:
        return ""
    start_index = next(
        (i for i, segment in enumerate(segments) if segment.start >= 60),
        0,
    )
    texts = [s.text.strip() for s in segments[start_index:]]
    joined = " ".join(texts)
    joined = re.sub(r"\s+", " ", joined)
    return joined[:160]


def _file_entry(path: Path, course_dir: Path, root: Path) -> Optional[dict]:
    """Return a file entry dict, or None if the file should be skipped."""
    relative_parts = path.relative_to(course_dir).parts
    if any(part.startswith(".") for part in relative_parts):
        return None
    if OUTDATED_DIR in relative_parts[:-1]:
        return None
    if fnmatch.fnmatch(path.name, "*.conflict[0-9]*"):
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    size_kb = (stat.st_size + 1023) // 1024
    modified = datetime.fromtimestamp(stat.st_mtime).date().isoformat()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_kb": size_kb,
        "modified": modified,
    }


def _folder_entries(folder: Path, course_dir: Path, root: Path) -> List[dict]:
    """Return file entries for all files under a folder recursively."""
    entries = []
    for path in sorted(folder.rglob("*"), key=lambda p: p.as_posix()):
        if not path.is_file():
            continue
        entry = _file_entry(path, course_dir, root)
        if entry is not None:
            entries.append(entry)
    return entries


def catalog_course(course: str, course_dir: Path, root: Path) -> dict:
    """Build the catalog data for one course."""
    result = {"course": course, "transcripts": [], "folders": {}, "root_files": []}

    transcript_dir = course_dir / "Transcripts"
    if transcript_dir.is_dir():
        transcript_entries = []
        for path in sorted(transcript_dir.iterdir(), key=lambda p: p.name):
            if not path.is_file():
                continue
            parsed_name = _transcript_name(path)
            if parsed_name is None:
                continue
            parsed = _parse_transcript_file(path)
            if parsed is None:
                d, kind = parsed_name
                transcript_entries.append(
                    {
                        "date": d.isoformat(),
                        "kind": kind,
                        "path": path.relative_to(root).as_posix(),
                        "status": "unreadable",
                        "duration": None,
                        "segments": None,
                        "opening": None,
                    }
                )
                continue
            d, kind, segments = parsed
            duration = "00:00"
            if segments:
                duration = format_ts(segments[-1].end)
            transcript_entries.append(
                {
                    "date": d.isoformat(),
                    "kind": kind,
                    "path": path.relative_to(root).as_posix(),
                    "status": "ok",
                    "duration": duration,
                    "segments": len(segments),
                    "opening": _opening_text(segments),
                }
            )
        transcript_entries.sort(key=lambda e: (e["date"], 0 if e["kind"] == "lecture" else 1))
        result["transcripts"] = transcript_entries

    for material_dir in MATERIAL_DIRS:
        folder = course_dir / material_dir
        if folder.is_dir():
            result["folders"][material_dir] = _folder_entries(folder, course_dir, root)

    root_entries = []
    for path in sorted(course_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file():
            continue
        entry = _file_entry(path, course_dir, root)
        if entry is not None:
            root_entries.append(entry)
    result["root_files"] = root_entries

    return result


def _select_courses(root: Path, course_arg: Optional[str], *, catalog: bool) -> Optional[dict]:
    """Select courses by argument; return None on error."""
    if not root.exists() or not root.is_dir():
        print(f"error: root not found: {root}", file=sys.stderr)
        return None

    courses = find_courses(root, catalog=catalog)
    if not courses:
        if catalog:
            print(f"error: no course folders under {root}", file=sys.stderr)
        else:
            print(f"error: no course folders with Transcripts/ under {root}", file=sys.stderr)
        return None

    if course_arg is None:
        return courses

    course_name = match_course(course_arg, courses)
    if course_name is None:
        known = ", ".join(sorted(courses))
        print(
            f"error: unknown course '{course_arg}'; known: {known}",
            file=sys.stderr,
        )
        return None
    return {course_name: courses[course_name]}


def _print_catalog_block(course_data: dict) -> None:
    """Print one course block in text format."""
    course = course_data["course"]
    print(f"## {course}")

    transcripts = course_data["transcripts"]
    if transcripts:
        print(f"Transcripts ({len(transcripts)}):")
        for entry in transcripts:
            if entry["status"] == "unreadable":
                print(f"  {entry['date']} {entry['kind']} unreadable")
            else:
                print(
                    f"  {entry['date']} {entry['kind']} {entry['duration']} "
                    f"{entry['segments']} seg | {entry['opening']}"
                )

    for folder_name, entries in course_data["folders"].items():
        print(f"{folder_name}/ ({len(entries)}):")
        for entry in entries:
            print(
                f"  {entry['path']} {entry['size_kb']} KB {entry['modified']}"
            )

    root_files = course_data["root_files"]
    if root_files:
        print(f"Root files ({len(root_files)}):")
        for entry in root_files:
            print(
                f"  {entry['path']} {entry['size_kb']} KB {entry['modified']}"
            )


def cmd_catalog(args: argparse.Namespace, root: Path) -> int:
    """Execute the catalog subcommand."""
    selected = _select_courses(root, args.course, catalog=True)
    if selected is None:
        return 2

    course_data_list = []
    for name in sorted(selected):
        course_dir = selected[name]
        course_data = catalog_course(name, course_dir, root)
        course_data_list.append(course_data)

    if args.json:
        json.dump({"courses": course_data_list}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    for i, course_data in enumerate(course_data_list):
        if i > 0:
            print()
        _print_catalog_block(course_data)

    print()
    print(
        "readings and textbook text: Tools/readings/<course>/<path>.md; "
        "search with --in readings or --in textbooks"
    )
    return 0
