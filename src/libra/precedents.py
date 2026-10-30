"""Course precedents for `libra precedents`: posted solutions, then discussion, then lectures."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from libra.catalog import folder_entries
from libra.library import (
    Hit,
    PageHit,
    load_pages,
    load_transcripts,
    readings_dir,
    select_courses,
)
from libra.search import (
    parse_query,
    print_hit_json,
    print_hit_text,
    print_page_json,
    print_page_text,
    rank_hits,
    search,
    search_pages,
)

SOLUTION_TOKENS: frozenset[str] = frozenset(
    {"sol", "sols", "solution", "solutions", "key", "answer", "answers"}
)
TIERS: Tuple[str, ...] = ("solutions", "discussion", "lectures")

TRANSCRIPT_WINDOW = 4

_TIER_TABLE: Dict[str, Tuple[str, Optional[str]]] = {
    "solutions": ("Homework", None),
    "discussion": ("Discussion", "discussion"),
    "lectures": ("Slides", "lecture"),
}

_KIND_TO_TIER: Dict[str, str] = {
    kind: tier for tier, (_, kind) in _TIER_TABLE.items() if kind is not None
}


def is_solution_name(name: str) -> bool:
    """Return whether a file name marks a posted solution."""
    stem = Path(name).stem
    tokens = re.split(r"[^A-Za-z0-9]+", stem)
    lowered = {token.lower() for token in tokens if token}
    return bool(lowered & SOLUTION_TOKENS)


def tier_of(rel: str) -> Optional[str]:
    """Return a reading's tier, or None when it belongs to no tier."""
    parts = rel.split("/")
    if len(parts) < 2:
        return None
    folder = parts[1]
    if folder == "Homework":
        file_name = parts[-1]
        return "solutions" if is_solution_name(file_name) else None
    if folder == "Discussion":
        return "discussion"
    if folder == "Slides":
        return "lectures"
    return None


def _partition_hits(
    transcript_hits: List[Hit], page_hits: List[PageHit]
) -> Dict[str, List[Union[Hit, PageHit]]]:
    """Group hits per tier and rank each tier with rank_hits."""
    tier_transcript_hits: Dict[str, List[Hit]] = {
        tier: [] for tier in TIERS
    }
    tier_page_hits: Dict[str, List[PageHit]] = {
        tier: [] for tier in TIERS
    }
    for hit in transcript_hits:
        tier = _KIND_TO_TIER.get(hit.transcript.kind)
        if tier is not None:
            tier_transcript_hits[tier].append(hit)
    for hit in page_hits:
        tier = tier_of(hit.page.rel)
        if tier is not None:
            tier_page_hits[tier].append(hit)
    return {
        tier: rank_hits(tier_transcript_hits[tier], tier_page_hits[tier])
        for tier in TIERS
    }


def _unsearched_paths(root: Path, course_dir: Path, tier: str) -> List[str]:
    folder_name, _ = _TIER_TABLE[tier]
    folder = course_dir / folder_name
    if not folder.is_dir():
        return []
    entries = folder_entries(folder, course_dir, root)
    unsearched: List[str] = []
    for entry in entries:
        path = entry["path"]
        if tier == "solutions" and not is_solution_name(Path(path).name):
            continue
        exported = readings_dir(root) / (path + ".md")
        if not exported.exists():
            unsearched.append(path)
    return unsearched


def _print_tier_text(
    tier: str,
    rank: int,
    hits: List[Union[Hit, PageHit]],
    unsearched: List[str],
    context: int,
    limit: int,
) -> None:
    shown = hits[:limit]
    total = len(hits)
    header = f"## {rank} {tier.capitalize()}"
    if total:
        header += f" ({len(shown)} of {total})"
    print(header)
    if not shown:
        if not total:
            print("none found")
    else:
        for i, hit in enumerate(shown):
            if i:
                print()
            if isinstance(hit, Hit):
                print_hit_text(hit, context)
            else:
                print_page_text(hit, context)
    for path in unsearched:
        print(f"unsearched, read directly: {path}")


def _build_tier_json(
    tier: str,
    rank: int,
    hits: List[Union[Hit, PageHit]],
    unsearched: List[str],
    context: int,
    limit: int,
) -> Dict[str, Any]:
    shown = hits[:limit]
    hit_jsons = []
    for hit in shown:
        if isinstance(hit, Hit):
            hit_jsons.append(print_hit_json(hit, context))
        else:
            hit_jsons.append(print_page_json(hit, context))
    return {
        "tier": tier,
        "rank": rank,
        "total": len(hits),
        "hits": hit_jsons,
        "unsearched": unsearched,
    }


def cmd_precedents(args: argparse.Namespace, root: Path) -> int:
    """Print course precedents for `libra precedents`."""
    catalog = select_courses(root, args.course, catalog=False)
    if catalog is None:
        return 2
    course = next(iter(catalog))
    course_dir = catalog[course]

    terms = parse_query(args.terms)
    if not terms:
        print("error: empty query", file=sys.stderr)
        return 2
    if args.context < 0:
        print("error: --context must be at least 0", file=sys.stderr)
        return 2
    if args.limit < 1:
        print("error: --limit must be at least 1", file=sys.stderr)
        return 2

    transcripts = load_transcripts(course, course_dir, kind="all")
    pages = load_pages(root, course, {"readings"})
    transcript_hits = search(
        transcripts, terms, window=TRANSCRIPT_WINDOW, any_mode=not args.all_terms
    )
    page_hits = search_pages(pages, terms, any_mode=not args.all_terms)
    tier_hits = _partition_hits(transcript_hits, page_hits)

    unsearched_by_tier = {
        tier: _unsearched_paths(root, course_dir, tier) for tier in TIERS
    }

    if args.json:
        output: Dict[str, Any] = {
            "course": course,
            "terms": args.terms,
            "tiers": [
                _build_tier_json(
                    tier,
                    rank,
                    tier_hits[tier],
                    unsearched_by_tier[tier],
                    args.context,
                    args.limit,
                )
                for rank, tier in enumerate(TIERS, start=1)
            ],
        }
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        header = f"# Precedents · {course} · {' '.join(args.terms)}"
        print(header)
        print()
        for i, tier in enumerate(TIERS):
            if i:
                print()
            _print_tier_text(
                tier,
                i + 1,
                tier_hits[tier],
                unsearched_by_tier[tier],
                args.context,
                args.limit,
            )

    any_hits = any(tier_hits[tier] for tier in TIERS)
    if not any_hits:
        print("no precedent found; say so before explaining", file=sys.stderr)
        return 1
    return 0
