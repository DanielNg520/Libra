"""Lesson check kinds over text patterns and references: patterns, figures, links, vault_links (ADR-0046 C2)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from libra.study.check_concepts import IMAGE_EXTS, count_concepts, fence_mask, section_bounds

if TYPE_CHECKING:
    from libra.study.check_kinds import Finding, Lesson

__all__ = [
    "lesson_base",
    "require_pattern",
    "require_pattern_validate",
    "forbid_pattern",
    "forbid_pattern_validate",
    "figures",
    "figures_validate",
    "links",
    "links_validate",
    "vault_links",
    "vault_links_validate",
]

_IMAGE_WIKILINK_RE = re.compile(r"!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")


def lesson_base(path: str) -> PurePosixPath:
    parent = PurePosixPath(path).parent
    if parent.name == "lessons":
        return parent.parent
    return parent


def _regex_error(patterns: Sequence[object]) -> str | None:
    for pattern in patterns:
        try:
            re.compile(str(pattern))
        except re.error as exc:
            return f"bad regex {pattern!r}: {exc}"
    return None


def _scan_lines(
    lesson: Lesson, section: object | None, mask: Sequence[bool]
) -> Sequence[int]:
    body = lesson.body()
    if section is None:
        return [i for i in range(len(body)) if not mask[i]]
    bounds = section_bounds(body, str(section), mask)
    if bounds is None:
        return []
    start, end = bounds
    return [i for i in range(start + 1, end) if not mask[i]]


def require_pattern_validate(params: Mapping[str, object]) -> str | None:
    if "min" in params and int(params["min"]) < 1:
        return "min must be at least 1"
    return _regex_error([params["pattern"]])


def require_pattern(
    lesson: Lesson, params: Mapping[str, object], vault: Path
) -> list[Finding]:
    pattern = re.compile(str(params["pattern"]))
    mask = fence_mask(lesson.body())
    min_count = int(params.get("min", 1))
    message = params.get("message")
    section = params.get("section")
    scan_lines = _scan_lines(lesson, section, mask)
    n = sum(1 for i in scan_lines if pattern.search(lesson.body()[i]))
    if n >= min_count:
        return []
    line: int | None = None
    if section is not None:
        bounds = section_bounds(lesson.body(), str(section), mask)
        if bounds is not None:
            line = lesson.lineno(bounds[0])
    text = str(message) if message is not None else f"pattern missing: {params['pattern']!r}"
    if min_count > 1:
        text += f" (found {n}, need {min_count})"
    return [(line, text)]


def forbid_pattern_validate(params: Mapping[str, object]) -> str | None:
    patterns = [params["pattern"]]
    if "skip" in params:
        patterns.append(params["skip"])
    return _regex_error(patterns)


def forbid_pattern(
    lesson: Lesson, params: Mapping[str, object], vault: Path
) -> list[Finding]:
    body = lesson.body()
    mask = fence_mask(body)
    pattern = re.compile(str(params["pattern"]))
    skip_pattern = re.compile(str(params["skip"])) if "skip" in params else None
    skip_sections = [str(s) for s in params.get("skip_sections", [])]
    skipped: set[int] = set()
    for section in skip_sections:
        bounds = section_bounds(body, section, mask)
        if bounds is not None:
            skipped.update(range(bounds[0], bounds[1]))
    message = str(params.get("message", "forbidden pattern"))
    findings: list[Finding] = []
    for i in _scan_lines(lesson, params.get("section"), mask):
        if i in skipped:
            continue
        line_text = body[i]
        if skip_pattern is not None and skip_pattern.match(line_text):
            continue
        for match in pattern.finditer(line_text):
            findings.append((lesson.lineno(i), f"{message}: {match.group(0)!r}"))
    return findings


def _image_targets(
    lesson: Lesson, mask: Sequence[bool]
) -> list[tuple[int, str]]:
    body = lesson.body()
    targets: list[tuple[int, str]] = []
    for i, line in enumerate(body):
        if mask[i]:
            continue
        for match in _IMAGE_WIKILINK_RE.finditer(line):
            target = match.group(1).strip()
            if target.lower().endswith(IMAGE_EXTS):
                targets.append((i, target))
        for match in _IMAGE_MARKDOWN_RE.finditer(line):
            target = match.group(1).strip()
            if target.lower().startswith(("http://", "https://")):
                continue
            if target.lower().endswith(IMAGE_EXTS):
                targets.append((i, target))
    return targets


def figures_validate(params: Mapping[str, object]) -> str | None:
    if int(params["max"]) < 0:
        return "max must not be negative"
    return None


def figures(
    lesson: Lesson, params: Mapping[str, object], vault: Path
) -> list[Finding]:
    mask = fence_mask(lesson.body())
    targets = _image_targets(lesson, mask)
    max_images = int(params["max"])
    findings: list[Finding] = []
    if len(targets) > max_images:
        findings.append((None, f"figures: {len(targets)} images, max {max_images}"))
    lesson_dir = PurePosixPath(lesson.rel).parent
    for i, target in targets:
        path = PurePosixPath(target)
        if path.is_absolute() or ".." in path.parts:
            findings.append((lesson.lineno(i), f"figures: image outside the lesson folder {target!r}"))
        elif not (vault / lesson_dir / target).is_file():
            findings.append((lesson.lineno(i), f"figures: image missing {target!r}"))
    return findings


def _wikilinks(lesson: Lesson, mask: Sequence[bool]) -> list[tuple[int, str, str | None]]:
    body = lesson.body()
    links: list[tuple[int, str, str | None]] = []
    for i, line in enumerate(body):
        if mask[i]:
            continue
        for match in _WIKILINK_RE.finditer(line):
            raw = match.group(1)
            parts = raw.split("|", 1)
            target = parts[0].rstrip("\\")
            target = target.split("#", 1)[0].strip()
            alias: str | None = None
            if len(parts) > 1:
                alias = parts[1].strip()
                if not alias:
                    alias = None
            links.append((i, target, alias))
    return links


def links_validate(params: Mapping[str, object]) -> str | None:
    if "section_ref" in params:
        compiled = _regex_error([params["section_ref"]])
        if compiled is not None:
            return compiled
        compiled = re.compile(str(params["section_ref"]))
        if compiled.groups < 1:
            return "section_ref needs one group"
    return None


def links(
    lesson: Lesson, params: Mapping[str, object], vault: Path
) -> list[Finding]:
    body = lesson.body()
    mask = fence_mask(body)
    findings: list[Finding] = []
    for i, target, alias in _wikilinks(lesson, mask):
        line_no = lesson.lineno(i)
        if "/" not in target:
            findings.append((line_no, f"links: not path-qualified {target!r}"))
            continue
        if alias is None:
            findings.append((line_no, f"links: no alias {target!r}"))
            continue
        path = PurePosixPath(target)
        if path.is_absolute() or ".." in path.parts:
            findings.append((line_no, f"links: target outside the vault {target!r}"))
            continue
        file_target = target if PurePosixPath(target).suffix else target + ".md"
        if not (vault / file_target).is_file():
            findings.append((line_no, f"links: target missing {target!r}"))
    if "section_ref" in params:
        section_ref = re.compile(str(params["section_ref"]))
        concept_section = str(params.get("concept_section", "## Reading"))
        n = count_concepts(lesson, concept_section, mask)
        for i, line in enumerate(body):
            if mask[i]:
                continue
            for match in section_ref.finditer(line):
                k = match.group(1)
                if k.isdigit() and not (1 <= int(k) <= n):
                    findings.append(
                        (lesson.lineno(i), f"links: section {k} does not exist ({n} concepts)")
                    )
    return findings


def vault_links_validate(params: Mapping[str, object]) -> str | None:
    target = params["target"]
    if target not in ("outline", "week"):
        return f"target must be 'outline' or 'week', not {target!r}"
    return None


def _links_lesson(text: str, rel: str) -> bool:
    stem = rel[:-3] if rel.endswith(".md") else rel
    return (
        f"[[{stem}|" in text
        or f"[[{stem}\\|" in text
        or f"[[{stem}]]" in text
    )


def vault_links(
    lesson: Lesson, params: Mapping[str, object], vault: Path
) -> list[Finding]:
    target = params["target"]
    if target == "outline":
        outline_name = str(params.get("outline", "01 outline.md"))
        path = vault / lesson_base(lesson.rel) / outline_name
        if not path.is_file():
            relpath = path.relative_to(vault).as_posix()
            return [(None, f"vault_links: outline missing {relpath}")]
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            relpath = path.relative_to(vault).as_posix()
            return [(None, f"vault_links: cannot read outline {relpath}")]
        for line in lines:
            if line.startswith("|") and _links_lesson(line, lesson.rel):
                return []
        return [(None, "vault_links: no outline row links the lesson")]
    week_dir = str(params.get("week_dir", "Self study/Weekly"))
    base = vault / week_dir
    if not base.is_dir():
        return [(None, "vault_links: no week file links the lesson")]
    for file in sorted(base.rglob("*.md")):
        try:
            content = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _links_lesson(content, lesson.rel):
            return []
    return [(None, "vault_links: no week file links the lesson")]
