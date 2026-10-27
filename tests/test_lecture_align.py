"""Tests for libra.lecture_align (ADR-0041 P2)."""

from __future__ import annotations

import math

import pytest

from libra.lecture_align import (
    PAGE_MAX_DF,
    WEAK_SCORE,
    Anchor,
    Chapter,
    TermSpace,
    Unit,
    Window,
    align,
    align_track,
    chapter_links,
    clean_text,
    deck_order,
    spans_summary,
    tokenize,
    transcript_windows,
    unit_vectors,
)


def test_tokenize_filters_and_bigrams() -> None:
    result = tokenize("the queues arrive lecture servers")
    assert result == ["queue", "arrive", "server", "queue arrive", "arrive server"]


def test_clean_text_removes_noise() -> None:
    text = "Intro $x^2$ middle $$\\frac{a}{b}$$ end\nDiagram description line\nword theta and \\alpha here"
    result = clean_text(text)
    assert "$" not in result
    assert "frac" not in result
    assert "alpha" not in result
    assert "diagram description line" not in result
    assert "theta" not in result
    assert "Intro" in result
    assert "middle" in result
    assert "word" in result
    assert "here" in result


@pytest.mark.parametrize(
    ("rel", "track", "expected"),
    [
        ("C/Slides/Lec03 Queueing Notes", "lecture", (3, 1)),
        ("C/Slides/Lec7-Addendum.pdf", "lecture", (7, 2)),
        ("C/Slides/Lec13Handout.pdf", "lecture", (13, 3)),
        ("C/Slides/lecture5-dc.pdf", "lecture", (5, 0)),
        ("C/Slides/Lecture 9 - Bayes2.pdf", "lecture", (9, 0)),
        ("C/Slides/midterm review.pdf", "lecture", None),
        ("C/Discussion/ECE 108 - Discussion 2.pdf", "discussion", (2, 0)),
        ("C/Discussion/Discussion Section 10-07.pdf", "discussion", None),
    ],
)
def test_deck_order(rel: str, track: str, expected: tuple[int, int] | None) -> None:
    assert deck_order(rel, track) == expected


def test_transcript_windows() -> None:
    segments = [
        {"start": 0, "end": 100, "text": "a"},
        {"start": 100, "end": 200, "text": "b"},
        {"start": 200, "end": 300, "text": "c"},
        {"start": 300, "end": 400, "text": "d"},
        {"start": 400, "end": 500, "text": "e"},
    ]
    assert transcript_windows(segments, window_s=250) == [
        Window(0, 300, "a b c"),
        Window(300, 500, "d e"),
    ]
    assert transcript_windows([]) == []


def test_align_monotone_path() -> None:
    scores = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 0]]
    assert align(scores, [None] * len(scores)) == [0, 1, 2, 2]


def test_align_row_zero_counted_once() -> None:
    scores = [[0, 3], [2, 0]]
    assert align(scores, [None] * len(scores)) == [1, 1]


def test_align_anchor_honoured() -> None:
    assert align([[5, 0], [5, 0]], [frozenset({1}), None]) == [1, 1]


def test_align_contradictory_anchors_warns(caplog: pytest.LogCaptureFixture) -> None:
    result = align([[1, 0], [1, 0]], [frozenset({1}), frozenset({0})])
    assert result == [0, 0]
    assert "contradict" in caplog.text


def test_align_empty() -> None:
    assert align([], []) == []


def _two_units() -> list[Unit]:
    return [
        Unit(
            "C/Slides/lec1.pdf",
            (1, 0),
            {1: "queue arrival poisson", 2: "waiting server utilization"},
            (),
        ),
        Unit(
            "C/Slides/lec2.pdf",
            (2, 0),
            {1: "routing dijkstra shortest", 2: "distance vector bellman"},
            (),
        ),
    ]


def _two_transcripts() -> list[tuple[str, list[Window]]]:
    return [
        ("2026-10-01", [Window(0, 300, "queue arrival poisson waiting server")]),
        ("2026-10-02", [Window(0, 300, "routing dijkstra shortest distance vector")]),
    ]


def _vectors_for(units: list[Unit]) -> tuple[TermSpace, list]:
    docs = [tokenize(text) for unit in units for text in unit.pages.values()]
    space = TermSpace.build(docs, PAGE_MAX_DF)
    return space, [unit_vectors(unit, space) for unit in units]


def test_align_track_happy_path() -> None:
    units = _two_units()
    space, vectors = _vectors_for(units)
    result = align_track(_two_transcripts(), units, vectors, space, [])
    day1 = result["2026-10-01"]
    day2 = result["2026-10-02"]
    assert len(day1) == 1
    assert day1[0]["deck"] == "C/Slides/lec1.pdf"
    assert day1[0]["status"] == "matched"
    assert day1[0]["score"] > WEAK_SCORE
    assert day1[0]["pages"]
    assert day1[0]["pages"] == sorted(day1[0]["pages"])
    assert "candidate" not in day1[0]
    assert len(day2) == 1
    assert day2[0]["deck"] == "C/Slides/lec2.pdf"


def test_align_track_anchor_confirms() -> None:
    units = _two_units()
    space, vectors = _vectors_for(units)
    anchors = [Anchor("2026-10-01", 0.0, math.inf, 1)]
    result = align_track(_two_transcripts(), units, vectors, space, anchors)
    assert result["2026-10-01"][0]["deck"] == "C/Slides/lec2.pdf"
    assert result["2026-10-01"][0]["status"] == "confirmed"
    assert result["2026-10-02"][0]["deck"] == "C/Slides/lec2.pdf"


def test_align_track_unmatched_words() -> None:
    units = _two_units()
    space, vectors = _vectors_for(units)
    transcripts = [("2026-10-03", [Window(0, 100, "banana orange mango")])]
    result = align_track(transcripts, units, vectors, space, [])
    spans = result["2026-10-03"]
    assert len(spans) == 1
    assert spans[0]["deck"] is None
    assert spans[0]["candidate"] in {"C/Slides/lec1.pdf", "C/Slides/lec2.pdf"}
    assert spans[0]["status"] == "unmatched"


def test_align_track_no_units() -> None:
    transcripts = [
        ("2026-10-01", [Window(0, 100, "a b c")]),
        ("2026-10-02", []),
    ]
    result = align_track(transcripts, [], [], TermSpace({}), [])
    day1 = result["2026-10-01"]
    day2 = result["2026-10-02"]
    assert len(day1) == 1
    assert day1[0] == {
        "from_s": 0.0,
        "to_s": 100.0,
        "deck": None,
        "candidate": None,
        "status": "unmatched",
        "score": 0.0,
        "pages": [],
        "also": [],
        "terms": [],
    }
    assert day2 == []


def test_chapter_links() -> None:
    queue_chapter = Chapter(
        "C/Textbooks/b.pdf",
        "Queues",
        1,
        9,
        tuple(tokenize("queue arrival poisson waiting")),
    )
    routing_chapter = Chapter(
        "C/Textbooks/c.pdf",
        "Routing",
        1,
        7,
        tuple(tokenize("routing dijkstra shortest distance")),
    )
    coding_chapter = Chapter(
        "C/Textbooks/d.pdf",
        "Coding",
        1,
        5,
        tuple(tokenize("parity hamming erasure redundancy")),
    )
    ethernet_chapter = Chapter(
        "C/Textbooks/e.pdf",
        "Ethernet",
        1,
        6,
        tuple(tokenize("collision aloha backoff carrier")),
    )
    unit = Unit(
        "C/Slides/lec1.pdf",
        (1, 0),
        {1: "queue arrival poisson waiting server"},
        (),
    )
    links = chapter_links(
        [unit], [queue_chapter, routing_chapter, coding_chapter, ethernet_chapter]
    )
    assert links["C/Slides/lec1.pdf"][0]["title"] == "Queues"
    assert chapter_links([unit], []) == {}


def test_spans_summary() -> None:
    spans = {
        "a": [{"status": "matched"}, {"status": "unmatched"}],
        "b": [{"status": "confirmed"}],
    }
    assert spans_summary(spans) == (2, 1)
