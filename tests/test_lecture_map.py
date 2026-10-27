"""Tests for libra.lecture_map (ADR-0041 P2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from libra.config import Settings
from libra import lecture_map
from libra.textbooks import BookEntry, BookMap
from test_notes_sources import make_settings

LEC1_PAGES = {1: "Queue arrival poisson process", 2: "Waiting server utilization factor"}
LEC2_PAGES = {1: "Routing dijkstra shortest path", 2: "Distance vector bellman ford"}

LEC1_DECK = "ECE 1/Slides/lec1.pdf"
LEC2_DECK = "ECE 1/Slides/lec2.pdf"
CH1_DECK = "ECE 1/Slides/lec1 copy.pdf"


def _write_pdf(path: Path, content: bytes = b"%PDF-1.4\nfake") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_transcript(vault: Path, course: str, day: str, text: str) -> None:
    transcript_dir = vault / course / "Transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    segment = [{"start": 0.0, "end": 300.0, "text": text}]
    (transcript_dir / f"{day}.json").write_text(json.dumps(segment), encoding="utf-8")


def _make_pages(pages_by_rel: dict[str, dict[int, str]]) -> Any:
    def _cached_pages(settings: Settings, source: Any) -> dict[int, str]:
        return pages_by_rel.get(source.rel, {})

    return _cached_pages


def _setup_course(tmp_path: Path) -> Settings:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    assert vault is not None
    _write_pdf(vault / LEC1_DECK, b"%PDF-1.4\nlec1")
    _write_pdf(vault / LEC2_DECK, b"%PDF-1.4\nlec2")
    _write_transcript(vault, "ECE 1", "2026-10-01", "Queue arrival poisson waiting server")
    _write_transcript(vault, "ECE 1", "2026-10-02", "Routing dijkstra shortest distance vector")
    return settings


def test_write_maps_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from libra import lecture_map

    settings = _setup_course(tmp_path)
    monkeypatch.setattr(lecture_map, "cached_pages", _make_pages({LEC1_DECK: LEC1_PAGES, LEC2_DECK: LEC2_PAGES}))

    written = lecture_map.write_maps(settings)

    assert written == [settings.obsidian_academic_vault_dir / "Tools/maps/ECE 1.json"]
    data = json.loads(written[0].read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["course"] == "ECE 1"
    assert isinstance(data["inputs"], str)
    assert len(data["transcripts"]) == 2
    assert all(t["kind"] == "lecture" for t in data["transcripts"])
    assert data["transcripts"][0]["id"] == "2026-10-01"
    assert data["transcripts"][0]["spans"][0]["deck"] == LEC1_DECK
    assert data["transcripts"][0]["spans"][0]["status"] == "matched"
    assert data["transcripts"][1]["spans"][0]["deck"] == LEC2_DECK
    assert len(data["decks"]) == 2
    decks_by_rel = {d["rel"]: d for d in data["decks"]}
    assert decks_by_rel[LEC1_DECK]["transcripts"] == ["2026-10-01"]
    assert decks_by_rel[LEC2_DECK]["transcripts"] == ["2026-10-02"]


def test_write_maps_unchanged_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from libra import lecture_map

    settings = _setup_course(tmp_path)
    monkeypatch.setattr(lecture_map, "cached_pages", _make_pages({LEC1_DECK: LEC1_PAGES, LEC2_DECK: LEC2_PAGES}))

    first = lecture_map.write_maps(settings)
    assert first
    built_before = json.loads(first[0].read_text(encoding="utf-8"))["built"]
    inputs_before = json.loads(first[0].read_text(encoding="utf-8"))["inputs"]

    second = lecture_map.write_maps(settings)
    assert second == []
    assert json.loads(first[0].read_text(encoding="utf-8"))["built"] == built_before

    vault = settings.obsidian_academic_vault_dir
    _write_transcript(vault, "ECE 1", "2026-10-03", "Queue arrival poisson waiting server")

    third = lecture_map.write_maps(settings)
    assert third == first
    assert json.loads(first[0].read_text(encoding="utf-8"))["inputs"] != inputs_before


def test_write_maps_duplicates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from libra import lecture_map

    settings = _setup_course(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    _write_pdf(vault / CH1_DECK, b"%PDF-1.4\nlec1")
    monkeypatch.setattr(
        lecture_map,
        "cached_pages",
        _make_pages({LEC1_DECK: LEC1_PAGES, CH1_DECK: LEC1_PAGES, LEC2_DECK: LEC2_PAGES}),
    )

    written = lecture_map.write_maps(settings)

    data = json.loads(written[0].read_text(encoding="utf-8"))
    decks_by_rel = {d["rel"]: d for d in data["decks"]}
    assert decks_by_rel[LEC1_DECK]["duplicates"] == [CH1_DECK]
    assert CH1_DECK not in decks_by_rel


def test_write_maps_confirmed_anchor_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from libra import lecture_map

    settings = _setup_course(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    confirmed_dir = vault / "Tools/maps"
    confirmed_dir.mkdir(parents=True, exist_ok=True)
    (confirmed_dir / "ECE 1.confirmed.json").write_text(
        json.dumps(
            {
                "version": 1,
                "confirmed": [
                    {"transcript": "2026-10-01", "deck": LEC2_DECK},
                    {"transcript": "2099-01-01", "deck": LEC1_DECK},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(lecture_map, "cached_pages", _make_pages({LEC1_DECK: LEC1_PAGES, LEC2_DECK: LEC2_PAGES}))

    caplog.set_level("WARNING")
    written = lecture_map.write_maps(settings)

    data = json.loads(written[0].read_text(encoding="utf-8"))
    transcript = next(t for t in data["transcripts"] if t["id"] == "2026-10-01")
    assert transcript["spans"][0]["deck"] == LEC2_DECK
    assert transcript["spans"][0]["status"] == "confirmed"
    assert any("2099-01-01" in record.message for record in caplog.records)


def test_write_maps_discussion_unmatched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from libra import lecture_map

    settings = _setup_course(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    _write_transcript(vault, "ECE 1", "2026-10-03-DI", "Unrelated discussion words")
    monkeypatch.setattr(lecture_map, "cached_pages", _make_pages({LEC1_DECK: LEC1_PAGES, LEC2_DECK: LEC2_PAGES}))

    written = lecture_map.write_maps(settings)

    data = json.loads(written[0].read_text(encoding="utf-8"))
    disc = next(t for t in data["transcripts"] if t["id"] == "2026-10-03-DI")
    assert disc["kind"] == "discussion"
    assert len(disc["spans"]) == 1
    assert disc["spans"][0]["deck"] is None
    assert disc["spans"][0]["candidate"] is None
    assert disc["spans"][0]["status"] == "unmatched"


def _fake_load_cached_map(book_map: BookMap | None) -> Any:
    def _load(cache_file: Path, pdf_path: Path) -> BookMap | None:
        return book_map

    return _load


def _fake_pdf_page_texts(texts: list[str]) -> Any:
    def _page_texts(path: Path) -> list[str]:
        return texts

    return _page_texts


def test_write_maps_chapters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from libra import lecture_map

    settings = _setup_course(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    book_rel = "ECE 1/Textbooks/book.pdf"
    _write_pdf(vault / book_rel)
    monkeypatch.setattr(lecture_map, "cached_pages", _make_pages({LEC1_DECK: LEC1_PAGES, LEC2_DECK: LEC2_PAGES}))

    pages_texts = [
        "queue arrival poisson waiting server",
        "routing dijkstra shortest distance vector",
        "parity hamming erasure redundancy",
        "collision aloha backoff carrier",
    ]
    book_map = BookMap(
        title="Book",
        authors="Author",
        edition="1",
        year=2026,
        pages=4,
        searchable=True,
        complete=True,
        entries=(
            BookEntry("Queues", 1, 1, ()),
            BookEntry("Routing", 2, 2, ()),
            BookEntry("Coding", 3, 3, ()),
            BookEntry("Ethernet", 4, 4, ()),
        ),
    )
    monkeypatch.setattr(lecture_map, "load_cached_map", _fake_load_cached_map(book_map))
    monkeypatch.setattr(lecture_map, "pdf_page_texts", _fake_pdf_page_texts(pages_texts))

    written = lecture_map.write_maps(settings)

    data = json.loads(written[0].read_text(encoding="utf-8"))
    decks_by_rel = {d["rel"]: d for d in data["decks"]}
    assert decks_by_rel[LEC1_DECK]["chapters"][0]["title"] == "Queues"
    assert decks_by_rel[LEC2_DECK]["chapters"][0]["title"] == "Routing"

    monkeypatch.setattr(lecture_map, "load_cached_map", _fake_load_cached_map(None))
    (settings.state_dir / "lecture_reads" / "books").mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "lecture_reads" / "books" / "changed.json").write_text("{}")
    lecture_map.write_maps(settings)
    data_none = json.loads(written[0].read_text(encoding="utf-8"))
    decks_none = {d["rel"]: d for d in data_none["decks"]}
    assert decks_none[LEC1_DECK]["chapters"] == []


def test_course_names(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    assert vault is not None

    (vault / "Good").mkdir()
    (vault / "Good" / "Transcripts").mkdir()
    (vault / "Tools").mkdir()
    (vault / "Tools" / "Transcripts").mkdir()
    (vault / "Personal").mkdir()
    (vault / "Personal" / "Transcripts").mkdir()
    (vault / ".hidden").mkdir()
    (vault / ".hidden" / "Transcripts").mkdir()
    (vault / "NoTranscripts").mkdir()

    assert lecture_map.course_names(vault) == ["Good"]


def test_write_maps_vault_none(tmp_path: Path) -> None:
    settings = Settings.load({"SEMAI_STATE_DIR": str(tmp_path / "state")})
    assert settings.obsidian_academic_vault_dir is None
    assert lecture_map.write_maps(settings) == []


@pytest.mark.parametrize("error", [OSError("simulated failure"), KeyError("anchor")])
def test_write_maps_per_course_failure(
    tmp_path: Path,
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from libra import lecture_map

    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    assert vault is not None

    pages_by_rel: dict[str, object] = {}
    for course in ("Course A", "Course B"):
        _write_transcript(vault, course, "2026-10-01", "Queue arrival poisson waiting server")
        pages_rel = f"{course}/Slides/lec1.pdf"
        _write_pdf(vault / pages_rel)
        pages_by_rel[pages_rel] = LEC1_PAGES
    monkeypatch.setattr(lecture_map, "cached_pages", _make_pages(pages_by_rel))

    real_build_course_map = lecture_map.build_course_map

    def _flaky_build(settings: Settings, course: str, inputs: str) -> dict[str, Any] | None:
        if course == "Course A":
            raise error
        return real_build_course_map(settings, course, inputs)

    monkeypatch.setattr(lecture_map, "build_course_map", _flaky_build)

    caplog.set_level("WARNING")
    written = lecture_map.write_maps(settings)

    assert len(written) == 1
    assert written[0].name == "Course B.json"

    course_a_records = [
        record for record in caplog.records if "Course A" in record.message
    ]
    assert course_a_records
    assert all(record.exc_info is not None for record in course_a_records)
