"""Cached page reads with an optional capped Gemini fetch, for `libra read` (ported from SemAI's study socket)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from libra.config import Settings
from libra.courses import canonical_course_code
from libra.gemini import GeminiCapError
from libra.lecture_docs import pdf_page_count
from libra.source_pages import MAX_FETCH_PAGES, cached_pages, missing_entries
from libra.sources import SourceFile, course_dir, index_lock, list_sources, read_sources

READ_BUDGET_S: float = 900.0


class ReadError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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
    fetch: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if not path or "#" in path:
        raise ReadError("invalid_path")
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

    if first is None or last is None:
        first = 1
        last = total
    elif last > total:
        raise ReadError("invalid_pages")

    pages = cached_pages(settings, source)
    answer = _answer(source.rel, pages, first, last)
    missing = answer["missing"]
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
    result["failed"] = failed
    result["skipped"] = skipped
    return result
