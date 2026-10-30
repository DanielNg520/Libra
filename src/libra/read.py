"""Cached page reads with an optional capped Gemini fetch, for `libra read` (ported from SemAI's study socket)."""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable

from libra.config import Settings
from libra.courses import canonical_course_code
from libra.gemini import GeminiCapError
from libra.lecture_docs import READS_DIR, pdf_page_count, sha256_file
from libra.source_pages import MAX_FETCH_PAGES, cached_pages, missing_entries
from libra.sources import SourceFile, course_dir, index_lock, list_sources, load_index, read_sources, reconcile_index
from libra.textbooks import BOOKS_DIR, BookEntry, load_cached_map, locate, page_labels, pdf_page_texts

READ_BUDGET_S: float = 900.0


_PART_SUFFIX_RE = re.compile(r" \(part \d+/\d+\)$")


class ReadError(Exception):
    def __init__(self, code: str, *, chapters: Sequence[str] = ()) -> None:
        self.code = code
        self.chapters = tuple(chapters)
        super().__init__(code)


def find_chapter(entries: Sequence[BookEntry], query: str) -> tuple[str, int, int]:
    merged: list[tuple[str, int, int]] = []
    for entry in entries:
        base = _PART_SUFFIX_RE.sub("", entry.title)
        if merged and merged[-1][0] == base:
            title, start, _ = merged[-1]
            merged[-1] = (title, start, entry.last)
        else:
            merged.append((base, entry.first, entry.last))
    stripped = query.strip()
    if stripped.isdigit():
        index = int(stripped)
        non_appendix = [item for item in merged if not item[0].casefold().startswith("appendix")]
        if 1 <= index <= len(non_appendix):
            return non_appendix[index - 1]
        raise ReadError("unknown_chapter", chapters=[title for title, _, _ in merged])
    needle = stripped.casefold()
    matches = [item for item in merged if needle in item[0].casefold()]
    if not matches:
        raise ReadError("unknown_chapter", chapters=[title for title, _, _ in merged])
    if len(matches) == 1:
        return matches[0]
    exact = [item for item in matches if item[0].casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    raise ReadError("ambiguous_chapter", chapters=[title for title, _, _ in matches])


def _resolve_chapter_pages(settings: Settings, source: SourceFile, file_path: Path, query: str) -> tuple[str, int, int]:
    index_entry = load_index(settings).get(source.rel)
    if (
        isinstance(index_entry, list)
        and len(index_entry) == 4
        and index_entry[0] == source.size
        and index_entry[1] == source.mtime_ns
        and isinstance(index_entry[2], str)
        and index_entry[2]
    ):
        sha = index_entry[2]
    else:
        try:
            sha = sha256_file(file_path)
        except OSError:
            raise ReadError("unreadable_source") from None
    cache_file = settings.state_dir / READS_DIR / BOOKS_DIR / f"{sha}.json"
    book_map = load_cached_map(cache_file, file_path)
    if book_map is None or not book_map.usable:
        raise ReadError("no_chapter_map")
    return find_chapter(book_map.entries, query)


def _resolve_printed_pages(file_path: Path, printed: tuple[int, int], total: int) -> tuple[int, int]:
    try:
        texts = pdf_page_texts(file_path)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ReadError("unreadable_source") from None
    labels = page_labels(texts)
    located = [locate(labels, n, total) for n in printed]
    if any(page is None for page in located):
        raise ReadError("printed_page_unknown")
    first, last = located[0], located[1]
    if last < first:
        raise ReadError("printed_page_unknown")
    return first, last


def _answer(rel: str, pages: dict[int, str], first: int, last: int) -> dict[str, Any]:
    page_entries: list[dict[str, Any]] = []
    missing: list[int] = []
    for n in range(first, last + 1):
        if n in pages:
            page_entries.append({"page": n, "text": pages[n]})
        else:
            missing.append(n)
    return {"ok": True, "path": rel, "pages": page_entries, "missing": missing}


def read_pages(
    settings: Settings,
    course: str,
    path: str,
    *,
    first: int | None = None,
    last: int | None = None,
    chapter: str | None = None,
    printed: tuple[int, int] | None = None,
    fetch: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if not path or "#" in path:
        raise ReadError("invalid_path")
    selectors = sum(
        (
            first is not None or last is not None,
            chapter is not None,
            printed is not None,
        )
    )
    if selectors > 1 or (chapter is not None and not chapter.strip()) or (
        printed is not None and (printed[0] < 1 or printed[1] < printed[0])
    ):
        raise ReadError("invalid_pages")
    if (first is None) != (last is None) or (first is not None and first < 1) or (
        first is not None and last is not None and last < first
    ):
        raise ReadError("invalid_pages")
    code = canonical_course_code(course)
    try:
        course_dir(settings, code)
        sources = list_sources(settings, code)
    except ValueError:
        raise ReadError("course_folder_missing") from None

    source: SourceFile | None = None
    for candidate in sources:
        if candidate.rel == path:
            source = candidate
            break
    if source is None:
        raise ReadError("unknown_source")

    if source.kind != "doc" or Path(source.rel).suffix.lower() == ".pptx":
        raise ReadError("unsupported_source")

    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        raise ReadError("unreadable_source")
    try:
        total = pdf_page_count(vault / source.rel)
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ReadError("unreadable_source") from None

    extra: dict[str, Any] = {}
    if chapter is not None:
        chapter_title, first, last = _resolve_chapter_pages(settings, source, vault / source.rel, chapter)
        extra["chapter"] = {"title": chapter_title, "first": first, "last": last}
    elif printed is not None:
        first, last = _resolve_printed_pages(vault / source.rel, printed, total)
        extra["printed"] = {"first": printed[0], "last": printed[1]}
    elif first is None or last is None:
        first = 1
        last = total
    if last > total:
        raise ReadError("invalid_pages")

    pages = cached_pages(settings, source)
    answer = _answer(source.rel, pages, first, last)
    missing = answer["missing"]
    if missing and reconcile_index(settings, code, sources):
        pages = cached_pages(settings, source)
        answer = _answer(source.rel, pages, first, last)
        missing = answer["missing"]
    answer.update(extra)
    if not fetch or not missing:
        return answer

    if len(missing) > MAX_FETCH_PAGES:
        raise ReadError("too_many_pages")

    if not settings.gemini_api_key:
        raise ReadError("read_unavailable")

    with index_lock(settings):
        fetched = cached_pages(settings, source)
        still_missing = [page for page in missing if page not in fetched]
        if still_missing:
            entries = missing_entries(source.rel, still_missing, total)
            try:
                outcome = read_sources(
                    settings, code, entries, deadline=clock() + READ_BUDGET_S
                )
            except GeminiCapError:
                raise ReadError("gemini_cap") from None
            failed = dict(outcome.failed)
            skipped = list(outcome.skipped)
        else:
            failed = {}
            skipped = []

    result = _answer(source.rel, cached_pages(settings, source), first, last)
    result.update(extra)
    result["failed"] = failed
    result["skipped"] = skipped
    return result
