"""Lesson check kinds over concepts and sections: per_concept, section_shape, size (ADR-0046 C2)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from libra.study.render import scan_blocks

if TYPE_CHECKING:
    from libra.study.check_kinds import Finding, Lesson

CONCEPT_HEADING_RE = re.compile(r"^### \d+\.\s")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
EMBED_RE = re.compile(r"^!\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]\s*$")
DEFAULT_SECTION = "## Reading"
SOURCES_HEADING = "## Sources"

__all__ = [
    "CONCEPT_HEADING_RE",
    "IMAGE_EXTS",
    "EMBED_RE",
    "DEFAULT_SECTION",
    "SOURCES_HEADING",
    "fence_mask",
    "section_bounds",
    "is_concept_embed",
    "concept_units",
    "count_concepts",
    "words_outside_code",
    "per_concept",
    "per_concept_validate",
    "section_shape",
    "section_shape_validate",
    "size",
    "size_validate",
]


def fence_mask(body: Sequence[str]) -> list[bool]:
    """Code lines of `body` (fenced or indented), as the Study page parser sees them."""
    return list(scan_blocks(tuple(body)).code)


def section_bounds(
    body: Sequence[str], heading: str, mask: Sequence[bool]
) -> tuple[int, int] | None:
    for i, line in enumerate(body):
        if not mask[i] and line == heading:
            start = i
            break
    else:
        return None
    for i in range(start + 1, len(body)):
        if not mask[i] and body[i].startswith("## "):
            return start, i
    return start, len(body)


def is_concept_embed(line: str) -> bool:
    m = EMBED_RE.match(line)
    if not m:
        return False
    target = m.group(1).strip()
    return not target.lower().endswith(IMAGE_EXTS)


def concept_units(
    lesson: Lesson, unit: str, section: str, mask: Sequence[bool]
) -> list[tuple[int, int, str]]:
    body = lesson.body()
    if unit == "heading":
        bounds = section_bounds(body, section, mask)
        if bounds is None:
            return []
        section_start, section_end = bounds
        units: list[tuple[int, int, str]] = []
        current_start: int | None = None
        current_label = ""
        for i in range(section_start, section_end):
            if mask[i]:
                continue
            line = body[i]
            if CONCEPT_HEADING_RE.match(line):
                if current_start is not None:
                    units.append((current_start, i, current_label))
                current_start = i
                current_label = line[4:]
            elif line.startswith("### ") or line.startswith("## "):
                if current_start is not None:
                    units.append((current_start, i, current_label))
                    current_start = None
        if current_start is not None:
            units.append((current_start, section_end, current_label))
        return units
    if unit == "file":
        for i, line in enumerate(body):
            if not mask[i] and line == SOURCES_HEADING:
                return [(0, i, "concept note")]
        return [(0, len(body), "concept note")]
    raise ValueError(f"unknown unit: {unit!r}")


def count_concepts(lesson: Lesson, section: str, mask: Sequence[bool]) -> int:
    body = lesson.body()
    bounds = section_bounds(body, section, mask)
    if bounds is None:
        return 0
    start, end = bounds
    count = 0
    for i in range(start, end):
        if mask[i]:
            continue
        line = body[i]
        if CONCEPT_HEADING_RE.match(line) or is_concept_embed(line):
            count += 1
    return count


def words_outside_code(lesson: Lesson, mask: Sequence[bool]) -> int:
    body = lesson.body()
    end = len(body)
    for i, line in enumerate(body):
        if not mask[i] and line == SOURCES_HEADING:
            end = i
            break
    return sum(len(body[i].split()) for i in range(end) if not mask[i])


def per_concept_validate(params: Mapping[str, object]) -> str | None:
    unit = params.get("unit")
    if unit not in ("heading", "file"):
        return f"unit must be 'heading' or 'file', not {unit!r}"
    has_label = "label" in params
    has_min = "min" in params
    has_max = "max" in params
    if has_label != has_min or has_label != has_max:
        return "label, min and max go together"
    if has_min and has_max:
        min_val = params["min"]
        max_val = params["max"]
        assert isinstance(min_val, int)
        assert isinstance(max_val, int)
        if min_val > max_val:
            return "min must not exceed max"
    if "max_prose_lines" in params:
        mpl = params["max_prose_lines"]
        assert isinstance(mpl, int)
        if mpl < 0:
            return "max_prose_lines must not be negative"
    patterns = []
    if "label" in params:
        patterns.append(params["label"])
    if "require" in params:
        patterns.extend(params["require"])
    if "require_in_code" in params:
        patterns.extend(params["require_in_code"])
    if "prose_skip" in params:
        patterns.append(params["prose_skip"])
    for pattern in patterns:
        assert isinstance(pattern, str)
        try:
            re.compile(pattern)
        except re.error as exc:
            return f"bad regex {pattern!r}: {exc}"
    return None


def per_concept(
    lesson: Lesson, params: Mapping[str, object], vault: Path
) -> list[Finding]:
    body = lesson.body()
    mask = fence_mask(body)
    unit = params["unit"]
    assert isinstance(unit, str)
    section = params.get("section", DEFAULT_SECTION)
    assert isinstance(section, str)
    findings: list[Finding] = []
    for start, end, label in concept_units(lesson, unit, section, mask):
        line_no = lesson.lineno(start)
        if "label" in params:
            label_re = re.compile(params["label"])
            assert isinstance(label_re, re.Pattern)
            n = sum(
                1
                for i in range(start, end)
                if not mask[i] and label_re.match(body[i])
            )
            min_val = params.get("min", 0)
            max_val = params.get("max", float("inf"))
            assert isinstance(min_val, int)
            if n < min_val or n > max_val:
                findings.append(
                    (line_no, f"{label}: expected {min_val}-{max_val} checks, found {n}")
                )
        if "require" in params:
            require_patterns = params["require"]
            assert isinstance(require_patterns, list)
            for pattern in require_patterns:
                assert isinstance(pattern, str)
                if not any(
                    re.search(pattern, body[i])
                    for i in range(start, end)
                    if not mask[i]
                ):
                    findings.append((line_no, f"{label}: missing {pattern!r}"))
        if "require_in_code" in params:
            code_patterns = params["require_in_code"]
            assert isinstance(code_patterns, list)
            for pattern in code_patterns:
                assert isinstance(pattern, str)
                if not any(
                    mask[i]
                    and not body[i].lstrip().startswith("```")
                    and re.search(pattern, body[i])
                    for i in range(start, end)
                ):
                    findings.append((line_no, f"{label}: code lacks {pattern!r}"))
        if "max_prose_lines" in params:
            max_prose = params["max_prose_lines"]
            assert isinstance(max_prose, int)
            first = start + 1 if unit == "heading" else start
            prose = 0
            label_re = (
                re.compile(params["label"]) if "label" in params else None
            )
            prose_skip_re = (
                re.compile(params["prose_skip"]) if "prose_skip" in params else None
            )
            for i in range(first, end):
                if mask[i]:
                    continue
                line = body[i]
                stripped = line.strip()
                if not stripped:
                    continue
                ls = line.lstrip()
                if ls.startswith(("#", ">", "|", "![")):
                    continue
                if label_re is not None and label_re.match(line):
                    continue
                if prose_skip_re is not None and prose_skip_re.match(line):
                    continue
                prose += 1
            if prose > max_prose:
                findings.append(
                    (line_no, f"{label}: {prose} prose lines, max {max_prose}")
                )
    return findings


def section_shape_validate(params: Mapping[str, object]) -> str | None:
    has_label = "label" in params
    has_min = "min_items" in params
    has_max = "max_items" in params
    if (has_min or has_max) and not has_label:
        return "min_items and max_items need label"
    if has_min and has_max:
        min_val = params["min_items"]
        max_val = params["max_items"]
        assert isinstance(min_val, int)
        assert isinstance(max_val, int)
        if min_val > max_val:
            return "min_items must not exceed max_items"
    patterns = []
    for key in ("allowed", "order", "label"):
        if key in params:
            value = params[key]
            if key == "label":
                patterns.append(value)
            else:
                patterns.extend(value)
    for pattern in patterns:
        assert isinstance(pattern, str)
        try:
            re.compile(pattern)
        except re.error as exc:
            return f"bad regex {pattern!r}: {exc}"
    return None


def section_shape(
    lesson: Lesson, params: Mapping[str, object], vault: Path
) -> list[Finding]:
    body = lesson.body()
    mask = fence_mask(body)
    section = params["section"]
    assert isinstance(section, str)
    bounds = section_bounds(body, section, mask)
    if bounds is None:
        return []
    section_start, section_end = bounds
    section_line = lesson.lineno(section_start)
    headings: list[tuple[int, str]] = []
    for i in range(section_start + 1, section_end):
        if mask[i]:
            continue
        line = body[i]
        if line.startswith("### "):
            headings.append((i, line))
    findings: list[Finding] = []
    if "allowed" in params:
        allowed = [re.compile(p) for p in params["allowed"]]
        for idx, heading in headings:
            if not any(p.match(heading) for p in allowed):
                findings.append(
                    (lesson.lineno(idx), f"{section}: heading not allowed: {heading}")
                )
    if "order" in params:
        order = [re.compile(p) for p in params["order"]]
        found: list[tuple[int, str]] = []
        for pattern in order:
            for idx, heading in headings:
                if pattern.match(heading):
                    found.append((idx, heading))
                    break
            else:
                findings.append(
                    (section_line, f"{section}: missing part {pattern.pattern!r}")
                )
        last_idx = -1
        for idx, heading in found:
            if idx < last_idx:
                findings.append(
                    (lesson.lineno(idx), f"{section}: part out of order: {heading}")
                )
            last_idx = idx
    if "label" in params and ("min_items" in params or "max_items" in params):
        label_re = re.compile(params["label"])
        first_heading = next((i for i, _ in headings), section_end)
        n = sum(
            1
            for i in range(section_start + 1, first_heading)
            if not mask[i] and label_re.match(body[i])
        )
        lo = params.get("min_items", 0)
        hi = params.get("max_items", "any")
        if n < lo or (hi != "any" and n > hi):
            findings.append(
                (section_line, f"{section}: opening set has {n} problems, expected {lo}-{hi}")
            )
    return findings


def size_validate(params: Mapping[str, object]) -> str | None:
    measure = params.get("measure")
    if measure not in ("concepts", "words"):
        return f"measure must be 'concepts' or 'words', not {measure!r}"
    if "max" in params:
        max_val = params["max"]
        assert isinstance(max_val, int)
        if max_val < 0:
            return "max must not be negative"
    return None


def size(lesson: Lesson, params: Mapping[str, object], vault: Path) -> list[Finding]:
    body = lesson.body()
    mask = fence_mask(body)
    measure = params["measure"]
    assert isinstance(measure, str)
    max_val = params["max"]
    assert isinstance(max_val, int)
    if measure == "concepts":
        section = params.get("section", DEFAULT_SECTION)
        assert isinstance(section, str)
        n = count_concepts(lesson, section, mask)
        if n > max_val:
            return [(None, f"size: {n} concepts, max {max_val}")]
    elif measure == "words":
        n = words_outside_code(lesson, mask)
        if n > max_val:
            return [(None, f"size: {n} words, max {max_val}")]
    return []
