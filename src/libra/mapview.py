"""Lecture map view and confirm for `libra map` (ported from vault Tools/librarian.py)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Union

from libra.library import format_ts, select_courses


def maps_dir(root: Path) -> Path:
    return root / "Tools" / "maps"


def load_map(root: Path, course: str) -> Optional[dict]:
    path = maps_dir(root) / f"{course}.json"
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        return None


def load_confirmed(root: Path, course: str) -> List[dict]:
    path = maps_dir(root) / f"{course}.confirmed.json"
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("confirmed", [])
        if not isinstance(entries, list):
            raise ValueError("confirmed is not a list")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("confirmed entry is not a dict")
        return entries
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, ValueError, KeyError, OSError) as e:
        print(f"warning: malformed confirmed file for {course}: {e}", file=sys.stderr)
        return []


def parse_time(value: str) -> float:
    parts = value.strip().split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise ValueError(f"invalid time: {value}")


def merge_map(map_data: dict, confirmed: List[dict]) -> dict:
    merged = json.loads(json.dumps(map_data))
    transcripts = merged.get("transcripts", [])
    if not isinstance(transcripts, list):
        return merged

    tx_by_id: Dict[str, dict] = {}
    for tx in transcripts:
        if isinstance(tx, dict) and "id" in tx:
            tx_by_id[tx["id"]] = tx

    deck_members: Dict[str, set] = {deck["rel"]: set() for deck in merged.get("decks", []) if isinstance(deck, dict) and "rel" in deck}

    for entry in confirmed:
        tx_id = entry.get("transcript")
        if tx_id not in tx_by_id:
            continue
        tx = tx_by_id[tx_id]
        deck = entry.get("deck")
        if not deck:
            continue
        spans = tx.get("spans")
        if not isinstance(spans, list):
            spans = []
            tx["spans"] = spans
        from_s = entry.get("from_s")
        to_s = entry.get("to_s")
        if from_s is None:
            from_s = 0.0
        if to_s is None:
            generated_to = [s.get("to_s", 0.0) for s in spans if isinstance(s, dict) and "to_s" in s]
            to_s = max(generated_to) if generated_to else 0.0
        new_spans = []
        for span in spans:
            if not isinstance(span, dict):
                new_spans.append(span)
                continue

            s_from = span.get("from_s", 0.0)
            s_to = span.get("to_s", 0.0)
            if s_to <= from_s or s_from >= to_s:
                new_spans.append(span)
                continue

            if s_from < from_s:
                left = dict(span)
                left["to_s"] = from_s
                new_spans.append(left)
            if s_to > to_s:
                right = dict(span)
                right["from_s"] = to_s
                new_spans.append(right)
        new_spans.append({"from_s": from_s, "to_s": to_s, "deck": deck, "status": "confirmed"})
        new_spans.sort(key=lambda s: s.get("from_s", 0.0) if isinstance(s, dict) else 0.0)
        tx["spans"] = new_spans

    for tx in transcripts:
        if not isinstance(tx, dict):
            continue
        tx_id = tx.get("id")
        tx_decks = set()
        for span in tx.get("spans", []):
            if isinstance(span, dict) and "deck" in span:
                tx_decks.add(span["deck"])
        for rel, members in deck_members.items():
            if rel in tx_decks:
                members.add(tx_id)

    for deck in merged.get("decks", []):
        if isinstance(deck, dict) and "rel" in deck:
            deck["transcripts"] = sorted(deck_members.get(deck["rel"], set()))
    return merged


def resolve_deck(map_data: dict, deck_arg: str) -> Optional[Union[str, List[str]]]:
    decks = map_data.get("decks", [])
    candidates = []
    for deck in decks:
        if not isinstance(deck, dict):
            continue
        rel = deck.get("rel")
        if rel == deck_arg or Path(rel).name == deck_arg:
            candidates.append(rel)
        for dup in deck.get("duplicates", []):
            if dup == deck_arg or Path(dup).name == deck_arg:
                candidates.append(rel)
    unique = sorted(set(candidates))
    if len(unique) == 1:
        return unique[0]
    if not unique:
        return None
    return unique


def _print_map_block(course: str, map_data: dict, root: Path) -> None:
    built = map_data.get("built", "")
    print(f"## {course}  (map built {built})")
    for tx in map_data.get("transcripts", []):
        if not isinstance(tx, dict):
            continue
        kind = tx.get("kind", "lecture")
        print(f"{tx.get('id', '')} {kind}")
        for span in tx.get("spans", []):
            if not isinstance(span, dict):
                continue
            from_s = span.get("from_s", 0.0)
            to_s = span.get("to_s", 0.0)
            deck = span.get("deck")
            if span.get("status") == "confirmed":
                if deck:
                    print(f"  {format_ts(from_s)}-{format_ts(to_s)}  {Path(deck).name}  confirmed")
                else:
                    print(f"  {format_ts(from_s)}-{format_ts(to_s)}  confirmed")
                continue
            if deck:
                pages = span.get("pages", [])
                page_str = f"p{min(pages)}-{max(pages)}" if pages else ""
                score = span.get("score", 0.0)
                terms = span.get("terms", [])[:5]
                term_str = ", ".join(terms) if terms else ""
                also = span.get("also", [])
                also_str = f" (also: {', '.join(Path(a).name for a in also)})" if also else ""
                status = span.get("status", "matched")
                print(f"  {format_ts(from_s)}-{format_ts(to_s)}  {Path(deck).name}  {page_str}  {score:.2f} {status}  {also_str} | {term_str}")
            else:
                candidate = span.get("candidate", "")
                score = span.get("score", 0.0)
                print(f"  {format_ts(from_s)}-{format_ts(to_s)}  (unmatched; best guess {Path(candidate).name if candidate else ''} {score:.2f})")
    print("Decks -> chapters")
    for deck in map_data.get("decks", []):
        if not isinstance(deck, dict):
            continue
        rel = deck.get("rel", "")
        chapters = deck.get("chapters", [])
        chapter_strs = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            book = chapter.get("book", "")
            title = chapter.get("title", "")
            first = chapter.get("first", 0)
            last = chapter.get("last", 0)
            score = chapter.get("score", 0.0)
            book_name = Path(book).name[:40]
            chapter_strs.append(f'{book_name[:40]}: "{title}" pp {first}-{last} ({score:.2f})')
        if chapter_strs:
            print(f"  {Path(rel).name}: {'; '.join(chapter_strs)}")


def cmd_map(args: argparse.Namespace, root: Path) -> int:
    selected = select_courses(root, args.course, catalog=False)
    if selected is None:
        return 2
    if args.confirm:
        if not args.course:
            print("error: --course is required with --confirm", file=sys.stderr)
            return 2
        return _confirm(args, root, selected)
    found_any = False
    results = []
    for course in sorted(selected):
        map_data = load_map(root, course)
        if map_data is None:
            print(f"no map yet for {course}; Fedora builds it after the next transcript fetch", file=sys.stderr)
            continue
        confirmed = load_confirmed(root, course)
        merged = merge_map(map_data, confirmed)
        if args.date:
            date_str = args.date.isoformat()
            kept = [tx for tx in merged.get("transcripts", []) if isinstance(tx, dict) and tx.get("id", "").startswith(date_str)]
            merged["transcripts"] = kept
            kept_decks = {span.get("deck") for tx in kept for span in tx.get("spans", []) if isinstance(span, dict)}
            merged["decks"] = [d for d in merged.get("decks", []) if isinstance(d, dict) and d.get("rel") in kept_decks]
        found_any = True
        results.append(merged)
        if not args.json:
            _print_map_block(course, merged, root)
            print()
    if not found_any:
        return 1
    if args.json:
        print(json.dumps({"courses": results}, indent=2, ensure_ascii=False))
    else:
        print("confirm or correct: python3 Tools/librarian.py map --confirm --course '<course>' --transcript <id> --deck <deck> [--from MM:SS --to MM:SS]")
    return 0


def _confirm(args: argparse.Namespace, root: Path, selected: dict) -> int:
    course = args.course
    map_data = load_map(root, course)
    if map_data is None:
        print(f"no map yet for {course}; Fedora builds it after the next transcript fetch", file=sys.stderr)
        return 2
    transcript_ids = [tx.get("id") for tx in map_data.get("transcripts", []) if isinstance(tx, dict) and "id" in tx]
    if args.transcript not in transcript_ids:
        print(f"error: transcript {args.transcript} not found in map for {course}", file=sys.stderr)
        return 2
    deck = resolve_deck(map_data, args.deck)
    if deck is None:
        print(f"error: deck {args.deck} not found", file=sys.stderr)
        return 2
    if isinstance(deck, list):
        print(f"error: deck {args.deck} is ambiguous: {', '.join(deck)}", file=sys.stderr)
        return 2
    try:
        from_s = parse_time(args.from_t) if args.from_t else None
        to_s = parse_time(args.to_t) if args.to_t else None
    except ValueError:
        print("error: invalid time (use MM:SS, H:MM:SS or seconds)", file=sys.stderr)
        return 2
    if from_s is not None and to_s is not None and from_s > to_s:
        print("error: --from must be <= --to", file=sys.stderr)
        return 2
    confirmed = load_confirmed(root, course)
    for entry in confirmed:
        if entry.get("transcript") == args.transcript and entry.get("deck") == deck and entry.get("from_s") == from_s and entry.get("to_s") == to_s:
            print(f"confirmed {args.transcript} {from_s}-{to_s} -> {deck}")
            return 0
    new_entry = {"transcript": args.transcript, "deck": deck}
    if from_s is not None:
        new_entry["from_s"] = from_s
    if to_s is not None:
        new_entry["to_s"] = to_s
    confirmed.append(new_entry)
    confirmed.sort(key=lambda e: (e.get("transcript", ""), e.get("from_s", 0.0) if e.get("from_s") is not None else 0.0))
    path = maps_dir(root) / f"{course}.confirmed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump({"version": 1, "confirmed": confirmed}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, path)
    print(f"confirmed {args.transcript} {from_s}-{to_s} -> {deck}")
    return 0
