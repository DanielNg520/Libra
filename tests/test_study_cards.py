"""Tests for libra.study.cards (Anki card path, Libra ADR-0002)."""

from __future__ import annotations

import fcntl
import json
import logging
from datetime import date
from pathlib import Path

import pytest

from libra.study.runner import LessonError
from libra.study.cards import make_cards
from libra.study.anki_cards import note_guid
from libra.study.anki_sync import AnkiAuth
from libra.study.cards import (
    ANKI_BODY_PREFIX,
    ANKI_DONE_PREFIX,
    ANKI_UNSYNCED_KEY,
    JsonMetaStore,
    MetaStoreError,
    meta_path,
    preview_cards,
    week_lock,
)
from libra.study.week import week_relpath


class FakeStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def meta_get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    def meta_set(self, key: str, value: str) -> None:
        self.data[key] = value


def _week(monday: date, days: dict[int, list[str]], stage: int = 2) -> str:
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    lines = [
        "---",
        "tags:",
        "  - weekly",
        f"week: {monday.isoformat()}",
        f"stage: {stage}",
        "---",
        "",
    ]
    for i in range(7):
        d = date.fromordinal(monday.toordinal() + i)
        lines.append(f"## {names[i]} {d.isoformat()}")
        lines.extend(days.get(i, []))
    return "\n".join(lines) + "\n"


def _write(vault: Path, monday: date, text: str) -> Path:
    path = vault / week_relpath(monday)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_week_lock_excludes_others(tmp_path: Path) -> None:
    lock_path = tmp_path / "study.lock"
    lock_path.write_text("")
    with week_lock(tmp_path):
        handle = open(lock_path)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            handle.close()
    handle = open(lock_path)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


LESSON = "Self study/Probability/02 events and Bayes.md"


def _anki_vault(
    tmp_path: Path, *, done: bool = True, lesson_text: str | None = None
) -> Path:
    vault = tmp_path / "vault"
    lesson = vault / LESSON
    lesson.parent.mkdir(parents=True)
    lesson.write_text(
        lesson_text
        if lesson_text is not None
        else "# PR 02\n\n## Recall\n\n- Q one?\n- Q two?\n\n## Sources\n\n- Ross\n"
    )
    monday = date(2026, 11, 9)
    _write(
        vault,
        monday,
        _week(
            monday,
            {
            0: [
                f"- [{'x' if done else ' '}] PR: [[Self study/Probability/02 events and Bayes|PR 02]]",
                    "- [x] EXTRA: [[Self study/Extra/notes|Notes]]",
                ]
            },
        ),
    )
    return vault


def _good_runner(prompt: str) -> str:
    import json

    return json.dumps(
        [{"q": "Q one?", "a": "A one"}, {"q": "Q two?", "a": "A two"}]
    )


def _fake_anki(monkeypatch: pytest.MonkeyPatch, *, sync_fail_at: int | None = None, added: int | None = None) -> dict:
    rec: dict = {"opened": [], "syncs": [], "added": [], "closed": []}

    class FakeCol:
        def close(self) -> None:
            rec["closed"].append(1)

    def fake_open(state_dir: Path):
        rec["opened"].append(state_dir)
        return FakeCol()

    def fake_sync(col, auth) -> None:
        rec["syncs"].append(1)
        if len(rec["syncs"]) == sync_fail_at:
            raise RuntimeError("boom")

    def fake_add(col, deck, notes, tags) -> int:
        rec["added"].append((deck, list(notes), list(tags)))
        return len(notes) if added is None else added

    monkeypatch.setattr("libra.study.cards.open_collection", fake_open)
    monkeypatch.setattr("libra.study.cards.sync", fake_sync)
    monkeypatch.setattr("libra.study.cards.add_cards", fake_add)
    return rec


def test_make_cards_without_auth_does_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _anki_vault(tmp_path)
    store = FakeStore()
    state = tmp_path / "state"
    today = date(2026, 11, 10)
    rec = _fake_anki(monkeypatch)
    carded, failed = make_cards(vault, state, store, today, _good_runner, None)
    assert carded == ()
    assert failed == ()
    assert rec["opened"] == []


def test_make_cards_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _anki_vault(tmp_path)
    store = FakeStore()
    state = tmp_path / "state"
    today = date(2026, 11, 10)
    rec = _fake_anki(monkeypatch)
    carded, failed = make_cards(vault, state, store, today, _good_runner, AnkiAuth("k"))
    assert carded == (LESSON,)
    assert failed == ()
    assert rec["added"] == [
        (
            "Self study::Probability",
            [
                (note_guid(LESSON, "Q one?"), "Q one?", "A one"),
                (note_guid(LESSON, "Q two?"), "Q two?", "A two"),
            ],
            ["semai", "lesson::02_events_and_Bayes"],
        )
    ]
    assert len(rec["syncs"]) == 2
    assert len(rec["closed"]) == 1
    assert store.data[ANKI_DONE_PREFIX + LESSON] == "2026-11-10"
    assert store.data[ANKI_UNSYNCED_KEY] == ""

    rec2 = _fake_anki(monkeypatch)
    carded2, failed2 = make_cards(vault, state, store, today, _good_runner, AnkiAuth("k"))
    assert rec2["opened"] == []


def test_make_cards_skips_unticked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _anki_vault(tmp_path, done=False)
    store = FakeStore()
    state = tmp_path / "state"
    today = date(2026, 11, 10)
    rec = _fake_anki(monkeypatch)
    carded, failed = make_cards(vault, state, store, today, _good_runner, AnkiAuth("k"))
    assert carded == ()
    assert failed == ()
    assert rec["opened"] == []


def test_make_cards_first_sync_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _anki_vault(tmp_path)
    store = FakeStore()
    state = tmp_path / "state"
    today = date(2026, 11, 10)
    rec = _fake_anki(monkeypatch, sync_fail_at=1)
    carded, failed = make_cards(vault, state, store, today, _good_runner, AnkiAuth("k"))
    assert carded == ()
    assert failed == (LESSON,)
    assert rec["added"] == []
    assert len(rec["closed"]) == 1
    assert ANKI_DONE_PREFIX + LESSON not in store.data


def test_make_cards_bad_answers_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _anki_vault(tmp_path)
    store = FakeStore()
    state = tmp_path / "state"
    today = date(2026, 11, 10)
    rec = _fake_anki(monkeypatch)
    carded, failed = make_cards(vault, state, store, today, lambda prompt: "not json", AnkiAuth("k"))
    assert carded == ()
    assert failed == (LESSON,)
    assert rec["added"] == []
    assert len(rec["syncs"]) == 1
    assert store.data["anki_gen:2026-11-10:" + LESSON] == "1"


def test_make_cards_retries_unsynced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _anki_vault(tmp_path)
    store = FakeStore()
    state = tmp_path / "state"
    today = date(2026, 11, 10)
    rec = _fake_anki(monkeypatch, sync_fail_at=2)
    carded, failed = make_cards(vault, state, store, today, _good_runner, AnkiAuth("k"))
    assert carded == (LESSON,)
    assert store.data[ANKI_UNSYNCED_KEY] == "1"

    rec2 = _fake_anki(monkeypatch)
    carded2, failed2 = make_cards(vault, state, store, today, _good_runner, AnkiAuth("k"))
    assert carded2 == ()
    assert failed2 == ()
    assert len(rec2["opened"]) == 1
    assert len(rec2["syncs"]) == 1
    assert rec2["added"] == []
    assert store.data[ANKI_UNSYNCED_KEY] == ""


def test_make_cards_reading_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    vault = _anki_vault(
        tmp_path,
        lesson_text=(
            "# PR 02\n\n## Reading\n\n### 1 Events\n\ntext\n\n"
            "### 2 Bayes\n\ntext\n\n## Recall\n\n- Q one?\n\n## Sources\n\n- Ross\n"
        ),
    )
    store = FakeStore()
    state = tmp_path / "state"
    rec = _fake_anki(monkeypatch)
    prompts: list[str] = []

    def runner(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            [
                {"q": "Q one?", "a": "A one"},
                {"q": "What is an event?", "a": "A set", "section": "1 Events"},
                {
                    "q": "State Bayes rule.",
                    "a": "P(A|B) = ...",
                    "section": "2 Bayes",
                },
            ]
        )

    today = date(2026, 11, 10)
    carded, failed = make_cards(
        vault, state, store, today, runner, AnkiAuth("k"), cap=2
    )

    assert carded == (LESSON,)
    assert failed == ()
    assert len(prompts) == 1
    assert "Reading concepts:" in prompts[0]
    assert "1 Events" in prompts[0]
    expected_notes = [
        (note_guid(LESSON, "Q one?"), "Q one?", "A one"),
        (
            note_guid(LESSON, "What is an event?"),
            "What is an event?",
            "A set",
        ),
        (
            note_guid(LESSON, "State Bayes rule."),
            "State Bayes rule.",
            "P(A|B) = ...",
        ),
    ]
    assert rec["added"] == [
        ("Self study::Probability", expected_notes, ["semai", "lesson::02_events_and_Bayes"])
    ]


def test_make_cards_no_recall_no_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _anki_vault(
        tmp_path,
        lesson_text="# PR 02\n\nbody\n\n## Sources\n\n- Ross\n",
    )
    store = FakeStore()
    state = tmp_path / "state"
    rec = _fake_anki(monkeypatch)
    prompts: list[str] = []

    def runner(prompt: str) -> str:
        prompts.append(prompt)
        return "[]"

    today = date(2026, 11, 10)
    carded, failed = make_cards(
        vault, state, store, today, runner, AnkiAuth("k"), cap=2
    )

    assert carded == ()
    assert failed == ()
    assert prompts == []
    assert rec["added"] == []
    assert store.data[ANKI_DONE_PREFIX + LESSON] == "2026-11-10"


def test_make_cards_concept_embeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import json

    EVENTS = "Self study/Probability/concepts/Events.md"
    BAYES = "Self study/Probability/concepts/Bayes.md"

    lesson_text = (
        "# PR 02\n\n## Reading\n\n"
        "![[Self study/Probability/concepts/Events|Events]]\n\n"
        "![[Bayes]]\n\n"
        "![[Self study/Probability/concepts/Missing|Missing]]\n\n"
        "## Recall\n\n- Q one?\n\n## Sources\n\n- Ross\n"
    )
    vault = _anki_vault(tmp_path, lesson_text=lesson_text)
    concepts_dir = vault / "Self study/Probability/concepts"
    concepts_dir.mkdir(parents=True)
    (concepts_dir / "Events.md").write_text(
        "---\ntags:\n  - topic/probability\n---\n# Events\n\nEvent body text\n"
    )
    (concepts_dir / "Bayes.md").write_text(
        "---\ntags:\n  - topic/probability\n---\n# Bayes\n\nBayes body text\n"
    )

    prompts: list[str] = []

    def runner(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            [
                {"q": "Q one?", "a": "A one"},
                {"q": "What is an event?", "a": "A set", "section": "Events"},
                {"q": "State Bayes rule.", "a": "P(A|B)", "section": "Bayes"},
            ]
        )

    store = FakeStore()
    rec = _fake_anki(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="libra.study.cards"):
        carded, failed = make_cards(
            vault,
            tmp_path / "state",
            store,
            date(2026, 11, 10),
            runner,
            AnkiAuth("k"),
            cap=2,
        )

    assert carded == (LESSON,)
    assert failed == ()
    assert "Concept note: Events" in prompts[0]
    assert "Event body text" in prompts[0]
    assert "Concept note: Bayes" in prompts[0]
    assert "topic/probability" not in prompts[0]
    assert "1. Events" in prompts[0]
    assert "2. Bayes" in prompts[0]
    assert rec["added"] == [
        (
            "Self study::Probability",
            [
                (note_guid(LESSON, "Q one?"), "Q one?", "A one"),
                (note_guid(EVENTS, "What is an event?"), "What is an event?", "A set"),
                (note_guid(BAYES, "State Bayes rule."), "State Bayes rule.", "P(A|B)"),
            ],
            ["semai", "lesson::02_events_and_Bayes"],
        )
    ]
    assert store.data[ANKI_DONE_PREFIX + EVENTS] == "2026-11-10"
    assert store.data[ANKI_DONE_PREFIX + BAYES] == "2026-11-10"
    assert "embeds missing concept Self study/Probability/concepts/Missing" in caplog.text
    assert store.data[ANKI_DONE_PREFIX + LESSON] == "2026-11-10"


DSA_NOTE = "Coding Practice/DSA/Two pointers.md"


def _dsa_vault(tmp_path: Path, signals: list[str], extra_reading: str = "") -> Path:
    vault = tmp_path / "vault"
    note = vault / DSA_NOTE
    note.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "---\ntags:\n  - topic/dsa\n---\n# Two pointers\n\n"
        "## Reading\n\n"
        + extra_reading
        + "### Signals\n\n"
        + "".join(f"- {s}\n" for s in signals)
        + "\n## Problem log\n"
    )
    note.write_text(text)
    _write(
        vault,
        date(2026, 11, 9),
        _week(date(2026, 11, 9), {0: ["- [x] DSA: [[Coding Practice/DSA/Two pointers|LC 167 Two Sum II]]"]}),
    )
    return vault


def test_make_cards_dsa_signals_without_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _fake_anki(monkeypatch)
    vault = _dsa_vault(tmp_path, ["Sorted array plus pair sum"])
    store = FakeStore()

    def runner(*args: object, **kwargs: object) -> str:
        raise AssertionError

    carded, failed = make_cards(vault, tmp_path / "state", store, date(2026, 11, 10), runner, AnkiAuth("k"), cap=2)

    F = "Which pattern fits this signal: Sorted array plus pair sum"
    assert carded == (DSA_NOTE,)
    assert failed == ()
    assert rec["added"] == [
        ("Self study::DSA", [(note_guid(DSA_NOTE, F), F, "Two pointers")], ["semai", "lesson::Two_pointers"])
    ]


def test_make_cards_dsa_problem_note_uses_pattern(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _fake_anki(monkeypatch)
    vault = _dsa_vault(tmp_path, ["Sorted array plus pair sum"])
    PROBLEM = "Coding Practice/DSA/problems/LC 167 Two Sum II.md"
    problem_path = vault / PROBLEM
    problem_path.parent.mkdir(parents=True)
    problem_path.write_text(
        "---\ntags:\n  - topic/dsa\npattern: Coding Practice/DSA/Two pointers\n---\n"
        "# LC 167 Two Sum II\n\nStatement text\n"
    )
    _write(
        vault,
        date(2026, 11, 9),
        _week(date(2026, 11, 9), {0: ["- [x] DSA: [[Coding Practice/DSA/problems/LC 167 Two Sum II|LC 167 Two Sum II]]"]}),
    )
    store = FakeStore()
    runner = lambda _: (_ for _ in ()).throw(AssertionError())

    carded, failed = make_cards(vault, tmp_path / "state", store, date(2026, 11, 10), runner, AnkiAuth("k"), cap=2)

    F = "Which pattern fits this signal: Sorted array plus pair sum"
    assert carded == (PROBLEM,)
    assert failed == ()
    assert rec["added"] == [("Self study::DSA", [(note_guid(DSA_NOTE, F), F, "Two pointers")], ["semai", "lesson::LC_167_Two_Sum_II"])]
    assert store.data[ANKI_DONE_PREFIX + PROBLEM] == "2026-11-10"


def test_make_cards_dsa_problem_note_missing_pattern_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    rec = _fake_anki(monkeypatch)
    vault = _dsa_vault(tmp_path, ["Sorted array plus pair sum"])
    PROBLEM = "Coding Practice/DSA/problems/LC 167 Two Sum II.md"
    problem_path = vault / PROBLEM
    problem_path.parent.mkdir(parents=True)
    problem_path.write_text(
        "---\ntags:\n  - topic/dsa\npattern: Coding Practice/DSA/Nope\n---\n"
        "# LC 167 Two Sum II\n\nStatement text\n"
    )
    _write(
        vault,
        date(2026, 11, 9),
        _week(date(2026, 11, 9), {0: ["- [x] DSA: [[Coding Practice/DSA/problems/LC 167 Two Sum II|LC 167 Two Sum II]]"]}),
    )
    store = FakeStore()
    runner = lambda _: (_ for _ in ()).throw(AssertionError())

    with caplog.at_level(logging.WARNING, logger="libra.study.cards"):
        carded, failed = make_cards(vault, tmp_path / "state", store, date(2026, 11, 10), runner, AnkiAuth("k"), cap=2)

    assert carded == ()
    assert failed == (PROBLEM,)
    assert rec["added"] == []
    assert "names missing pattern" in caplog.text
    assert ANKI_DONE_PREFIX + PROBLEM not in store.data


def test_make_cards_dsa_rechecked_each_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _fake_anki(monkeypatch)
    vault = _dsa_vault(tmp_path, ["A"])
    store = FakeStore()

    def runner(*args: object, **kwargs: object) -> str:
        raise AssertionError

    carded, failed = make_cards(vault, tmp_path / "state", store, date(2026, 11, 10), runner, AnkiAuth("k"), cap=2)
    assert carded == (DSA_NOTE,)
    assert failed == ()

    _dsa_vault(tmp_path, ["A", "B"])

    for _ in range(2):
        carded, failed = make_cards(vault, tmp_path / "state", store, date(2026, 11, 10), runner, AnkiAuth("k"), cap=2)
        assert carded == (DSA_NOTE,)
        assert failed == ()
    FA = "Which pattern fits this signal: A"
    FB = "Which pattern fits this signal: B"
    assert rec["added"][-1][1] == [
        (note_guid(DSA_NOTE, FA), FA, "Two pointers"),
        (note_guid(DSA_NOTE, FB), FB, "Two pointers"),
    ]


def test_make_cards_dsa_concept_embed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    rec = _fake_anki(monkeypatch)
    vault = _dsa_vault(tmp_path, ["A"], extra_reading="![[Coding Practice/DSA/concepts/Hash map|Hash map]]\n\n")
    CONCEPT = "Coding Practice/DSA/concepts/Hash map.md"
    concept = vault / CONCEPT
    concept.parent.mkdir(parents=True, exist_ok=True)
    concept.write_text("---\ntags:\n  - topic/dsa\n---\n# Hash map\n\nHash body\n")
    store = FakeStore()
    prompts: list[str] = []

    def runner(prompt: str, **kwargs: object) -> str:
        prompts.append(prompt)
        return json.dumps([{"q": "What is a hash map?", "a": "A table", "section": "Hash map"}])

    day = date(2026, 11, 10)
    carded, failed = make_cards(vault, tmp_path / "state", store, day, runner, AnkiAuth("k"), cap=2)
    FA = "Which pattern fits this signal: A"
    assert carded == (DSA_NOTE,)
    assert failed == ()
    assert len(prompts) == 1
    assert "1. Hash map" in prompts[0]
    assert "Hash body" in prompts[0]
    assert "Questions:" not in prompts[0]
    assert rec["added"][-1][1] == [
        (note_guid(DSA_NOTE, FA), FA, "Two pointers"),
        (note_guid(CONCEPT, "What is a hash map?"), "What is a hash map?", "A table"),
    ]
    assert store.data[ANKI_DONE_PREFIX + CONCEPT] == "2026-11-10"

    carded, failed = make_cards(vault, tmp_path / "state", store, day, runner, AnkiAuth("k"), cap=2)
    assert carded == (DSA_NOTE,)
    assert failed == ()
    assert len(prompts) == 1
    assert rec["added"][-1][1] == [(note_guid(DSA_NOTE, FA), FA, "Two pointers")]


def test_make_cards_dsa_empty_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _fake_anki(monkeypatch)
    vault = _dsa_vault(tmp_path, [])

    def runner(*args: object, **kwargs: object) -> str:
        raise AssertionError

    carded, failed = make_cards(vault, tmp_path / "state", FakeStore(), date(2026, 11, 10), runner, AnkiAuth("k"), cap=2)
    assert (carded, failed) == ((), ())
    assert rec["added"] == []


def test_make_cards_zero_added_not_carded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _fake_anki(monkeypatch, added=0)
    vault = _dsa_vault(tmp_path, ["A"])
    def runner(prompt: str, **kwargs: object) -> str:
        raise AssertionError
    store = FakeStore()
    carded, failed = make_cards(vault, tmp_path / "state", store, date(2026, 11, 10), runner, AnkiAuth("k"), cap=2)
    assert (carded, failed) == ((), ())
    assert len(rec["added"]) == 1
    assert len(rec["syncs"]) == 1
    assert store.data.get(ANKI_UNSYNCED_KEY, "") == ""


@pytest.mark.parametrize("mode", ["raise", "bad_json", "cap"])
def test_make_cards_dsa_signals_survive_card_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    rec = _fake_anki(monkeypatch)
    vault = _dsa_vault(tmp_path, ["A"], extra_reading="![[Coding Practice/DSA/concepts/Hash map|Hash map]]\n\n")
    concept_path = vault / "Coding Practice/DSA/concepts/Hash map.md"
    concept_path.parent.mkdir(parents=True, exist_ok=True)
    concept_path.write_text("---\ntags:\n  - topic/dsa\n---\n# Hash map\n\nHash body\n")

    def runner(prompt: str, **kwargs: object) -> str:
        if mode == "raise":
            raise LessonError("boom")
        if mode == "bad_json":
            return "not json"
        raise AssertionError()

    cap = 0 if mode == "cap" else 2
    store = FakeStore()
    carded, failed = make_cards(vault, tmp_path / "state", store, date(2026, 11, 10), runner, AnkiAuth("k"), cap=cap)
    FA = "Which pattern fits this signal: A"
    assert carded == (DSA_NOTE,)
    assert failed == ()
    assert rec["added"][-1][1] == [(note_guid(DSA_NOTE, FA), FA, "Two pointers")]
    assert ANKI_DONE_PREFIX + "Coding Practice/DSA/concepts/Hash map.md" not in store.data


def test_make_cards_carded_concept_not_repeated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    EVENTS = "Self study/Probability/concepts/Events.md"

    lesson_text = (
        "# PR 02\n\n## Reading\n\n"
        "![[Self study/Probability/concepts/Events|Events]]\n\n"
        "## Recall\n\n- Q one?\n\n## Sources\n\n- Ross\n"
    )
    vault = _anki_vault(tmp_path, lesson_text=lesson_text)
    concepts_dir = vault / "Self study/Probability/concepts"
    concepts_dir.mkdir(parents=True)
    (concepts_dir / "Events.md").write_text(
        "---\ntags:\n  - topic/probability\n---\n# Events\n\nEvent body text\n"
    )

    prompts: list[str] = []

    def runner(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps([{"q": "Q one?", "a": "A one"}])

    store = FakeStore()
    store.data[ANKI_DONE_PREFIX + EVENTS] = "2026-11-09"
    rec = _fake_anki(monkeypatch)
    carded, failed = make_cards(
        vault,
        tmp_path / "state",
        store,
        date(2026, 11, 10),
        runner,
        AnkiAuth("k"),
        cap=2,
    )

    assert carded == (LESSON,)
    assert failed == ()
    assert "Concept note: Events" in prompts[0]
    assert "Reading concepts:" not in prompts[0]
    assert rec["added"][0][1] == [(note_guid(LESSON, "Q one?"), "Q one?", "A one")]
    assert store.data[ANKI_DONE_PREFIX + EVENTS] == "2026-11-09"
    assert store.data[ANKI_DONE_PREFIX + LESSON] == "2026-11-10"


def test_make_cards_marks_concept_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib
    import json

    EVENTS = "Self study/Probability/concepts/Events.md"
    lesson_text = (
        "# PR 02\n\n## Reading\n\n"
        "![[Self study/Probability/concepts/Events|Events]]\n\n"
        "## Recall\n\n- Q one?\n\n## Sources\n\n- Ross\n"
    )
    vault = _anki_vault(tmp_path, lesson_text=lesson_text)
    concepts_dir = vault / "Self study/Probability/concepts"
    concepts_dir.mkdir(parents=True)
    (concepts_dir / "Events.md").write_text(
        "---\ntags:\n  - topic/probability\n---\n# Events\n\nEvent body text\n"
    )
    BODY_KEY = ANKI_BODY_PREFIX + hashlib.sha256(
        "# Events\n\nEvent body text".encode("utf-8")
    ).hexdigest()

    prompts: list[str] = []

    def runner(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            [
                {"q": "Q one?", "a": "A one"},
                {"q": "What is an event?", "a": "A set", "section": "Events"},
            ]
        )

    store = FakeStore()
    _fake_anki(monkeypatch)
    carded, failed = make_cards(
        vault,
        tmp_path / "state",
        store,
        date(2026, 11, 10),
        runner,
        AnkiAuth("k"),
        cap=2,
    )

    assert carded == (LESSON,)
    assert failed == ()
    assert store.data[ANKI_DONE_PREFIX + EVENTS] == "2026-11-10"
    assert store.data[BODY_KEY] == "2026-11-10"


def test_make_cards_renamed_concept_not_recarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json

    EVENTS = "Self study/Probability/concepts/Events.md"
    lesson_text = (
        "# PR 02\n\n## Reading\n\n"
        "![[Self study/Probability/concepts/Events|Events]]\n\n"
        "## Recall\n\n- Q one?\n\n## Sources\n\n- Ross\n"
    )
    vault = _anki_vault(tmp_path, lesson_text=lesson_text)
    concepts_dir = vault / "Self study/Probability/concepts"
    concepts_dir.mkdir(parents=True)
    (concepts_dir / "Events.md").write_text(
        "---\ntags:\n  - topic/probability\n---\n# Events\n\nEvent body text\n"
    )
    BODY_KEY = ANKI_BODY_PREFIX + hashlib.sha256(
        "# Events\n\nEvent body text".encode("utf-8")
    ).hexdigest()

    prompts: list[str] = []

    def runner(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps([{"q": "Q one?", "a": "A one"}])

    store = FakeStore()
    store.data[BODY_KEY] = "2026-11-09"
    rec = _fake_anki(monkeypatch)
    carded, failed = make_cards(
        vault,
        tmp_path / "state",
        store,
        date(2026, 11, 10),
        runner,
        AnkiAuth("k"),
        cap=2,
    )

    assert carded == (LESSON,)
    assert failed == ()
    assert "Reading concepts:" not in prompts[0]
    assert "Concept note: Events" in prompts[0]
    assert rec["added"][0][1] == [(note_guid(LESSON, "Q one?"), "Q one?", "A one")]
    assert ANKI_DONE_PREFIX + EVENTS not in store.data
    assert store.data[BODY_KEY] == "2026-11-09"


def test_make_cards_concept_label_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import json

    EVENTS = "Self study/Probability/concepts/Events.md"

    lesson_text = (
        "# PR 02\n\n## Reading\n\n### Events\n\ntext\n\n"
        "![[Self study/Probability/concepts/Events|Events]]\n\n"
        "## Recall\n\n- Q one?\n\n## Sources\n\n- Ross\n"
    )
    vault = _anki_vault(tmp_path, lesson_text=lesson_text)
    concepts_dir = vault / "Self study/Probability/concepts"
    concepts_dir.mkdir(parents=True)
    (concepts_dir / "Events.md").write_text(
        "---\ntags:\n  - topic/probability\n---\n# Events\n\nEvent body text\n"
    )

    def runner(prompt: str) -> str:
        return json.dumps(
            [
                {"q": "Q one?", "a": "A one"},
                {"q": "What is an event?", "a": "A set", "section": "Events"},
            ]
        )

    store = FakeStore()
    rec = _fake_anki(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="libra.study.cards"):
        carded, failed = make_cards(
            vault,
            tmp_path / "state",
            store,
            date(2026, 11, 10),
            runner,
            AnkiAuth("k"),
            cap=2,
        )

    assert carded == (LESSON,)
    assert failed == ()
    assert rec["added"] == [
        (
            "Self study::Probability",
            [
                (note_guid(LESSON, "Q one?"), "Q one?", "A one"),
                (
                    note_guid(LESSON, "What is an event?"),
                    "What is an event?",
                    "A set",
                ),
            ],
            ["semai", "lesson::02_events_and_Bayes"],
        )
    ]
    assert ANKI_DONE_PREFIX + EVENTS not in store.data
    assert "repeats" in caplog.text
    assert store.data[ANKI_DONE_PREFIX + LESSON] == "2026-11-10"


def test_json_meta_store_round_trip(tmp_path: Path) -> None:
    path = meta_path(tmp_path)
    store = JsonMetaStore(path)
    store.meta_set("alpha", "one")
    store.meta_set("beta", "two")

    fresh = JsonMetaStore(path)
    assert fresh.meta_get("alpha") == "one"
    assert fresh.meta_get("beta") == "two"

    parsed = json.loads(path.read_text())
    assert parsed == {"alpha": "one", "beta": "two"}


def test_json_meta_store_missing_file_is_empty(tmp_path: Path) -> None:
    store = JsonMetaStore(meta_path(tmp_path))
    assert store.meta_get("alpha", "fallback") == "fallback"


def test_json_meta_store_no_persist_writes_nothing(tmp_path: Path) -> None:
    path = meta_path(tmp_path)
    store = JsonMetaStore(path, persist=False)
    store.meta_set("alpha", "one")

    assert store.meta_get("alpha") == "one"
    assert not path.exists()


@pytest.mark.parametrize(
    "content",
    ["not json", '["just", "a", "list"]', '{"alpha": 42}'],
)
def test_json_meta_store_rejects_malformed(tmp_path: Path, content: str) -> None:
    path = meta_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)

    with pytest.raises(MetaStoreError):
        JsonMetaStore(path)


def test_preview_cards_recall_lesson_needs_claude(tmp_path: Path) -> None:
    vault = _anki_vault(tmp_path)
    store = FakeStore()

    previews = preview_cards(vault, store, date(2026, 11, 10))

    assert len(previews) == 1
    preview = previews[0]
    assert preview.path == LESSON
    assert preview.source == LESSON
    assert preview.fronts == ()
    assert preview.needs_claude is True
    assert store.data == {}


def test_preview_cards_dsa_signals_without_claude(tmp_path: Path) -> None:
    vault = _dsa_vault(tmp_path, ["Sorted array plus pair sum"])
    store = FakeStore()

    previews = preview_cards(vault, store, date(2026, 11, 10))

    assert len(previews) == 1
    preview = previews[0]
    assert preview.path == DSA_NOTE
    assert len(preview.fronts) == 1
    assert "Sorted array plus pair sum" in preview.fronts[0]
    assert preview.needs_claude is False
    assert store.data == {}


def test_preview_cards_skips_carded_lesson(tmp_path: Path) -> None:
    vault = _anki_vault(tmp_path)
    store = FakeStore()
    store.data[ANKI_DONE_PREFIX + LESSON] = "2026-11-10"

    assert preview_cards(vault, store, date(2026, 11, 10)) == []
