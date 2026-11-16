"""Anki cards for ticked self-study lessons, ported from SemAI's nightly job (Libra ADR-0002)."""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol

from libra.study.anki_cards import (
    DECKS,
    build_card_prompt,
    lesson_tag,
    note_guid,
    parse_cards,
    reading_embeds,
    reading_sections,
    recall_questions,
    signal_cards,
    to_anki_html,
)
from libra.study.anki_sync import AnkiAuth, COLLECTION_DIR, add_cards, open_collection, sync
from libra.study.runner import LessonError, Runner
from libra.study.paths import LESSON_ROOTS, make_resolver, note_names
from libra.study.render import split_frontmatter
from libra.study.week import Item, parse_week, week_relpath

log = logging.getLogger(__name__)

LOCK_FILE = "study.lock"
ATTEMPT_CAP = 2
ANKI_DONE_PREFIX = "anki_cards:"
ANKI_BODY_PREFIX = "anki_cards_body:"
ANKI_GEN_PREFIX = "anki_gen:"
ANKI_LOCK_FILE = "anki.lock"
ANKI_UNSYNCED_KEY = "anki_unsynced"
SIGNAL_CAT = "DSA"
META_FILE = "meta.json"

__all__ = [
    "ANKI_BODY_PREFIX",
    "ANKI_DONE_PREFIX",
    "ANKI_GEN_PREFIX",
    "ANKI_LOCK_FILE",
    "ANKI_UNSYNCED_KEY",
    "ATTEMPT_CAP",
    "LOCK_FILE",
    "META_FILE",
    "CardPreview",
    "JsonMetaStore",
    "MetaStore",
    "MetaStoreError",
    "make_cards",
    "meta_path",
    "preview_cards",
    "week_lock",
]


class MetaStore(Protocol):
    def meta_get(self, key: str, default: str | None = None) -> str | None: ...
    def meta_set(self, key: str, value: str) -> None: ...


class MetaStoreError(ValueError):
    """The meta file is unreadable or malformed."""


def meta_path(state_dir: Path) -> Path:
    return state_dir / COLLECTION_DIR / META_FILE


class JsonMetaStore:
    def __init__(self, path: Path, *, persist: bool = True) -> None:
        self._path = path
        self._persist = persist
        self._data: dict[str, str] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or any(
                    not isinstance(k, str) or not isinstance(v, str)
                    for k, v in raw.items()
                ):
                    raise ValueError("meta file must map strings to strings")
                self._data = raw
            except (OSError, ValueError, json.JSONDecodeError) as e:
                raise MetaStoreError(f"Cannot read meta file {path}") from e

    def meta_get(self, key: str, default: str | None = None) -> str | None:
        return self._data.get(key, default)

    def meta_set(self, key: str, value: str) -> None:
        self._data[key] = value
        if not self._persist:
            return
        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


@contextmanager
def week_lock(state_dir: Path, name: str = LOCK_FILE) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    fd = (state_dir / name).open("a")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def _done_lessons(vault: Path, store: MetaStore, today: date) -> list[Item]:
    kept: list[Item] = []
    seen: set[PurePosixPath] = set()
    kept_paths: set[str] = set()
    for d in (today - timedelta(days=1), today):
        rel = week_relpath(d)
        if rel in seen:
            continue
        seen.add(rel)
        path = vault / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        week = parse_week(text, str(rel))
        for item in week.items:
            if not item.done:
                continue
            if not item.path:
                continue
            if item.cat not in DECKS:
                continue
            p = PurePosixPath(item.path)
            if p.is_absolute() or ".." in p.parts:
                continue
            if not item.path.startswith(LESSON_ROOTS):
                continue
            if not (vault / item.path).is_file():
                continue
            if item.cat != SIGNAL_CAT and store.meta_get(ANKI_DONE_PREFIX + item.path):
                continue
            if item.path in kept_paths:
                continue
            kept_paths.add(item.path)
            kept.append(item)
    return kept


def _body_key(body: str) -> str | None:
    if not body.strip():
        return None
    return ANKI_BODY_PREFIX + hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


def _concept_body_key(vault: Path, path: str) -> str | None:
    try:
        concept_text = (vault / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    _, body = split_frontmatter(concept_text)
    return _body_key(body)


def _lesson_concepts(
    vault: Path,
    rel: str,
    text: str,
    store: MetaStore,
    taken: Sequence[str],
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    embeds = reading_embeds(text)
    if not embeds:
        return ([], {})
    resolve = make_resolver(vault, rel, note_names(vault))
    concepts: list[tuple[str, str]] = []
    fresh: dict[str, str] = {}
    seen_paths: set[str] = set()
    for target, label in embeds:
        path = resolve(target)
        if path is None or not path.endswith(".md"):
            log.warning("anki: %s embeds missing concept %s", rel, target)
            continue
        if path in seen_paths:
            continue
        seen_paths.add(path)
        try:
            concept_text = (vault / path).read_text(encoding="utf-8")
        except OSError:
            log.warning("anki: cannot read concept %s", path)
            continue
        _, body = split_frontmatter(concept_text)
        concepts.append((label, body))
        body_key = _body_key(body)
        if store.meta_get(ANKI_DONE_PREFIX + path):
            continue
        if body_key is not None and store.meta_get(body_key):
            continue
        if label in taken or label in fresh:
            log.warning("anki: %s concept label %r repeats; no Reading cards for %s", rel, label, path)
            continue
        fresh[label] = path
    return (concepts, fresh)


def _signal_source(vault: Path, rel: str, text: str) -> tuple[str, str] | None:
    fm, _ = split_frontmatter(text)
    target = fm.get("pattern")
    if target is None:
        return (rel, text)
    if not isinstance(target, str) or not target.strip():
        log.warning("anki: %s names missing pattern %r", rel, target)
        return None
    pattern = make_resolver(vault, rel, note_names(vault))(target.strip())
    if pattern is None or pattern == rel:
        log.warning("anki: %s names missing pattern %r", rel, target)
        return None
    try:
        pattern_text = (vault / pattern).read_text(encoding="utf-8")
    except OSError:
        log.warning("anki: cannot read pattern %s", pattern)
        return None
    return (pattern, pattern_text)


def _item_sources(vault: Path, item: Item, store: MetaStore) -> _ItemSources | None:
    rel = item.path
    text = (vault / rel).read_text(encoding="utf-8")
    if item.cat == SIGNAL_CAT:
        resolved = _signal_source(vault, rel, text)
        if resolved is None:
            return None
        rel, text = resolved
        questions = []
        own = []
        signals = signal_cards(text, PurePosixPath(rel).stem)
    else:
        questions = recall_questions(text)
        own = reading_sections(text)
        signals = []
    concepts, fresh = _lesson_concepts(vault, rel, text, store, own)
    sections = own + list(fresh)
    notes = [(note_guid(rel, c.question), to_anki_html(c.question), to_anki_html(c.answer)) for c in signals]
    return _ItemSources(
        rel=rel,
        text=text,
        questions=questions,
        sections=sections,
        concepts=concepts,
        fresh=fresh,
        notes=notes,
    )


def _item_notes(vault: Path, item: Item, store: MetaStore, today: date, runner: Runner, cap: int) -> tuple[list[tuple[str, str, str]], dict[str, str]] | None:
    sources = _item_sources(vault, item, store)
    if sources is None:
        return None
    rel = sources.rel
    text = sources.text
    questions = sources.questions
    sections = sources.sections
    concepts = sources.concepts
    fresh = sources.fresh
    notes = sources.notes
    if not questions and not sections:
        if item.cat == SIGNAL_CAT:
            if not notes:
                log.info("anki: %s has no signals or new concepts; skipped", rel)
            return notes, fresh
        log.warning("anki: %s has no Recall items or Reading headings; skipped", rel)
        store.meta_set(ANKI_DONE_PREFIX + rel, today.isoformat())
        return [], {}
    key = f"{ANKI_GEN_PREFIX}{today.isoformat()}:{rel}"
    try:
        attempts = int(store.meta_get(key) or "0")
    except ValueError:
        attempts = cap
    if attempts >= cap:
        log.info("anki: attempt cap reached for %s", rel)
        return (notes, {}) if notes else None
    store.meta_set(key, str(attempts + 1))
    try:
        raw = runner(build_card_prompt(text, questions, sections, concepts))
    except LessonError as exc:
        log.warning("anki: cards for %s failed: %s", rel, exc)
        return (notes, {}) if notes else None
    cards, errors = parse_cards(raw, questions, sections)
    if errors:
        log.warning("anki: cards for %s failed: %s", rel, "; ".join(errors))
        return (notes, {}) if notes else None
    notes.extend((note_guid(fresh.get(c.section or "", rel), c.question), to_anki_html(c.question), to_anki_html(c.answer)) for c in cards)
    return notes, fresh


def make_cards(
    vault: Path,
    state_dir: Path,
    store: MetaStore,
    today: date,
    runner: Runner,
    auth: AnkiAuth | None,
    *,
    cap: int = ATTEMPT_CAP,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if auth is None:
        log.info("anki: no sync key; skipped")
        return ((), ())
    pending = _done_lessons(vault, store, today)
    if not pending and not store.meta_get(ANKI_UNSYNCED_KEY):
        return ((), ())
    carded: list[str] = []
    failed: list[str] = []
    with week_lock(state_dir, ANKI_LOCK_FILE):
        col = open_collection(state_dir)
        try:
            try:
                sync(col, auth)
            except Exception as exc:
                log.warning("anki: sync failed: %s", exc)
                return ((), tuple(item.path for item in pending))
            store.meta_set(ANKI_UNSYNCED_KEY, "")
            for item in pending:
                built = _item_notes(vault, item, store, today, runner, cap)
                if built is None:
                    failed.append(item.path)
                    continue
                notes, fresh = built
                if not notes:
                    continue
                try:
                    added = add_cards(col, DECKS[item.cat], notes, [lesson_tag(item.path)])
                except Exception as exc:
                    log.warning("anki: adding cards for %s failed: %s", item.path, exc)
                    failed.append(item.path)
                    continue
                for concept_path in fresh.values():
                    store.meta_set(ANKI_DONE_PREFIX + concept_path, today.isoformat())
                    body_key = _concept_body_key(vault, concept_path)
                    if body_key is not None:
                        store.meta_set(body_key, today.isoformat())
                store.meta_set(ANKI_DONE_PREFIX + item.path, today.isoformat())
                if added > 0:
                    store.meta_set(ANKI_UNSYNCED_KEY, "1")
                    carded.append(item.path)
                    log.info("anki: carded %s (%d cards)", item.path, added)
            if store.meta_get(ANKI_UNSYNCED_KEY):
                try:
                    sync(col, auth)
                    store.meta_set(ANKI_UNSYNCED_KEY, "")
                except Exception as exc:
                    log.warning("anki: sync after adding failed: %s", exc)
        finally:
            col.close()
    return (tuple(carded), tuple(failed))


@dataclass(frozen=True)
class _ItemSources:
    rel: str
    text: str
    questions: list[str]
    sections: list[str]
    concepts: list[tuple[str, str]]
    fresh: dict[str, str]
    notes: list[tuple[str, str, str]]


@dataclass(frozen=True)
class CardPreview:
    path: str
    source: str
    fronts: tuple[str, ...]
    needs_claude: bool


def preview_cards(vault: Path, store: MetaStore, today: date) -> list[CardPreview]:
    previews: list[CardPreview] = []
    for item in _done_lessons(vault, store, today):
        sources = _item_sources(vault, item, store)
        if sources is None:
            continue
        previews.append(
            CardPreview(
                path=item.path,
                source=sources.rel,
                fronts=tuple(front for _, front, _ in sources.notes),
                needs_claude=bool(sources.questions or sources.sections),
            )
        )
    return previews



