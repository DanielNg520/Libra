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
    CONFLICT_GLOB,
    MATERIAL_DIRS,
    OUTDATED_DIR,
    Segment,
    _parse_transcript_file,
    _transcript_name,
    format_ts,
    select_courses,
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
    if fnmatch.fnmatch(path.name, CONFLICT_GLOB):
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


def folder_entries(folder: Path, course_dir: Path, root: Path) -> List[dict]:
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
            result["folders"][material_dir] = folder_entries(folder, course_dir, root)

    root_entries = []
    for path in sorted(course_dir.iterdir(), key=lambda p: p.name):
        if not path.is_file():
            continue
        entry = _file_entry(path, course_dir, root)
        if entry is not None:
            root_entries.append(entry)
    result["root_files"] = root_entries

    return result


def filter_newer(course_data: dict, root: Path, cutoff_ns: int) -> dict:
    """Return a new catalog dict keeping only entries newer than cutoff_ns."""
    def is_newer(entry: dict) -> bool:
        try:
            return (root / entry["path"]).stat().st_mtime_ns > cutoff_ns
        except OSError:
            return False

    transcripts = [entry for entry in course_data["transcripts"] if is_newer(entry)]
    folders = {
        name: kept
        for name, entries in course_data["folders"].items()
        if (kept := [entry for entry in entries if is_newer(entry)])
    }
    root_files = [entry for entry in course_data["root_files"] if is_newer(entry)]
    return {
        "course": course_data["course"],
        "transcripts": transcripts,
        "folders": folders,
        "root_files": root_files,
    }


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


def _resolve_note(arg: str, root: Path) -> Path | None:
    """Resolve a note path argument to an absolute Path, or None if not a file."""
    p = Path(arg).expanduser()
    if not p.is_absolute():
        candidate = root / p
        if candidate.exists():
            p = candidate
        else:
            p = Path.cwd() / p
    if p.is_file():
        return p
    return None


def cmd_catalog(args: argparse.Namespace, root: Path) -> int:
    """Execute the catalog subcommand."""
    note_path = None
    newer_than_info = None
    course_arg = args.course

    if args.newer_than is not None:
        note_path = _resolve_note(args.newer_than, root)
        if note_path is None:
            print(f"error: note not found: {args.newer_than}", file=sys.stderr)
            return 2
        # Determine course if not provided
        if course_arg is None:
            try:
                rel = note_path.resolve().relative_to(root.resolve())
            except ValueError:
                print(
                    f"error: note {args.newer_than} is not inside a course folder; pass --course",
                    file=sys.stderr,
                )
                return 2
            parts = rel.parts
            if len(parts) < 2:
                print(
                    f"error: note {args.newer_than} is not inside a course folder; pass --course",
                    file=sys.stderr,
                )
                return 2
            course_arg = parts[0]
        cutoff_ns = note_path.stat().st_mtime_ns
        # Display path: POSIX relative to root.resolve() when under it, else str(p)
        try:
            display_path = note_path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            display_path = str(note_path)
        modified_stamp = datetime.fromtimestamp(note_path.stat().st_mtime).isoformat(timespec="minutes")
        newer_than_info = {"path": display_path, "modified": modified_stamp}
    else:
        cutoff_ns = None

    selected = select_courses(root, course_arg, catalog=True)
    if selected is None:
        return 2

    course_data_list = []
    for name in sorted(selected):
        course_dir = selected[name]
        course_data = catalog_course(name, course_dir, root)
        if cutoff_ns is not None:
            course_data = filter_newer(course_data, root, cutoff_ns)
        course_data_list.append(course_data)

    if args.json:
        output = {"courses": course_data_list}
        if newer_than_info is not None:
            output["newer_than"] = newer_than_info
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    if newer_than_info is not None:
        print(f'newer than {newer_than_info["path"]} (modified {newer_than_info["modified"]}):')
        print()

    for i, course_data in enumerate(course_data_list):
        if i > 0:
            print()
        _print_catalog_block(course_data)
        # Check if this course block is empty (no transcripts, no folders, no root_files)
        if newer_than_info is not None:
            has_content = (
                course_data["transcripts"]
                or course_data["folders"]
                or course_data["root_files"]
            )
            if not has_content:
                print("nothing newer")

    print()
    print(
        "readings and textbook text: Tools/readings/<course>/<path>.md; "
        "search with --in readings or --in textbooks"
    )
    return 0
