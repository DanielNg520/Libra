"""Study commands: lesson rule check (vault Tools/lesson_rules.toml) and Anki cards."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime
from pathlib import Path

from libra.config import Settings, load_secrets
from libra.study.anki_sync import load_auth
from libra.study.cards import (
    JsonMetaStore,
    MetaStoreError,
    make_cards,
    meta_path,
    preview_cards,
)
from libra.study.checks import RuleFileError, check_text, lesson_paths, load_rules
from libra.study.paths import LESSON_ROOTS
from libra.study.runner import claude_runner

__all__ = ["cmd_study_cards", "cmd_study_check"]

CLAUDE_READ_DIRS: tuple[Path, ...] = (Path.home() / "Ebooks", Path.home() / "Classes")


def cmd_study_cards(settings: Settings, vault: Path, day: date | None, dry_run: bool) -> int:
    """Make Anki cards for lessons ticked in Self study Current.md and Master index.md."""
    today = day if day is not None else datetime.now(settings.zone).date()
    try:
        store = JsonMetaStore(meta_path(settings.state_dir), persist=not dry_run)
    except MetaStoreError as exc:
        print(f"study cards: {exc}", file=sys.stderr)
        return 2
    if dry_run:
        previews = preview_cards(vault, store)
        for preview in previews:
            suffix = f" (from {preview.source})" if preview.source != preview.path else ""
            print(f"{preview.path}{suffix}")
            for front in preview.fronts:
                print(f"  card: {front}")
            if preview.needs_claude:
                print("  needs Claude: Recall or Reading answers")
        total_cards = sum(len(p.fronts) for p in previews)
        need_claude = sum(1 for p in previews if p.needs_claude)
        print(
            f"study cards --dry-run {today.isoformat()}: {len(previews)} lessons, "
            f"{total_cards} cards without Claude, {need_claude} need Claude"
        )
        return 0
    if importlib.util.find_spec("anki") is None:
        print(
            "study cards: needs the anki extra; reinstall with "
            "uv tool install --editable --force '.[fedora,plot,study,anki]'",
            file=sys.stderr,
        )
        return 2
    secrets = load_secrets(settings)
    auth = load_auth(secrets)
    if auth is None:
        print(
            "study cards: no AnkiWeb key; set LIBRA_ANKIWEB_HKEY in Libra sops",
            file=sys.stderr,
        )
        return 2
    runner = claude_runner(vault, CLAUDE_READ_DIRS)
    carded, failed = make_cards(vault, settings.state_dir, store, today, runner, auth)
    print(f"study cards {today.isoformat()}: carded {len(carded)}, failed {len(failed)}")
    for path in carded:
        print(f"  carded: {path}")
    for path in failed:
        print(f"  failed: {path}")
    return 1 if failed else 0


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
