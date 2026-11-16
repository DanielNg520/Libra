"""Study check command against the vault rule file `Tools/lesson_rules.toml`."""
from __future__ import annotations

import sys
from pathlib import Path

from libra.study.checks import RuleFileError, check_text, lesson_paths, load_rules
from libra.study.paths import LESSON_ROOTS

__all__ = ["cmd_study_check"]


def cmd_study_check(vault: Path, paths: list[str], all_lessons: bool, profile: str | None) -> int:
    """Check lessons against vault `Tools/lesson_rules.toml` (ADR-0046)."""
    try:
        ruleset = load_rules(vault)
    except RuleFileError as exc:
        print(f"study check: {exc}", file=sys.stderr)
        return 2
    if profile is not None and profile not in ruleset.profiles:
        print(f"study check: unknown profile {profile!r}", file=sys.stderr)
        return 2

    usage_error = False
    targets: list[str] = []
    for p in paths:
        rel = _vault_rel(vault, p)
        if rel is None:
            print(f"study check: outside the vault: {p}", file=sys.stderr)
            usage_error = True
        else:
            targets.append(rel)
    if all_lessons:
        targets.extend(lesson_paths(vault, ruleset, LESSON_ROOTS))
    targets = list(dict.fromkeys(targets))
    if not targets:
        print("study check: no lessons to check (give paths or --all)", file=sys.stderr)
        return 2

    failures = 0
    notes = 0
    files_checked = 0
    used_profiles: list[str] = []
    for rel in targets:
        name = profile or ruleset.profile_for(rel)
        if name is None:
            print(f"study check: no profile matches {rel}; pass --profile", file=sys.stderr)
            usage_error = True
            continue
        if not (vault / rel).is_file():
            print(f"study check: no such file: {rel}", file=sys.stderr)
            usage_error = True
            continue
        try:
            text = (vault / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"study check: cannot read {rel}: {exc}", file=sys.stderr)
            usage_error = True
            continue
        for failure in check_text(text, rel, vault, ruleset.rules_for(name)):
            print(failure.format())
            if failure.note:
                notes += 1
            else:
                failures += 1
        files_checked += 1
        if name not in used_profiles:
            used_profiles.append(name)
    for name in used_profiles:
        print(f"manual checklist ({name}):")
        for rule in ruleset.manual_rules(name):
            suffix = f" (planned: {rule.planned_kind})" if rule.planned_kind else ""
            print(f"- {rule.id}: {rule.text}{suffix}")
    print(f"study check: {files_checked} files, {failures} failures, {notes} notes")
    return 2 if usage_error else 1 if failures else 0


def _vault_rel(vault: Path, raw: str) -> str | None:
    p = Path(raw).expanduser()
    if p.is_absolute():
        try:
            return p.resolve().relative_to(vault.resolve()).as_posix()
        except ValueError:
            return None
    if ".." in p.parts:
        return None
    return p.as_posix()
