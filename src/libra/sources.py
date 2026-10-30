"""Source layer for on-demand study-notes: list course files and read chosen ones lazily."""

import fcntl
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from libra.config import Settings
from libra.library import OUTDATED_DIR
from libra.gemini import GeminiCapError, GeminiError
from libra.lecture_docs import (
    READ_PROMPT,
    READS_DIR,
    TEXTBOOK_READ_PROMPT,
    TooManyPages,
    read_document,
    reading_key,
    render_pages,
    save_checkpoint,
    sha256_file,
)

log = logging.getLogger(__name__)

PHOTO_MODEL = "gemini-3.5-flash"
PHOTO_EFFORT = "medium"
DOC_EFFORT = "low"
INDEX_NAME = "source_index.json"
LOCK_NAME = "read.lock"
SLIDES_DIR = "Slides"
DISCUSSION_DIR = "Discussion"
HOMEWORK_DIR = "Homework"
TEXTBOOKS_DIR = "Textbooks"
READINGS_DIR = "Readings"
OWNER_NOTES_DIR = "Ask uploads"
TRANSCRIPTS_DIR = "Transcripts"
LECTURE_NOTES_DIR = "Lecture notes"
STUDY_NOTES_DIR = "Study notes"
AGENT_SCRATCH_DIR = "Agent scratch"

SOURCE_DIRS: tuple[str, ...] = (
    SLIDES_DIR,
    DISCUSSION_DIR,
    HOMEWORK_DIR,
    TEXTBOOKS_DIR,
    READINGS_DIR,
    OWNER_NOTES_DIR,
)
OUTPUT_DIRS: frozenset[str] = frozenset(
    {TRANSCRIPTS_DIR, LECTURE_NOTES_DIR, STUDY_NOTES_DIR, AGENT_SCRATCH_DIR}
)
NON_COURSE_DIRS: frozenset[str] = frozenset(
    {"Concepts", "Archive", "Academic Planning", "Personal"}
)


DOC_SUFFIXES = frozenset({".pdf", ".pptx"})
PHOTO_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
TEXT_SUFFIXES = frozenset({".md", ".txt"})


@dataclass(frozen=True, slots=True)
class SourceFile:
    rel: str
    kind: str
    size: int
    mtime_ns: int
    pages: tuple[int, int] | None = None
    label: str = ""

    @property
    def entry(self) -> str:
        if self.pages is None:
            return self.rel
        return f"{self.rel}#pages={self.pages[0]}-{self.pages[1]}"


@dataclass(frozen=True, slots=True)
class ReadOutcome:
    readings: dict[str, Path]
    skipped: list[str]
    failed: dict[str, str]


class _BudgetExceeded(Exception):
    pass


def course_dir(settings: Settings, course: str) -> Path:
    if settings.obsidian_academic_vault_dir is None:
        raise ValueError("Obsidian academic vault is not configured")
    if not course or course.startswith(".") or "/" in course or "\\" in course:
        raise ValueError(f"Invalid course name: {course!r}")
    if course in NON_COURSE_DIRS:
        raise ValueError(f"{course!r} is a non-course vault folder")
    vault = settings.obsidian_academic_vault_dir
    path = (vault / course).resolve()
    if path.parent != vault:
        raise ValueError(f"Course folder is not a direct child of the vault: {course}")
    if not path.is_dir():
        raise ValueError(f"Course folder is not a directory: {course}")
    return path


def source_roots(settings: Settings, course: str) -> list[Path]:
    """The course folder, resolved; every source lies under it."""
    return [course_dir(settings, course)]


def _source_file(path: Path, root: Path, vault: Path) -> SourceFile | None:
    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            return None
        st = path.stat()
    except OSError:
        log.debug("skipping unstatable file: %s", path)
        return None
    suffix = path.suffix.lower()
    if suffix in DOC_SUFFIXES:
        kind = "doc"
    elif suffix in PHOTO_SUFFIXES:
        kind = "photo"
    elif suffix in TEXT_SUFFIXES:
        kind = "text"
    elif suffix == "":
        try:
            with path.open("rb") as fh:
                kind = "doc" if fh.read(5) == b"%PDF-" else None
        except OSError:
            return None
    else:
        kind = None
    if kind is None:
        return None
    rel = resolved.relative_to(vault).as_posix()
    return SourceFile(rel=rel, kind=kind, size=st.st_size, mtime_ns=st.st_mtime_ns)


def list_sources(settings: Settings, course: str) -> list[SourceFile]:
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        raise ValueError("Obsidian academic vault is not configured")
    root = course_dir(settings, course)
    sources: list[SourceFile] = []
    for entry in sorted(root.iterdir()):
        if entry.name.startswith(".") or entry.name.startswith("~$"):
            continue
        if entry.is_dir():
            if entry.name in SOURCE_DIRS:
                try:
                    if entry.resolve().parent != root:
                        continue
                except OSError:
                    continue
                for dirpath, dirnames, filenames in os.walk(entry, followlinks=False):
                    dirnames[:] = sorted(
                        d
                        for d in dirnames
                        if not d.startswith(".")
                        and not d.startswith("~$")
                        and d not in OUTPUT_DIRS
                        and d != OUTDATED_DIR
                    )
                    for filename in sorted(filenames):
                        if filename.startswith(".") or filename.startswith("~$"):
                            continue
                        path = Path(dirpath) / filename
                        source = _source_file(path, root, vault)
                        if source is not None:
                            sources.append(source)
            elif entry.name not in OUTPUT_DIRS:
                try:
                    if any(entry.iterdir()):
                        log.warning(
                            "%s: folder %r is not a source folder; its files are ignored",
                            course,
                            entry.name,
                        )
                except OSError:
                    pass
        else:
            source = _source_file(entry, root, vault)
            if source is not None:
                sources.append(source)
    return sorted(sources, key=lambda s: s.rel)


ENTRY_RE = re.compile(r"^(.+)#pages=(\d+)-(\d+)$")


def split_entry(entry: str) -> tuple[str, tuple[int, int] | None]:
    if "#pages=" not in entry:
        return entry, None
    match = ENTRY_RE.fullmatch(entry)
    if match is None:
        raise ValueError(f"bad page range entry: {entry!r}")
    rel, first_s, last_s = match.groups()
    first = int(first_s)
    last = int(last_s)
    if first < 1 or first > last:
        raise ValueError(f"bad page range entry: {entry!r}")
    return rel, (first, last)


def load_index(settings: Settings) -> dict[str, list]:
    """Load the source index (entry -> [size, mtime_ns, sha, render_key]); empty on a missing or bad file."""
    path = settings.state_dir / READS_DIR / INDEX_NAME
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        log.warning("unreadable source index at %s", path)
        return {}
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("files"), dict):
        log.warning("malformed source index at %s", path)
        return {}
    return {rel: entry for rel, entry in raw["files"].items() if isinstance(entry, list) and len(entry) == 4}


def _key_for(kind: str, file_sha: str, path: Path, page_range: tuple[int, int] | None = None) -> tuple[str, list[tuple[str, bytes]] | None]:
    if kind == "photo":
        return hashlib.sha256(("photo\n" + file_sha).encode()).hexdigest(), None
    with tempfile.TemporaryDirectory() as tmpdir:
        pages = render_pages("doc", [path], Path(tmpdir), page_range=page_range)
    h = hashlib.sha256(b"render-v1\n")
    if page_range is not None:
        h.update(f"range {page_range[0]}-{page_range[1]}\n".encode())
    for _, png in pages:
        h.update(hashlib.sha256(png).digest())
    return h.hexdigest(), pages


def _resolve_key(
    source: SourceFile,
    path: Path,
    index: dict[str, list],
    deadline: float,
    clock: Callable[[], float],
) -> tuple[str, list[tuple[str, bytes]] | None, bool]:
    key = source.entry
    entry = index.get(key)
    if isinstance(entry, list) and len(entry) == 4 and entry[0] == source.size and entry[1] == source.mtime_ns and entry[3]:
        return str(entry[3]), None, False
    if clock() >= deadline:
        raise _BudgetExceeded
    file_sha = sha256_file(path)
    if isinstance(entry, list) and len(entry) == 4 and entry[2] == file_sha and entry[3]:
        if entry[0] != source.size or entry[1] != source.mtime_ns:
            index[key] = [source.size, source.mtime_ns, file_sha, entry[3]]
        return str(entry[3]), None, True
    render_key, pages = _key_for(source.kind, file_sha, path, source.pages)
    index[key] = [source.size, source.mtime_ns, file_sha, render_key]
    return render_key, pages, True


@contextmanager
def index_lock(settings: Settings) -> Iterator[None]:
    """Exclusive lock serialising index writers (`libra read` fetches and the readings export); not re-entrant within one process."""
    path = settings.state_dir / LOCK_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _rewrite_ranges(index: dict[str, list], old_prefix: str, new_prefix: str, size: int, mtime_ns: int) -> None:
    """Move range keys from old_prefix to new_prefix, updating size and mtime_ns."""
    for key in list(index):
        if key.startswith(old_prefix):
            suffix = key[len(old_prefix):]
            entry = index.pop(key)
            index[new_prefix + suffix] = [size, mtime_ns, entry[2], entry[3]]


def _adopt_moved(index: dict[str, list], course: str, sources: Collection[SourceFile], vault: Path) -> bool:
    """Adopt index entries for renamed or touched sources by content hash."""
    changed = False
    listed = {s.rel for s in sources}
    orphans = sorted(k for k in index if "#pages=" not in k and k.startswith(f"{course}/") and k not in listed)

    seen: set[str] = set()
    for source in sources:
        rel = source.rel
        if source.kind not in ("doc", "photo") or rel in seen:
            continue
        seen.add(rel)

        own = index.get(rel)
        if isinstance(own, list) and len(own) == 4 and own[0] == source.size and own[1] == source.mtime_ns:
            continue

        candidates: list[str] = []
        if isinstance(own, list) and len(own) == 4 and own[0] == source.size:
            candidates.append(rel)
        candidates.extend(k for k in orphans if index[k][0] == source.size)

        if not candidates:
            continue

        try:
            sha = sha256_file(vault / rel)
        except OSError:
            log.debug("could not hash %s", rel)
            continue

        adopted_from: str | None = None
        if rel in candidates and index[rel][2] == sha:
            old_render_key = index[rel][3]
            index[rel] = [source.size, source.mtime_ns, sha, old_render_key]
            _rewrite_ranges(index, f"{rel}#pages=", f"{rel}#pages=", source.size, source.mtime_ns)
            changed = True
            continue

        for orphan in orphans:
            if index[orphan][0] != source.size or index[orphan][2] != sha:
                continue
            adopted_from = orphan
            break

        if adopted_from is None:
            continue

        orphan_render_key = index[adopted_from][3]
        index[rel] = [source.size, source.mtime_ns, sha, orphan_render_key]
        _rewrite_ranges(index, f"{adopted_from}#pages=", f"{rel}#pages=", source.size, source.mtime_ns)
        index.pop(adopted_from, None)
        orphans.remove(adopted_from)
        log.info("adopted index entry %s -> %s", adopted_from, rel)
        changed = True

    return changed


def reconcile_index(settings: Settings, course: str, sources: Collection[SourceFile]) -> bool:
    """Reconcile the source index with current sources; callers must not already hold `index_lock`."""
    if settings.obsidian_academic_vault_dir is None:
        return False
    vault = settings.obsidian_academic_vault_dir
    with index_lock(settings):
        index = load_index(settings)
        changed = _adopt_moved(index, course, sources, vault)
        if changed:
            save_checkpoint(settings.state_dir / READS_DIR / INDEX_NAME, {"version": 1, "files": index})
        return changed


def _prune_index(index: dict[str, list], course: str, listed: Collection[str]) -> bool:
    pruned = False
    prefixes = (f"{course}/",)
    for rel in list(index):
        if rel.startswith(prefixes):
            bare = rel.split("#pages=", 1)[0]
            if bare not in listed:
                del index[rel]
                pruned = True
    return pruned


def read_sources(
    settings: Settings,
    course: str,
    rels: list[str],
    *,
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
    doc_model: str | None = None,
    doc_effort: str = DOC_EFFORT,
    photo_model: str = PHOTO_MODEL,
    photo_effort: str = PHOTO_EFFORT,
) -> ReadOutcome:
    roots = source_roots(settings, course)
    sources = {s.rel: s for s in list_sources(settings, course)}
    reads_dir = settings.state_dir / READS_DIR
    index = load_index(settings)
    index_changed = False
    if _adopt_moved(index, course, sources.values(), settings.obsidian_academic_vault_dir):
        index_changed = True
    readings: dict[str, Path] = {}
    skipped: list[str] = []
    failed: dict[str, str] = {}
    seen: set[str] = set()

    def on_batch() -> None:
        if clock() >= deadline:
            raise _BudgetExceeded

    try:
        for entry_str in rels:
            if entry_str in seen:
                continue
            seen.add(entry_str)
            try:
                rel, page_range = split_entry(entry_str)
            except ValueError as exc:
                failed[entry_str] = str(exc)
                continue
            base = sources.get(rel)
            if base is None:
                failed[entry_str] = f"not a source of {course}"
                continue
            if page_range is not None and base.kind != "doc":
                failed[entry_str] = "page range on a non-document"
                continue
            source = replace(base, pages=page_range)
            path = (settings.obsidian_academic_vault_dir / rel).resolve()
            if not any(path.is_relative_to(root) for root in roots):
                failed[entry_str] = "outside course folders"
                continue
            if source.kind == "text":
                readings[entry_str] = path
                continue
            try:
                render_key, pages, changed = _resolve_key(source, path, index, deadline, clock)
                if changed:
                    index_changed = True
                doc = source.kind == "doc"
                model = doc_model or settings.ocr_model if doc else photo_model
                effort = doc_effort if doc else photo_effort
                prompt_template = TEXTBOOK_READ_PROMPT if source.pages is not None else READ_PROMPT
                key = reading_key(render_key, model=model, effort=effort, prompt_template=prompt_template)
                if (reads_dir / f"{key}.md").exists():
                    readings[entry_str] = reads_dir / f"{key}.md"
                    continue
                if clock() >= deadline:
                    skipped.append(entry_str)
                    continue
                reading = read_document(
                    settings,
                    key=key,
                    course=course,
                    kind="doc" if doc else "photos",
                    paths=[entry_str],
                    sources=[path],
                    model=model,
                    effort=effort,
                    on_batch=on_batch,
                    pages=pages,
                    page_range=source.pages,
                    prompt_template=prompt_template,
                )
                readings[entry_str] = reading
            except _BudgetExceeded:
                skipped.append(entry_str)
            except GeminiCapError:
                raise
            except (TooManyPages, ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, GeminiError) as exc:
                failed[entry_str] = f"{type(exc).__name__}: {exc}"
    finally:
        if _prune_index(index, course, sources):
            index_changed = True
        if index_changed:
            save_checkpoint(
                reads_dir / INDEX_NAME,
                {"version": 1, "files": index},
            )
    return ReadOutcome(readings=readings, skipped=skipped, failed=failed)
