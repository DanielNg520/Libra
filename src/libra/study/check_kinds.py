"""Lesson check kinds: the fixed vocabulary of parameterized checks behind `Tools/lesson_rules.toml` (ADR-0046)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from libra.study.frontmatter import FrontmatterError, load
from libra.study.check_concepts import (
    fence_mask,
    per_concept,
    per_concept_validate,
    section_shape,
    section_shape_validate,
    size,
    size_validate,
)
from libra.study.check_refs import (
    figures,
    figures_validate,
    forbid_pattern,
    forbid_pattern_validate,
    links,
    links_validate,
    require_pattern,
    require_pattern_validate,
    vault_links,
    vault_links_validate,
)
from libra.study.check_code import Note, code_run, code_run_validate
from libra.study.check_facts import (
    cold_read,
    cold_read_validate,
    fact_ledger,
    fact_ledger_validate,
)

RECALL_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S")
_WIKILINK_RE = re.compile(r"^\[\[([^|\]]+)(?:\|[^\]]+)?\]\]$")
_CITATION_RE = re.compile(r"§\s?\d|\bch\.\s?\d|\bpp?\.\s?\d|[A-Z]{2,4}\s?\d{1,3}[A-Z]?\s+\S.*?(?:\d|`[^`]+`)")
_SOURCES_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(\S.*)$")


class LessonParseError(ValueError):
    pass


@dataclass(frozen=True)
class Lesson:
    rel: str
    lines: tuple[str, ...]
    body_start: int
    frontmatter: Mapping[str, object]

    def body(self) -> Sequence[str]:
        return self.lines[self.body_start:]

    def lineno(self, body_index: int) -> int:
        return self.body_start + body_index + 1


def parse_lesson(text: str, rel: str) -> Lesson:
    try:
        frontmatter, _ = load(text)
    except FrontmatterError as exc:
        raise LessonParseError(str(exc)) from exc

    lines = tuple(text.split("\n"))
    body_start = len(lines)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            body_start = i + 1
            break

    return Lesson(rel=rel, lines=lines, body_start=body_start, frontmatter=frontmatter)


Finding = tuple[int | None, str]
Check = Callable[[Lesson, Mapping[str, object], Path], list[Finding | Note]]


@dataclass(frozen=True)
class KindSpec:
    check: Check | None
    required: Mapping[str, str]
    optional: Mapping[str, str]
    validate: Callable[[Mapping[str, object]], str | None] | None = None


def param_ok(value: object, type_name: str) -> bool:
    if type_name == "str":
        return isinstance(value, str)
    if type_name == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "list[str]":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if type_name == "dict[str,str]":
        return (
            isinstance(value, dict)
            and all(isinstance(k, str) for k in value.keys())
            and all(isinstance(v, str) for v in value.values())
        )
    raise ValueError(f"unknown type name: {type_name!r}")


def _heading_order(lesson: Lesson, params: Mapping[str, object], vault: Path) -> list[Finding]:
    headings = params["headings"]
    assert isinstance(headings, list)

    findings: list[Finding] = []
    position = 0
    for heading in headings:
        assert isinstance(heading, str)
        found = False
        body = lesson.body()
        for i in range(position, len(body)):
            if body[i] == heading:
                position = i + 1
                found = True
                break
        if not found:
            findings.append((None, f"heading missing: {heading}"))
    last = params.get("last")
    if last is not None:
        assert isinstance(last, str)
        mask = fence_mask(lesson.body())
        body = lesson.body()
        last_heading = None
        for i in range(len(body) - 1, -1, -1):
            if not mask[i] and body[i].startswith("## "):
                last_heading = body[i]
                break
        if last_heading != last:
            findings.append((None, f"heading not last: {last}"))
    return findings


def _frontmatter(lesson: Lesson, params: Mapping[str, object], vault: Path) -> list[Finding]:
    field = params["field"]
    assert isinstance(field, str)

    if field == "tags":
        tags = lesson.frontmatter.get("tags")
        if not isinstance(tags, list) or len(tags) == 0 or not all(
            isinstance(t, str) for t in tags
        ):
            return [(None, "tags: must be a non-empty list of strings")]

        findings = []

        allowed = params.get("allowed")
        if allowed is not None:
            assert isinstance(allowed, list)
            for tag in tags:
                if tag not in allowed:
                    findings.append((None, "tags: contains unknown tag"))
                    break

        required_by_glob = params.get("required_by_glob")
        if required_by_glob is not None:
            assert isinstance(required_by_glob, dict)
            matched = False
            for glob, required_tag in required_by_glob.items():
                if fnmatchcase(lesson.rel, glob):
                    matched = True
                    assert isinstance(required_tag, str)
                    if required_tag not in tags:
                        findings.append((None, f"tags: missing required tag {required_tag}"))
                    break
            if not matched:
                findings.append((None, "tags: no required tag for this path"))

        max_tags = params.get("max")
        if max_tags is not None:
            assert isinstance(max_tags, int)
            if len(tags) > max_tags:
                findings.append((None, f"tags: at most {max_tags} tags, found {len(tags)}"))

        return findings

    if field == "prereqs":
        findings: list[Finding] = []
        prereqs = lesson.frontmatter.get("prereqs")
        if "prereqs" not in lesson.frontmatter:
            findings.append((None, "prereqs: key missing"))
            return findings

        if prereqs is None or prereqs == "[]":
            prereqs = []

        if not isinstance(prereqs, list):
            findings.append((None, "prereqs: must be a list"))
            return findings

        for entry in prereqs:
            if not isinstance(entry, str):
                findings.append((None, "prereqs: entries must be strings"))
                continue

            match = _WIKILINK_RE.match(entry)
            if match is None:
                findings.append((None, f"prereqs: invalid wikilink {entry!r}"))
                continue

            target = match.group(1)
            if not target.endswith(".md"):
                target += ".md"

            path = PurePosixPath(target)
            if path.is_absolute() or ".." in path.parts:
                findings.append((None, f"prereqs: target not relative {target!r}"))
            elif not (vault / target).exists():
                findings.append((None, f"prereqs: target missing {target!r}"))

        return findings

    raise ValueError(f"field must be 'tags' or 'prereqs', not {field!r}")


def _section_end(body: Sequence[str], start: int) -> int:
    for i in range(start, len(body)):
        if body[i].startswith("## "):
            return i
    return len(body)


def _list_count(lesson: Lesson, params: Mapping[str, object], vault: Path) -> list[Finding]:
    section = params["section"]
    min_count = params["min"]
    max_count = params["max"]
    assert isinstance(section, str)
    assert isinstance(min_count, int)
    assert isinstance(max_count, int)

    body = lesson.body()
    heading_index = -1
    for i, line in enumerate(body):
        if line == section:
            heading_index = i
            break

    if heading_index == -1:
        return []

    end = _section_end(body, heading_index + 1)
    count = 0
    for i in range(heading_index + 1, end):
        if RECALL_ITEM_RE.match(body[i]):
            count += 1

    if min_count <= count <= max_count:
        return []

    label = params.get("label")
    if label is None:
        label = section.removeprefix("## ").strip().lower()
    assert isinstance(label, str)
    return [
        (
            lesson.lineno(heading_index),
            f"{label}: expected {min_count}-{max_count} items, found {count}",
        )
    ]


def _sources(lesson: Lesson, params: Mapping[str, object], vault: Path) -> list[Finding]:
    heading = params["heading"]
    assert isinstance(heading, str)

    body = lesson.body()
    start = 0
    after = params.get("after")
    if after is not None:
        assert isinstance(after, str)
        for i, line in enumerate(body):
            if line == after:
                start = i + 1
                break

    heading_index = -1
    for i in range(start, len(body)):
        if body[i] == heading:
            heading_index = i
            break

    if heading_index == -1:
        return [(None, f"sources: heading missing: {heading}")]

    end = _section_end(body, heading_index + 1)
    entries: list[tuple[int, str]] = []
    for i in range(heading_index + 1, end):
        match = _SOURCES_ITEM_RE.match(body[i])
        if match:
            entries.append((i, match.group(1)))

    if not entries:
        return [(lesson.lineno(heading_index), "sources: empty list")]

    findings: list[Finding] = []
    for line_index, entry in entries:
        if _CITATION_RE.search(entry) is None:
            findings.append(
                (lesson.lineno(line_index), f"sources: entry lacks a citation {entry!r}")
            )
    return findings


def _answers(lesson: Lesson, params: Mapping[str, object], vault: Path) -> list[Finding]:
    prefix = params["prefix"]
    assert isinstance(prefix, str)

    label = params.get("label")
    if label is None:
        for line in lesson.body():
            if line.startswith(prefix):
                return []
        return [(None, "missing folded answer callout")]

    assert isinstance(label, str)
    body = lesson.body()
    mask = fence_mask(body)
    findings: list[Finding] = []
    for i, line in enumerate(body):
        if mask[i] or re.match(label, line) is None:
            continue
        answered = False
        j = i + 1
        while j < len(body):
            if not mask[j] and (
                re.match(label, body[j]) is not None
                or body[j].startswith("## ")
                or body[j].startswith("### ")
            ):
                break
            if body[j].startswith(prefix):
                answered = True
                break
            j += 1
        if not answered:
            findings.append(
                (lesson.lineno(i), f"answers: no folded answer after {line.strip()[:60]!r}")
            )
    return findings


def _frontmatter_validate(params: Mapping[str, object]) -> str | None:
    field = params.get("field")
    if field != "tags" and field != "prereqs":
        return f"field must be 'tags' or 'prereqs', not {field!r}"
    return None


def _answers_validate(params: Mapping[str, object]) -> str | None:
    label = params.get("label")
    if label is None:
        return None
    assert isinstance(label, str)
    try:
        re.compile(label)
    except re.error as exc:
        return f"bad regex {label!r}: {exc}"
    return None


def _list_count_validate(params: Mapping[str, object]) -> str | None:
    min_count = params.get("min")
    max_count = params.get("max")
    if min_count is not None and max_count is not None:
        assert isinstance(min_count, int)
        assert isinstance(max_count, int)
        if min_count > max_count:
            return "min must not exceed max"
    return None


KINDS: Mapping[str, KindSpec] = MappingProxyType(
    {
        "heading_order": KindSpec(
            check=_heading_order,
            required={"headings": "list[str]"},
            optional={"last": "str"},
        ),
        "frontmatter": KindSpec(
            check=_frontmatter,
            required={"field": "str"},
            optional={"allowed": "list[str]", "required_by_glob": "dict[str,str]", "max": "int"},
            validate=_frontmatter_validate,
        ),
        "list_count": KindSpec(
            check=_list_count,
            required={"section": "str", "min": "int", "max": "int"},
            optional={"label": "str"},
            validate=_list_count_validate,
        ),
        "sources": KindSpec(
            check=_sources,
            required={"heading": "str"},
            optional={"after": "str"},
        ),
        "answers": KindSpec(
            check=_answers,
            required={"prefix": "str"},
            optional={"label": "str"},
            validate=_answers_validate,
        ),
        "per_concept": KindSpec(
            check=per_concept,
            required={"unit": "str"},
            optional={
                "section": "str",
                "label": "str",
                "min": "int",
                "max": "int",
                "require": "list[str]",
                "require_in_code": "list[str]",
                "max_prose_lines": "int",
                "prose_skip": "str",
            },
            validate=per_concept_validate,
        ),
        "section_shape": KindSpec(
            check=section_shape,
            required={"section": "str"},
            optional={
                "allowed": "list[str]",
                "order": "list[str]",
                "label": "str",
                "min_items": "int",
                "max_items": "int",
            },
            validate=section_shape_validate,
        ),
        "size": KindSpec(
            check=size,
            required={"measure": "str", "max": "int"},
            optional={"section": "str"},
            validate=size_validate,
        ),
        "require_pattern": KindSpec(
            check=require_pattern,
            required={"pattern": "str"},
            optional={"section": "str", "min": "int", "message": "str"},
            validate=require_pattern_validate,
        ),
        "forbid_pattern": KindSpec(
            check=forbid_pattern,
            required={"pattern": "str"},
            optional={
                "section": "str",
                "skip": "str",
                "skip_sections": "list[str]",
                "message": "str",
            },
            validate=forbid_pattern_validate,
        ),
        "figures": KindSpec(
            check=figures,
            required={"max": "int"},
            optional={},
            validate=figures_validate,
        ),
        "links": KindSpec(
            check=links,
            required={},
            optional={"section_ref": "str", "concept_section": "str"},
            validate=links_validate,
        ),
        "vault_links": KindSpec(
            check=vault_links,
            required={"target": "str"},
            optional={"outline": "str", "week_dir": "str"},
            validate=vault_links_validate,
        ),
        "code_run": KindSpec(
            check=code_run,
            required={},
            optional={
                "timeout_s": "int",
                "mem_mb": "int",
                "c_flags": "list[str]",
                "cpp_flags": "list[str]",
                "broken": "str",
                "python_output": "str",
                "c_output": "str",
                "cpp_output": "str",
                "error_name": "str",
            },
            validate=code_run_validate,
        ),
        "fact_ledger": KindSpec(
            check=fact_ledger,
            required={"sections": "list[str]"},
            optional={"assumed": "list[str]", "markers": "list[str]", "example": "str", "answer": "str", "min_sites": "int"},
            validate=fact_ledger_validate,
        ),
        "cold_read": KindSpec(
            check=cold_read,
            required={"dir": "str"},
            optional={},
            validate=cold_read_validate,
        ),
        "manual": KindSpec(
            check=None,
            required={},
            optional={},
        ),
    }
)


__all__ = [
    "LessonParseError",
    "Lesson",
    "parse_lesson",
    "Finding",
    "Note",
    "Check",
    "KindSpec",
    "param_ok",
    "KINDS",
]
