"""Transcript and reading search for `libra search` (ported from vault Tools/librarian.py)."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from datetime import date
from pathlib import Path
from typing import List, Tuple

from libra.catalog import _select_courses
from libra.library import (
    Hit,
    Page,
    PageHit,
    Term,
    Transcript,
    format_ts,
    load_pages,
    load_transcripts,
)


def parse_query(terms: List[str]) -> List[Term]:
    """Parse command-line terms into Term objects with compiled regexes."""
    joined = " ".join(terms)
    try:
        words = shlex.split(joined)
    except ValueError:
        words = joined.split()

    result = []
    for raw in words:
        if raw == "*":
            continue
        term_raw = raw
        trailing_star = term_raw.endswith("*") and not term_raw.endswith(r"\*")
        if trailing_star:
            term_raw = term_raw[:-1]
        if not term_raw:
            continue
        parts = term_raw.split()
        escaped = [re.escape(p) for p in parts]
        body = r"\s+".join(escaped)
        pattern = rf"(?<!\w){body}" + ("" if trailing_star else r"(?!\w)")
        result.append(
            Term(raw=raw, pattern=re.compile(pattern, re.IGNORECASE))
        )
    return result


def _window_texts(transcript: Transcript, window: int) -> List[Tuple[int, int, str]]:
    """Yield (first, last, joined_text) for sliding windows."""
    n = len(transcript.segments)
    if n == 0:
        return []
    windows = []
    for i in range(0, n, 1):
        last = min(i + window - 1, n - 1)
        text = " ".join(s.text for s in transcript.segments[i : last + 1])
        windows.append((i, last, text))
        if last == n - 1:
            break
    return windows


def _merge_spans(spans: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Merge overlapping or touching spans."""
    if not spans:
        return []
    spans.sort()
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(m) for m in merged]


def _trim_span(transcript: Transcript, terms: List[Term], first: int, last: int) -> Tuple[int, int]:
    """Trim leading and trailing segments that carry no matches."""
    segments = transcript.segments

    def has_match(idx: int) -> bool:
        if idx < first or idx > last:
            return False
        text = segments[idx].text
        for t in terms:
            if t.pattern.search(text):
                return True

        def spans_boundary(left_idx: int, right_idx: int) -> bool:
            left = segments[left_idx].text
            right = segments[right_idx].text
            joined = left + " " + right
            for t in terms:
                for m in t.pattern.finditer(joined):
                    if m.start() < len(left) and m.end() > len(left) + 1:
                        return True
            return False

        if idx - 1 >= first and spans_boundary(idx - 1, idx):
            return True
        if idx + 1 <= last and spans_boundary(idx, idx + 1):
            return True
        return False

    new_first = first
    while new_first < last and not has_match(new_first):
        new_first += 1
    new_last = last
    while new_last > new_first and not has_match(new_last):
        new_last -= 1
    return new_first, new_last


def _count_terms(text: str, terms: List[Term]) -> Tuple[int, int]:
    """Return (distinct terms matched, total non-overlapping occurrences)."""
    matched = 0
    occurrences = 0
    for t in terms:
        count = len(t.pattern.findall(text))
        if count > 0:
            matched += 1
            occurrences += count
    return matched, occurrences


def search(
    transcripts: List[Transcript],
    terms: List[Term],
    *,
    window: int = 4,
    any_mode: bool = False,
) -> List[Hit]:
    """Search transcripts and return ranked hits."""
    hits = []
    for transcript in transcripts:
        windows = _window_texts(transcript, window)
        qualifying = []
        for first, last, text in windows:
            if any_mode:
                ok = any(t.pattern.search(text) for t in terms)
            else:
                ok = all(t.pattern.search(text) for t in terms)
            if ok:
                qualifying.append((first, last))
        spans = _merge_spans(qualifying)
        for first, last in spans:
            new_first, new_last = _trim_span(transcript, terms, first, last)
            text = " ".join(
                s.text for s in transcript.segments[new_first : new_last + 1]
            )
            matched, occurrences = _count_terms(text, terms)
            hits.append(
                Hit(
                    transcript=transcript,
                    first=new_first,
                    last=new_last,
                    terms_matched=matched,
                    occurrences=occurrences,
                )
            )

    hits.sort(key=lambda h: h.transcript.course)
    hits.sort(key=lambda h: h.transcript.segments[h.first].start)
    hits.sort(key=lambda h: h.transcript.date, reverse=True)
    hits.sort(key=lambda h: h.occurrences, reverse=True)
    hits.sort(key=lambda h: h.terms_matched, reverse=True)
    return hits


def _print_hit_text(hit: Hit, context: int) -> None:
    """Print one hit in text format."""
    t = hit.transcript
    time_label = format_ts(t.segments[hit.first].start)
    kind_suffix = " (discussion)" if t.kind == "discussion" else ""
    header = f"{t.course} · {t.date.isoformat()}{kind_suffix} · [{time_label}]"
    print(header)

    first = max(0, hit.first - context)
    last = min(len(t.segments) - 1, hit.last + context)
    for i in range(first, last + 1):
        seg = t.segments[i]
        label = format_ts(seg.start)
        prefix = "> " if hit.first <= i <= hit.last else "  "
        print(f"{prefix}[{label}] {seg.text.strip()}")


def _print_hit_json(hit: Hit, context: int) -> dict:
    """Build the JSON-serializable dictionary for one hit."""
    t = hit.transcript
    first = max(0, hit.first - context)
    last = min(len(t.segments) - 1, hit.last + context)
    segments = []
    for i in range(first, last + 1):
        seg = t.segments[i]
        segments.append(
            {
                "start": seg.start,
                "label": format_ts(seg.start),
                "text": seg.text,
                "hit": hit.first <= i <= hit.last,
            }
        )
    return {
        "source": "transcript",
        "course": t.course,
        "date": t.date.isoformat(),
        "kind": t.kind,
        "start": t.segments[hit.first].start,
        "start_label": format_ts(t.segments[hit.first].start),
        "terms_matched": hit.terms_matched,
        "occurrences": hit.occurrences,
        "segments": segments,
    }


def search_pages(
    pages: List[Page], terms: List[Term], *, any_mode: bool = False
) -> List[PageHit]:
    hits = []
    for page in pages:
        if not page.lines:
            continue
        text = " ".join(page.lines)
        matched, occurrences = _count_terms(text, terms)
        if (any_mode and occurrences > 0) or (
            not any_mode and matched == len(terms)
        ):
            hit_lines = []
            for idx, line in enumerate(page.lines):
                if any(term.pattern.search(line) for term in terms):
                    hit_lines.append(idx)
                if len(hit_lines) == 3:
                    break
            if not hit_lines:
                hit_lines = [0]
            hits.append(
                PageHit(
                    page=page,
                    hit_lines=tuple(hit_lines),
                    terms_matched=matched,
                    occurrences=occurrences,
                )
            )
    return hits


def _page_line_range(hit: PageHit, context: int) -> List[Tuple[int, bool]]:
    ranges = []
    for idx in hit.hit_lines:
        ranges.append((max(0, idx - context), min(len(hit.page.lines) - 1, idx + context)))
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    result = []
    for start, end in merged:
        for idx in range(start, end + 1):
            result.append((idx, idx in hit.hit_lines))
    return result


def _print_page_text(hit: PageHit, context: int) -> None:
    page = hit.page
    suffix = " (textbook)" if page.kind == "textbook" else ""
    print(f"{page.course} · {page.rel} · p.{page.number}{suffix}")
    for idx, is_hit in _page_line_range(hit, context):
        prefix = "> " if is_hit else "  "
        print(f"{prefix}{page.lines[idx]}")


def _print_page_json(hit: PageHit, context: int) -> dict:
    lines = []
    for idx, is_hit in _page_line_range(hit, context):
        lines.append({"text": hit.page.lines[idx], "hit": is_hit})
    return {
        "source": "reading",
        "course": hit.page.course,
        "rel": hit.page.rel,
        "kind": hit.page.kind,
        "page": hit.page.number,
        "terms_matched": hit.terms_matched,
        "occurrences": hit.occurrences,
        "lines": lines,
    }


def _validate_date(value: str) -> date:
    """Validate a YYYY-MM-DD date argument."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date: {value}")


def cmd_search(args: argparse.Namespace, root: Path) -> int:
    """Execute the search subcommand."""
    courses = _select_courses(root, args.course, catalog=False)
    if courses is None:
        return 2

    terms = parse_query(list(args.terms))
    if not terms:
        print("error: empty query", file=sys.stderr)
        return 2

    since = args.since
    until = args.until

    if args.window < 1:
        print("error: --window must be at least 1", file=sys.stderr)
        return 2
    if args.context < 0:
        print("error: --context must be at least 0", file=sys.stderr)
        return 2
    if args.limit < 1:
        print("error: --limit must be at least 1", file=sys.stderr)
        return 2

    if args.scope is None:
        scope = {"transcripts", "readings"}
    elif "all" in args.scope:
        scope = {"transcripts", "readings", "textbooks"}
    else:
        scope = set(args.scope)

    transcripts = []
    if "transcripts" in scope:
        for name in sorted(courses):
            transcripts.extend(
                load_transcripts(
                    name,
                    courses[name],
                    since=since,
                    until=until,
                    kind=args.kind,
                )
            )

    transcript_hits = (
        search(
            transcripts,
            terms,
            window=args.window,
            any_mode=args.any_mode,
        )
        if transcripts
        else []
    )

    page_hits = []
    if "readings" in scope or "textbooks" in scope:
        pages = []
        for name in sorted(courses):
            pages.extend(load_pages(root, name, scope))
        page_hits = search_pages(pages, terms, any_mode=args.any_mode)

    combined = []
    combined.extend((h.terms_matched, h.occurrences, 0, i, h) for i, h in enumerate(transcript_hits))
    combined.extend((h.terms_matched, h.occurrences, 1, p, h) for p, h in enumerate(page_hits))
    combined.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    hits = [item[4] for item in combined]

    total = len(hits)
    limited = hits[: args.limit]

    if args.json:
        data = [
            _print_page_json(h, args.context) if isinstance(h, PageHit) else _print_hit_json(h, args.context)
            for h in limited
        ]
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        if total == 0:
            print("no matches", file=sys.stderr)
            return 1
        if total > args.limit:
            print(f"{args.limit} of {total} hits", file=sys.stderr)
        return 0

    if total == 0:
        print("no matches", file=sys.stderr)
        return 1

    for i, hit in enumerate(limited):
        if i > 0:
            print()
        if isinstance(hit, PageHit):
            _print_page_text(hit, args.context)
        else:
            _print_hit_text(hit, args.context)

    if total > args.limit:
        print(f"{args.limit} of {total} hits", file=sys.stderr)
    return 0
