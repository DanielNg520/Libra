"""Vault path guard and wikilink resolution shared by the Study API and the nightly job (ADR-0043, ADR-0046)."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from pathlib import Path, PurePosixPath

from libra.study.render import IMAGE_SUFFIXES

LESSON_ROOTS: tuple[str, ...] = ("Self study/",)

__all__ = ["StudyPathError", "LESSON_ROOTS", "make_resolver", "note_names", "resolve_study_path"]


class StudyPathError(ValueError):
    """Raised when a vault-relative path fails validation."""


def resolve_study_path(
    vault: Path, rel: str, suffixes: Collection[str]
) -> Path:
    if not rel or "\x00" in rel:
        raise StudyPathError(f"invalid path: {rel!r}")
    posix = PurePosixPath(rel)
    if posix.is_absolute() or ".." in posix.parts:
        raise StudyPathError(f"path escapes vault: {rel!r}")
    if not any(rel.startswith(root) for root in LESSON_ROOTS):
        raise StudyPathError(f"path outside lesson roots: {rel!r}")
    allowed_suffixes = {s.lower() for s in suffixes}
    if posix.suffix.lower() not in allowed_suffixes:
        raise StudyPathError(f"unexpected suffix: {rel!r}")
    vault_resolved = vault.resolve()
    candidate = (vault / rel).resolve()
    if not candidate.is_relative_to(vault_resolved):
        raise StudyPathError(f"symlink escape: {rel!r}")
    resolved_roots = [vault_resolved / root for root in LESSON_ROOTS]
    if not any(candidate.is_relative_to(root.resolve()) for root in resolved_roots):
        raise StudyPathError(f"resolved path outside lesson roots: {rel!r}")
    if candidate.suffix.lower() not in allowed_suffixes:
        raise StudyPathError(f"resolved suffix not allowed: {rel!r}")
    return candidate


def make_resolver(
    vault: Path, rel_path: str, names: Mapping[str, str]
) -> Callable[[str], str | None]:
    def resolve_link(target: str) -> str | None:
        lower = target.lower()
        if not lower.endswith(".md") and PurePosixPath(lower).suffix not in IMAGE_SUFFIXES:
            target += ".md"
        candidates: list[str] = []
        if "/" in target:
            candidates.append(target)
            candidates.append(
                str(PurePosixPath(rel_path).parent / target)
            )
        else:
            candidates.append(str(PurePosixPath(rel_path).parent / target))
            name_key = PurePosixPath(target).name.lower()
            if name_key in names:
                candidates.append(names[name_key])
        for cand in candidates:
            try:
                resolved = resolve_study_path(
                    vault, cand, {".md"} | set(IMAGE_SUFFIXES)
                )
            except StudyPathError:
                continue
            if resolved.is_file():
                return cand
        return None

    return resolve_link


def note_names(vault: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for root in LESSON_ROOTS:
        base = vault / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(vault).parts):
                continue
            rel = path.relative_to(vault).as_posix()
            names.setdefault(path.name.lower(), rel)
    return names
