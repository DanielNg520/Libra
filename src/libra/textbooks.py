from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import statistics
import subprocess
import tempfile
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from libra.config import Settings
from libra.gemini import chat
from libra.lecture_docs import (
    READS_DIR,
    read_pages,
    render_pages,
    save_checkpoint,
)

log = logging.getLogger(__name__)

MAP_VERSION = 1
BOOKS_DIR = "books"
FRONT_PAGES = 60
FRONT_CHARS = 200_000
TITLE_PAGES = 12
ENTRY_MAX_PAGES = 60
GAP_PAGES = 10
GAP_RUN = 5
MIN_MEDIAN_WORDS = 50
LABEL_WINDOW = 20
MIN_VOTES = 3
MIN_AGREEMENT = 0.6
MAP_MODEL = "gemini-3.8-flash"
MAP_EFFORT = "low"
CALL_TIMEOUT_S = 300.0

CONTENTS_PROMPT = (
    'Below is the text layer of the first pages of a textbook PDF, each page headed `=== PDF page N ===`. '
    "From the table of contents, reply with ONLY a JSON object: "
    '{"title": str, "authors": str, "edition": str or null, "year": int or null, '
    '"chapters": [{"title": str, "start": int, "sections": [{"title": str, "start": int}]}], '
    '"index_start": int or null}. '
    "`start` values are the PRINTED page numbers shown in the contents (arabic numerals only), not PDF page numbers. "
    "Chapters include appendices; skip front matter (preface, contents, roman-numbered pages), bibliography and index. "
    "Sections are numbered first-level sections only, titles without their numbers. "
    "Edition and year come from the title or copyright page. "
    "index_start is the printed page of the book's index."
)

TITLE_PROMPT = (
    "These are the first pages of a scanned textbook. Reply with ONLY a JSON object: "
    '{"title": str, "authors": str, "edition": str or null, "year": int or null}, '
    "read from the cover, title, and copyright pages."
)

MAP_KEY: str = hashlib.sha256(
    "\n".join(
        [
            str(MAP_VERSION),
            MAP_MODEL,
            MAP_EFFORT,
            CONTENTS_PROMPT,
            TITLE_PROMPT,
        ]
    ).encode("utf-8")
).hexdigest()[:16]

UNUSABLE_RETRY_S = 7 * 24 * 3600


class BookMapError(ValueError):
    """Raised when a model reply cannot be parsed into a book map."""


@dataclass(frozen=True, slots=True)
class BookEntry:
    title: str
    first: int
    last: int
    sections: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BookMap:
    title: str
    authors: str
    edition: str | None
    year: int | None
    pages: int
    searchable: bool
    complete: bool
    entries: tuple[BookEntry, ...]
    built: bool = False

    @property
    def usable(self) -> bool:
        return bool(self.entries)


def pdf_page_texts(path: Path) -> list[str]:
    result = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(path), "-"],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    pages = result.stdout.split("\f")
    if pages and pages[-1] == "":
        pages.pop()
    return pages


def is_searchable(texts: list[str]) -> bool:
    if not texts:
        return False
    word_counts = [len(text.split()) for text in texts]
    return statistics.median(word_counts) >= MIN_MEDIAN_WORDS


def page_labels(texts: list[str]) -> list[tuple[int, int]]:
    pattern = re.compile(r"(?:This is page )?(\d{1,4})")
    candidates: list[tuple[int, int]] = []
    for i, text in enumerate(texts, start=1):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines[:3] + lines[-3:]:
            match = pattern.fullmatch(line)
            if not match:
                continue
            n = int(match.group(1))
            if n >= 1:
                candidates.append((i, n))
                break
    labels = [(i, n) for i, n in candidates if any(
        1 <= abs(j - i) <= 3 and j - m == i - n for j, m in candidates)]
    return labels


def locate(labels: list[tuple[int, int]], printed: int, pages: int) -> int | None:
    votes = [i - n for i, n in labels if printed <= n <= printed + LABEL_WINDOW]
    if len(votes) < MIN_VOTES:
        return None
    counts: dict[int, int] = {}
    for offset in votes:
        counts[offset] = counts.get(offset, 0) + 1
    max_count = max(counts.values())
    best_offsets = sorted(offset for offset, count in counts.items() if count == max_count)
    offset = best_offsets[0]
    if counts[offset] / len(votes) < MIN_AGREEMENT:
        return None
    result = printed + offset
    if not 1 <= result <= pages:
        return None
    return result


def build_entries(
    chapters: list[tuple[str, int, list[tuple[str, int]]]],
    index_page: int | None,
    pages: int,
) -> tuple[BookEntry, ...]:
    entries: list[BookEntry] = []
    kept: list[tuple[str, int, list[tuple[str, int]]]] = []
    last_start = 0
    for chapter in chapters:
        title, start, sections = chapter
        if start <= last_start:
            continue
        kept.append((title, start, sections))
        last_start = start

    for idx, (title, start, sections) in enumerate(kept):
        if idx + 1 < len(kept):
            end = kept[idx + 1][1] - 1
        elif index_page is not None and index_page > start:
            end = index_page - 1
        else:
            end = pages

        kept_sections = sorted(
            [(s_title, s_start) for s_title, s_start in sections if start < s_start <= end],
            key=lambda s: s[1],
        )
        parts: list[tuple[int, int]] = []
        cursor = start
        while end - cursor + 1 > ENTRY_MAX_PAGES:
            cuts = [s_start for _, s_start in kept_sections if cursor < s_start <= cursor + ENTRY_MAX_PAGES]
            if cuts:
                cut = max(cuts)
            else:
                cut = cursor + ENTRY_MAX_PAGES
            parts.append((cursor, cut - 1))
            cursor = cut
        parts.append((cursor, end))

        for part_idx, (first, last) in enumerate(parts, start=1):
            entry_title = title
            if len(parts) > 1:
                entry_title = f"{title} (part {part_idx}/{len(parts)})"
            entry_sections = tuple(
                s_title for s_title, s_start in kept_sections if first <= s_start <= last
            )
            entries.append(BookEntry(entry_title, first, last, entry_sections))
    return tuple(entries)


def has_gap(labels: list[tuple[int, int]]) -> bool:
    offsets: list[int] = []
    run: list[tuple[int, int]] = []
    for label in labels:
        if run and label[0] - label[1] != run[-1][0] - run[-1][1]:
            if len(run) >= GAP_RUN:
                offsets.append(run[-1][0] - run[-1][1])
            run = []
        run.append(label)
    if len(run) >= GAP_RUN:
        offsets.append(run[-1][0] - run[-1][1])
    for prev, curr in zip(offsets, offsets[1:]):
        if prev - curr > GAP_PAGES:
            return True
    return False


def normalize_title(title: str) -> str:
    lowered = title.lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    collapsed = " ".join(cleaned.split())
    if collapsed.startswith("the "):
        collapsed = collapsed[4:]
    return collapsed


# Backslashes that are not valid JSON escapes (e.g. LaTeX like \{, \%, x\_1).
_BAD_ESCAPE_RE = re.compile(
    r"""
    (?<!\\)            # not preceded by a backslash
    (?:\\\\)*          # consume already-escaped pair(s) of backslashes
    \\                 # a single backslash
    (?!
        ["\\/bfnrt]    # valid single-character JSON escape
        |
        u[0-9a-fA-F]{4}  # \uXXXX
    )
    """,
    re.VERBOSE,
)


def _parse_json_reply(reply: str) -> dict:
    stripped = reply.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as original_exc:
        if not original_exc.msg.startswith(("Invalid \\escape", "Invalid \\uXXXX escape")):
            raise BookMapError(f"Invalid JSON reply: {original_exc}") from original_exc

        def _escape_match(match: re.Match[str]) -> str:
            return match.group(0) + "\\"

        repaired = _BAD_ESCAPE_RE.sub(_escape_match, stripped)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            raise BookMapError(f"Invalid JSON reply: {original_exc}") from original_exc
        log.warning("repaired invalid JSON escapes in model reply")

    if not isinstance(data, dict):
        raise BookMapError("Reply is not a JSON object")
    return data


def _clean_metadata(data: dict, fallback_title: str) -> tuple[str, str, str | None, int | None]:
    title = data.get("title")
    if not isinstance(title, str) or not title:
        title = fallback_title
    authors = data.get("authors", "")
    if not isinstance(authors, str):
        authors = ""
    edition = data.get("edition")
    if not isinstance(edition, str) or not edition:
        edition = None
    year = data.get("year")
    if not isinstance(year, int):
        year = None
    return title, authors, edition, year


def load_cached_map(cache_file: Path, path: Path) -> BookMap | None:
    if not cache_file.exists():
        return None
    try:
        cached = json.loads(cache_file.read_text())
        if cached.get("version") != MAP_VERSION:
            raise KeyError("version")
        if cached.get("key") != MAP_KEY:
            raise KeyError("key")
        book_map = BookMap(
            title=cached["title"],
            authors=cached["authors"],
            edition=cached.get("edition"),
            year=cached.get("year"),
            pages=cached["pages"],
            searchable=cached["searchable"],
            complete=cached["complete"],
            entries=tuple(
                BookEntry(e["title"], e["first"], e["last"], tuple(e["sections"]))
                for e in cached["entries"]
            ),
        )
        if not book_map.entries and time.time() - cache_file.stat().st_mtime > UNUSABLE_RETRY_S:
            log.info("Unusable map for %s is older than 7 days; rebuilding", path)
            return None
        return book_map
    except (OSError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        log.warning("Unreadable or version-mismatched cache for %s; rebuilding", path)
        return None


def _save_map(cache_file: Path, book: BookMap) -> None:
    save_checkpoint(
        cache_file,
        {
            "version": MAP_VERSION,
            "key": MAP_KEY,
            "title": book.title,
            "authors": book.authors,
            "edition": book.edition,
            "year": book.year,
            "pages": book.pages,
            "searchable": book.searchable,
            "complete": book.complete,
            "entries": [
                {"title": e.title, "first": e.first, "last": e.last, "sections": list(e.sections)}
                for e in book.entries
            ],
        },
    )


def _front_prompt(texts: list[str]) -> str:
    front_blocks: list[str] = []
    total_chars = 0
    for i, text in enumerate(texts[:FRONT_PAGES], start=1):
        block = f"=== PDF page {i} ===\n{text}"
        if total_chars + len(block) > FRONT_CHARS:
            block = block[: FRONT_CHARS - total_chars]
            if block:
                front_blocks.append(block)
            break
        front_blocks.append(block)
        total_chars += len(block)
    return CONTENTS_PROMPT + "\n\n" + "\n\n".join(front_blocks)


def _parse_chapters(data: dict) -> list[tuple[str, int, list[tuple[str, int]]]]:
    raw_chapters = data.get("chapters", [])
    if not isinstance(raw_chapters, list):
        raw_chapters = []
    parsed_chapters: list[tuple[str, int, list[tuple[str, int]]]] = []
    for chapter in raw_chapters:
        if not isinstance(chapter, dict):
            continue
        c_title = chapter.get("title")
        c_start = chapter.get("start")
        if not isinstance(c_title, str) or not c_title or not isinstance(c_start, int):
            continue
        raw_sections = chapter.get("sections", [])
        if not isinstance(raw_sections, list):
            raw_sections = []
        sections: list[tuple[str, int]] = []
        for section in raw_sections:
            if not isinstance(section, dict):
                continue
            s_title = section.get("title")
            s_start = section.get("start")
            if isinstance(s_title, str) and s_title and isinstance(s_start, int):
                sections.append((s_title, s_start))
        parsed_chapters.append((c_title, c_start, sections))
    return parsed_chapters


def _locate_chapters(
    labels: list[tuple[int, int]],
    parsed: list[tuple[str, int, list[tuple[str, int]]]],
    pages: int,
) -> list[tuple[str, int, list[tuple[str, int]]]]:
    located_chapters: list[tuple[str, int, list[tuple[str, int]]]] = []
    for c_title, c_start, sections in parsed:
        located_start = locate(labels, c_start, pages)
        if located_start is None:
            continue
        located_sections: list[tuple[str, int]] = []
        for s_title, s_start in sections:
            located_section = locate(labels, s_start, pages)
            if located_section is not None:
                located_sections.append((s_title, located_section))
        located_chapters.append((c_title, located_start, located_sections))
    return located_chapters


def _locate_index(
    labels: list[tuple[int, int]],
    texts: list[str],
    index_start: int | None,
    pages: int,
) -> int | None:
    if index_start is None:
        return None
    candidate = locate(labels, index_start, pages)
    if candidate is None:
        return None
    lines = [line.strip() for line in texts[candidate - 1].splitlines() if line.strip()]
    if any("index" in line.lower() for line in lines[:5]):
        return candidate
    return None


def book_map(
    settings: Settings,
    path: Path,
    file_sha: str,
    *,
    chat_fn: Callable[..., str] = chat,
) -> BookMap:
    cache_file = settings.state_dir / READS_DIR / BOOKS_DIR / f"{file_sha}.json"
    cached = load_cached_map(cache_file, path)
    if cached is not None:
        return cached

    texts = pdf_page_texts(path)
    pages = len(texts)
    searchable = is_searchable(texts)

    if not searchable:
        with tempfile.TemporaryDirectory() as tmpdir:
            rendered = render_pages(
                "doc", [path], Path(tmpdir), page_range=(1, min(TITLE_PAGES, pages))
            )
            reply = read_pages(
                settings, TITLE_PROMPT, rendered, model=MAP_MODEL, effort=MAP_EFFORT
            )
        data = _parse_json_reply(reply)
        title, authors, edition, year = _clean_metadata(data, path.stem)
        book = BookMap(title, authors, edition, year, pages, False, False, (), built=True)
        _save_map(cache_file, book)
        log.info(
            "Built map for %s: title=%r, located 0/0 chapters, 0 entries, complete=False",
            path,
            title,
        )
        return book

    prompt = _front_prompt(texts)
    reply = chat_fn(
        [{"role": "user", "content": prompt}],
        MAP_MODEL,
        api_key=settings.gemini_api_key,
        reasoning_effort=MAP_EFFORT,
        timeout_s=CALL_TIMEOUT_S,
        json_mode=True,
    )
    data = _parse_json_reply(reply)
    title, authors, edition, year = _clean_metadata(data, path.stem)
    parsed_chapters = _parse_chapters(data)

    index_start = data.get("index_start")
    if not isinstance(index_start, int):
        index_start = None

    labels = page_labels(texts)
    located_chapters = _locate_chapters(labels, parsed_chapters, pages)
    located_index = _locate_index(labels, texts, index_start, pages)

    if located_index is not None and located_chapters:
        located_chapters = [
            (t, s, secs) for t, s, secs in located_chapters if s < located_index
        ]

    if parsed_chapters and len(located_chapters) < len(parsed_chapters) / 2:
        entries: tuple[BookEntry, ...] = ()
    else:
        entries = build_entries(located_chapters, located_index, pages)

    if index_start is not None:
        complete = located_index is not None and not has_gap(labels)
    else:
        complete = (
            bool(parsed_chapters)
            and locate(labels, parsed_chapters[-1][1], pages) is not None
            and not has_gap(labels)
        )

    book = BookMap(title, authors, edition, year, pages, True, complete, entries, built=True)
    _save_map(cache_file, book)
    log.info(
        "Built map for %s: title=%r, located %d/%d chapters, %d entries, complete=%s",
        path,
        title,
        len(located_chapters),
        len(parsed_chapters),
        len(entries),
        complete,
    )
    return book


def _normalize_authors(authors: str) -> str:
    lowered = authors.lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(cleaned.split())


def check_copies(
    settings: Settings,
    books: Mapping[str, BookMap],
    *,
    linked: Collection[str],
    delete: bool,
) -> list[str]:
    lines: list[str] = []
    groups: dict[tuple[str, str], list[tuple[str, BookMap]]] = {}
    for rel, book in books.items():
        key = (normalize_title(book.title), _normalize_authors(book.authors))
        groups.setdefault(key, []).append((rel, book))

    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(
            key=lambda item: (
                item[1].complete,
                item[1].searchable,
                _edition_number(item[1].edition),
                item[1].year or 0,
                item[1].pages,
            ),
            reverse=True,
        )
        winner_rel, winner = group[0]
        for loser_rel, loser in group[1:]:
            if not loser.complete:
                reason = "incomplete"
            elif not loser.searchable:
                reason = "not searchable"
            else:
                reason = "older or same edition"

            if reason == "older or same edition":
                outcome = "logged only"
            elif not delete:
                outcome = "report only"
            elif loser_rel in linked:
                outcome = "linked, kept"
            elif loser.built:
                outcome = "built this run, kept"
            elif not (winner.complete and winner.searchable):
                outcome = "winner unusable, kept"
            else:
                vault = settings.obsidian_academic_vault_dir
                if vault is None:
                    raise ValueError("obsidian_academic_vault_dir is not set")
                loser_path = (vault / loser_rel).resolve()
                from libra.sources import TEXTBOOKS_DIR  # local: sources imports this module
                if loser_path.parent.name != TEXTBOOKS_DIR or loser_path.parent.parent.parent != vault.resolve():
                    outcome = "outside Textbooks, kept"
                else:
                    try:
                        loser_path.unlink()
                        outcome = "deleted"
                    except OSError as exc:
                        outcome = f"delete failed: {exc}"

            line = f"{loser_rel}: {reason}; keep {winner_rel} ({outcome})"
            lines.append(line)
            log.warning(line)
    return lines


def _edition_number(edition: str | None) -> int:
    if not edition:
        return 0
    match = re.search(r"\d+", edition)
    return int(match.group()) if match else 0
