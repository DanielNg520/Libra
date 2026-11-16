"""Closed-world lesson kinds: fact_ledger (taught before used) and cold_read (fresh-reader record), ADR-0047."""
from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from libra.study.frontmatter import FrontmatterError, load
from libra.study.check_concepts import fence_mask
from libra.study.render import scan_blocks

if TYPE_CHECKING:
    from libra.study.check_kinds import Finding, Lesson

__all__ = [
    "DEFAULT_MARKERS",
    "cold_read",
    "cold_read_digest",
    "cold_read_validate",
    "fact_ledger",
    "fact_ledger_validate",
    "record_relpath",
]

DEFAULT_MARKERS: tuple[str, ...] = (
    "Proof:",
    "Why:",
    "Definition.",
    "Axiom.",
    "Stated without proof.",
)

_ANCHOR_RE = re.compile(r"^(?:#{1,6} |\*\*)")
_FACT_RE = re.compile(r"^- \*\*(?P<name>[^*]+?):\*\*\s+(?P<rest>.*)$")
_PREREQ_RE = re.compile(r"^\[\[([^|\]]+)(?:\|[^\]]+)?\]\]$")
_USES_RE = re.compile(r"^- Uses:(?P<names>.*)$")
_ANSWER_USES_RE = re.compile(r"^>\s*Uses:(?P<names>.*)$")


@dataclass(frozen=True)
class _Note:
    frontmatter: Mapping[str, object]
    body: tuple[str, ...]


def _load_note(vault: Path, rel: str, cache: dict[str, _Note | None]) -> _Note | None:
    if rel in cache:
        return cache[rel]
    try:
        text = (vault / rel).read_text(encoding="utf-8")
        fm, body_text = load(text)
    except (OSError, UnicodeDecodeError, FrontmatterError):
        cache[rel] = None
        return None
    note = _Note(frontmatter=fm, body=tuple(body_text.split("\n")))
    cache[rel] = note
    return note


def _resolve(vault: Path, target: str) -> str | None:
    target = target.strip()
    if "#" in target:
        target = target.split("#", 1)[0]
    if not target or target.startswith("/") or ".." in PurePosixPath(target).parts:
        return None
    p = PurePosixPath(target)
    if not p.suffix:
        p = p.with_suffix(".md")
    rel = p.as_posix()
    if not rel.endswith(".md"):
        return None
    return rel if (vault / rel).is_file() else None


def _prereq_targets(frontmatter: Mapping[str, object]) -> list[str]:
    prereqs = frontmatter.get("prereqs")
    if not isinstance(prereqs, list):
        return []
    targets: list[str] = []
    for entry in prereqs:
        if isinstance(entry, str):
            m = _PREREQ_RE.match(entry)
            if m:
                targets.append(m.group(1))
    return targets


def _targets(note: _Note) -> list[str]:
    embeds = scan_blocks(note.body).embeds
    targets = [e.target for e in embeds]
    targets.extend(_prereq_targets(note.frontmatter))
    return targets


def _facts(body: Sequence[str], mask: Sequence[bool], sections: tuple[re.Pattern[str], ...]) -> list[tuple[int, str, str, str]]:
    anchor_idx: list[int] = []
    for i, line in enumerate(body):
        if not mask[i] and _ANCHOR_RE.match(line):
            anchor_idx.append(i)

    def nearest_anchor(i: int) -> int | None:
        best = None
        for a in anchor_idx:
            if a < i:
                best = a
            else:
                break
        return best

    facts: list[tuple[int, str, str, str]] = []
    for i, line in enumerate(body):
        if mask[i]:
            continue
        m = _FACT_RE.match(line)
        if not m:
            continue
        anchor = nearest_anchor(i)
        if anchor is None or not any(s.match(body[anchor]) for s in sections):
            continue
        name = m.group("name").strip()
        key = name.casefold()
        text_lines = [m.group("rest")]
        j = i + 1
        while j < len(body) and body[j].strip() and (body[j].startswith(" ") or body[j].startswith("\t")):
            text_lines.append(body[j])
            j += 1
        facts.append((i, name, key, " ".join(text_lines)))
    return facts


def _example_end(
    body: Sequence[str],
    mask: Sequence[bool],
    start: int,
    example_re: re.Pattern[str],
    answer_prefix: str,
) -> tuple[int | None, int]:
    for i in range(start + 1, len(body)):
        if mask[i]:
            continue
        line = body[i]
        if _USES_RE.match(line):
            return i, i + 1
        if (
            re.match(r"^#{1,6} ", line)
            or line.strip().startswith("![[")
            or example_re.match(line)
            or line.startswith(answer_prefix)
        ):
            return None, i
    return None, len(body)


def _uses_names(captured: str) -> list[str] | None:
    text = captured.strip()
    if text.endswith("."):
        text = text[:-1]
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return None
    casefolded = [p.casefold() for p in parts]
    if "none" in casefolded:
        return [] if len(parts) == 1 else None
    return parts


def _uses_sites(
    body: Sequence[str],
    mask: Sequence[bool],
    example_re: re.Pattern[str],
    answer_prefix: str,
) -> tuple[list[tuple[int, list[str]]], list[tuple[int, str]]]:
    sites: list[tuple[int, list[str]]] = []
    problems: list[tuple[int, str]] = []

    i = 0
    while i < len(body):
        if not mask[i] and example_re.match(body[i]):
            uses_idx, resume = _example_end(body, mask, i, example_re, answer_prefix)
            if uses_idx is None:
                problems.append((i, "fact_ledger: worked example without a final Uses line"))
            elif uses_idx + 1 < len(body) and body[uses_idx + 1].strip():
                problems.append((i, "fact_ledger: worked example without a final Uses line"))
            else:
                m = _USES_RE.match(body[uses_idx])
                names = _uses_names(m.group("names"))
                if names is None:
                    problems.append(
                        (
                            uses_idx,
                            "fact_ledger: Uses line lists no names"
                            if not m.group("names").strip()
                            else "fact_ledger: Uses line mixes none with names",
                        )
                    )
                else:
                    sites.append((uses_idx, names))
            i = resume
        else:
            i += 1

    i = 0
    while i < len(body):
        if not mask[i] and body[i].startswith(answer_prefix):
            start = i
            j = i
            while j < len(body) and body[j].startswith(">"):
                j += 1
            last = j - 1
            m = _ANSWER_USES_RE.match(body[last])
            if not m:
                problems.append((start, "fact_ledger: answer without a final Uses line"))
            else:
                names = _uses_names(m.group("names"))
                if names is None:
                    problems.append((last, "fact_ledger: Uses line lists no names" if not m.group("names").strip() else "fact_ledger: Uses line mixes none with names"))
                else:
                    sites.append((last, names))
            i = j
        else:
            i += 1
    return sites, problems


def _closure(vault: Path, seeds: Sequence[str], skip: str, cache: dict[str, _Note | None]) -> tuple[list[str], list[str]]:
    visited_order: list[str] = []
    unreadable: list[str] = []
    seen: set[str] = set()
    queue: deque[str] = deque()
    for seed in seeds:
        rel = _resolve(vault, seed)
        if rel and rel != skip and rel not in seen:
            seen.add(rel)
            queue.append(rel)
    while queue:
        rel = queue.popleft()
        note = _load_note(vault, rel, cache)
        if note is None:
            unreadable.append(rel)
            continue
        visited_order.append(rel)
        for seed in _targets(note):
            child = _resolve(vault, seed)
            if child and child != skip and child not in seen:
                seen.add(child)
                queue.append(child)
    return visited_order, unreadable


def _embed_order(vault: Path, lesson: Lesson, body: Sequence[str], prereq_targets: list[str], cache: dict[str, _Note | None]) -> list[tuple[int, str]]:
    prereq_seeds = [t for t in prereq_targets if _resolve(vault, t)]
    reachable, _ = _closure(vault, prereq_seeds, lesson.rel, cache)
    reachable_set = set(reachable)
    embeds = scan_blocks(tuple(body)).embeds
    earlier: set[str] = set()
    findings: list[tuple[int, str]] = []
    for embed in embeds:
        e_rel = _resolve(vault, embed.target)
        if e_rel is None:
            continue
        note = _load_note(vault, e_rel, cache)
        if note is not None:
            for p_target in _prereq_targets(note.frontmatter):
                p_rel = _resolve(vault, p_target)
                if p_rel is None:
                    continue
                if p_rel not in earlier and p_rel not in reachable_set and p_rel != lesson.rel:
                    findings.append((embed.line, f"fact_ledger: {e_rel} needs {p_rel}, not embedded earlier or reachable from prereqs"))
        earlier.add(e_rel)
    return findings


def fact_ledger(lesson: Lesson, params: Mapping[str, object], vault: Path) -> list[Finding]:
    sections_raw = params["sections"]
    if not isinstance(sections_raw, list):
        return []
    sections = tuple(re.compile(s) for s in sections_raw if isinstance(s, str))
    assumed = [str(s).strip().casefold() for s in params.get("assumed", [])] if isinstance(params.get("assumed", []), list) else []
    markers = tuple(str(m) for m in params.get("markers", DEFAULT_MARKERS)) if isinstance(params.get("markers", DEFAULT_MARKERS), list) else DEFAULT_MARKERS
    example_raw = params.get("example", r"^\*\*Worked example")
    example_re = re.compile(example_raw) if isinstance(example_raw, str) else re.compile(r"^\*\*Worked example")
    answer_prefix = str(params.get("answer", "> [!success]-"))

    body = lesson.body()
    mask = fence_mask(body)
    facts = _facts(body, mask, sections)
    cache: dict[str, _Note | None] = {}

    findings: list[Finding] = []
    seen: dict[str, int] = {}
    for idx, name, key, text in facts:
        if key in seen:
            findings.append((lesson.lineno(idx), f"fact_ledger: fact {name!r} labelled twice"))
        else:
            seen[key] = idx
        if not any(marker in text for marker in markers):
            findings.append((lesson.lineno(idx), f"fact_ledger: fact {name!r} has no justification marker"))

    sites, problems = _uses_sites(body, mask, example_re, answer_prefix)
    findings.extend((lesson.lineno(i), msg) for i, msg in problems)
    min_sites = params.get("min_sites", 0)
    if not isinstance(min_sites, int) or isinstance(min_sites, bool):
        min_sites = 0
    total_sites = len(sites) + len(problems)
    if total_sites < min_sites:
        findings.append(
            (
                None,
                f"fact_ledger: {total_sites} worked examples or answers with a Uses line, needs at least {min_sites}",
            )
        )
    sites.sort(key=lambda s: s[0])

    prereq_targets = _prereq_targets(lesson.frontmatter)
    embeds = scan_blocks(tuple(body)).embeds
    embed_targets = [e.target for e in embeds]
    visited, unreadable = _closure(vault, prereq_targets + embed_targets, lesson.rel, cache)
    closure_keys: set[str] = set()
    for rel in visited:
        note = _load_note(vault, rel, cache)
        if note is None:
            continue
        for _, _, key, _ in _facts(note.body, fence_mask(note.body), sections):
            closure_keys.add(key)
    for rel in unreadable:
        findings.append((None, f"fact_ledger: cannot read {rel}"))

    for site_idx, names in sites:
        for name in names:
            key = name.strip().casefold()
            if key in seen and seen[key] >= site_idx:
                findings.append((lesson.lineno(site_idx), f"fact_ledger: {name!r} used before it is labelled"))
            elif key in seen or key in closure_keys or key in assumed:
                continue
            else:
                findings.append((lesson.lineno(site_idx), f"fact_ledger: {name!r} used but not taught earlier"))

    if embeds:
        findings.extend((lesson.lineno(i), msg) for i, msg in _embed_order(vault, lesson, body, prereq_targets, cache))
    return findings


def fact_ledger_validate(params: Mapping[str, object]) -> str | None:
    sections = params.get("sections")
    if not isinstance(sections, list) or not sections:
        return "sections must be a non-empty list"
    for pattern in sections:
        if isinstance(pattern, str):
            try:
                re.compile(pattern)
            except re.error as exc:
                return f"bad regex {pattern!r}: {exc}"
    example = params.get("example")
    if example is not None and isinstance(example, str):
        try:
            re.compile(example)
        except re.error as exc:
            return f"bad regex {example!r}: {exc}"
    markers = params.get("markers")
    if markers is not None and (not isinstance(markers, list) or not markers):
        return "markers must not be empty"
    return None


def record_relpath(directory: str, rel: str) -> str:
    dir_clean = directory.rstrip("/")
    note_part = rel[:-3] if rel.endswith(".md") else rel
    record_part = note_part.replace("/", "__") + ".json"
    return f"{dir_clean}/{record_part}"


def cold_read_digest(vault: Path, rel: str, text: str, frontmatter: Mapping[str, object]) -> str:
    try:
        _, body_text = load(text)
        body = tuple(body_text.split("\n"))
    except FrontmatterError:
        body = tuple()
    embeds = scan_blocks(body).embeds if body else []
    embed_targets = [e.target for e in embeds]
    prereq_targets = _prereq_targets(frontmatter)

    entries: list[tuple[str, str]] = [(rel, text)]
    seen: set[str] = {rel}
    for target in embed_targets + prereq_targets:
        resolved = _resolve(vault, target)
        if resolved is None or resolved in seen:
            continue
        dep_text = (vault / resolved).read_text(encoding="utf-8")
        seen.add(resolved)
        entries.append((resolved, dep_text))

    h = hashlib.sha256()
    for r, t in entries:
        h.update(r.encode("utf-8"))
        h.update(b"\0")
        h.update(t.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def cold_read(lesson: Lesson, params: Mapping[str, object], vault: Path) -> list[Finding]:
    directory = str(params["dir"])
    relpath = record_relpath(directory, lesson.rel)
    record_path = vault / relpath
    if not record_path.is_file():
        return [(None, f"cold_read: no record {relpath}")]
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [(None, f"cold_read: unreadable record {relpath}")]
    if not isinstance(record, dict):
        return [(None, f"cold_read: unreadable record {relpath}")]
    if record.get("lesson") != lesson.rel:
        return [(None, f"cold_read: record {relpath} is for another lesson")]
    if record.get("verdict") != "pass":
        return [(None, f"cold_read: verdict {record.get('verdict')!r}, not pass")]
    try:
        digest = cold_read_digest(vault, lesson.rel, "\n".join(lesson.lines), lesson.frontmatter)
    except (OSError, UnicodeDecodeError):
        return [(None, "cold_read: cannot read a dependency")]
    if record.get("sha256") != digest:
        return [(None, f"cold_read: stale record, current sha256 {digest}")]
    return []


def cold_read_validate(params: Mapping[str, object]) -> str | None:
    directory = params.get("dir")
    if not isinstance(directory, str) or not directory:
        return "dir must be a vault-relative folder"
    p = PurePosixPath(directory)
    if p.is_absolute() or ".." in p.parts:
        return "dir must be a vault-relative folder"
    return None
