"""Per-page view of cached source readings for the study socket `read` route (ADR-0039 S4)."""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from libra.config import Settings
from libra.sources import DOC_EFFORT, SourceFile, load_index, split_entry
from libra.lecture_docs import (
    READ_PROMPT,
    READS_DIR,
    TEXTBOOK_READ_PROMPT,
    reading_key,
)

log = logging.getLogger(__name__)

MAX_FETCH_PAGES: int = 25


def page_sections(text: str) -> dict[int, str]:
    """Page number -> text under each `### Page N` heading; text before the first heading is dropped."""
    pages: dict[int, str] = {}
    current_page: int | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^### Page (\d+)\s*$", line)
        if match:
            if current_page is not None:
                pages[current_page] = "\n".join(buffer).strip("\n")
            current_page = int(match.group(1))
            buffer = []
        elif current_page is not None:
            buffer.append(line)
    if current_page is not None:
        pages[current_page] = "\n".join(buffer).strip("\n")
    return pages


def cached_pages(settings: Settings, source: SourceFile) -> dict[int, str]:
    """Page number -> text from every cached reading of `source.rel`."""
    index = load_index(settings)
    considered: list[tuple[int, str, str, bool]] = []
    for entry, item in index.items():
        try:
            rel, pages = split_entry(entry)
        except ValueError:
            continue
        if rel != source.rel:
            continue
        if not isinstance(item, list) or len(item) != 4:
            continue
        size, mtime_ns, _sha, render_key = item
        if size != source.size or mtime_ns != source.mtime_ns:
            continue
        if not isinstance(render_key, str) or not render_key:
            continue
        first = pages[0] if pages is not None else 0
        considered.append((first, entry, render_key, pages is not None))

    considered.sort(key=lambda x: x[0])

    result: dict[int, str] = {}
    for first, entry, render_key, is_range in considered:
        prompt_template = TEXTBOOK_READ_PROMPT if is_range else READ_PROMPT
        key = reading_key(
            render_key,
            model=settings.ocr_model,
            effort=DOC_EFFORT,
            prompt_template=prompt_template,
        )
        path = settings.state_dir / READS_DIR / f"{key}.md"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            log.debug("cached reading skipped for %s", entry)
            continue
        for page, section in page_sections(text).items():
            if page not in result:
                result[page] = section

    return result


def missing_entries(rel: str, missing: Sequence[int], total: int) -> list[str]:
    """`read_sources` entries that cover the `missing` pages of a `total`-page document."""
    pages = sorted(set(missing))
    if total >= 1 and pages == list(range(1, total + 1)):
        return [rel]
    if not pages:
        return []

    entries: list[str] = []
    run_start = pages[0]
    run_end = pages[0]
    for page in pages[1:]:
        if page == run_end + 1:
            run_end = page
        else:
            entries.append(f"{rel}#pages={run_start}-{run_end}")
            run_start = page
            run_end = page
    entries.append(f"{rel}#pages={run_start}-{run_end}")
    return entries
