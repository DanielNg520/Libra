from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from libra import sources
from libra.sources import SourceFile, split_entry
from libra.textbooks import BookEntry, BookMap, BookMapError
from libra import lecture_docs

from test_notes_sources import _FakeClock, _index, _write, fake_chat, make_settings  # noqa: F401


def _range_render(pngs: list[bytes]) -> tuple[Callable, list[tuple[int, int] | None]]:
    ranges: list[tuple[int, int] | None] = []

    def fake_render(
        kind: str,
        srcs: list[Path],
        workdir: Path,
        page_range: tuple[int, int] | None = None,
    ) -> list[tuple[str, bytes]]:
        ranges.append(page_range)
        return [("image/png", p) for p in pngs]

    return fake_render, ranges


def _book(title: str, entries: tuple[BookEntry, ...]) -> BookMap:
    return BookMap(title, "A", None, None, 700, True, True, entries)


def test_split_entry() -> None:
    assert split_entry("x.pdf") == ("x.pdf", None)
    assert split_entry("x.pdf#pages=7-9") == ("x.pdf", (7, 9))
    with pytest.raises(ValueError):
        split_entry("x.pdf#pages=5-2")
    with pytest.raises(ValueError):
        split_entry("x.pdf#pages=0-3")
    with pytest.raises(ValueError):
        split_entry("x.pdf#pages=a-b")


def test_source_file_entry() -> None:
    assert SourceFile("x.pdf", "doc", 1, 2).entry == "x.pdf"
    assert SourceFile("x.pdf", "doc", 1, 2, pages=(5, 9)).entry == "x.pdf#pages=5-9"


def test_expand_books_maps_long_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    course_dir = settings.obsidian_academic_vault_dir / "ECE 271A"
    _write(
        course_dir / "Textbooks" / "book.pdf",
        b"%PDF-1.7 book",
    )
    _write(course_dir / "slides.pdf", b"%PDF-1.7 slides")
    _write(course_dir / "notes.md", "# n")

    listing = sources.list_sources(settings, "ECE 271A")
    counted: list[str] = []

    def fake_pdf_page_count(path: Path) -> int:
        counted.append(path.name)
        if path.name == "book.pdf":
            return 700
        return 20

    sha_calls = 0

    def fake_sha256_file(path: Path) -> str:
        nonlocal sha_calls
        sha_calls += 1
        return "sha-book"

    mapped = _book(
        "Pattern Things",
        (
            BookEntry("Intro", 11, 30, ()),
            BookEntry("Regression", 31, 89, ("Linear", "Bayes")),
        ),
    )
    check_calls: list[dict[str, Any]] = []

    def fake_book_map(settings: Any, path: Path, sha: str) -> BookMap:
        return mapped

    def fake_check_copies(settings: Any, books: list[SourceFile], *, linked: bool, delete: bool) -> list[str]:
        check_calls.append({"linked": linked, "delete": delete})
        return []

    monkeypatch.setattr(sources, "pdf_page_count", fake_pdf_page_count)
    monkeypatch.setattr(sources, "sha256_file", fake_sha256_file)
    monkeypatch.setattr(sources, "book_map", fake_book_map)
    monkeypatch.setattr(sources, "check_copies", fake_check_copies)

    entries, notices = sources.expand_books(settings, listing)

    assert counted == ["book.pdf"]
    assert [(e.rel, e.pages, e.label) for e in entries] == [
        ("ECE 271A/Textbooks/book.pdf", (11, 30), "Pattern Things, Intro"),
        ("ECE 271A/Textbooks/book.pdf", (31, 89), "Pattern Things, Regression (Linear; Bayes)"),
        ("ECE 271A/notes.md", None, ""),
        ("ECE 271A/slides.pdf", None, ""),
    ]
    assert notices == {}
    assert _index(settings)["ECE 271A/Textbooks/book.pdf"][2:] == ["sha-book", ""]
    assert sha_calls == 1
    assert check_calls == []

    entries, notices = sources.expand_books(settings, listing)
    assert sha_calls == 1


def test_expand_books_prunes_stale_ranges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    book_dir = settings.obsidian_academic_vault_dir / "ECE 271A" / "Textbooks"
    book_dir.mkdir(parents=True)
    (book_dir / "book.pdf").write_bytes(b"%PDF-1.7 book")

    listing = sources.list_sources(settings, "ECE 271A")

    book = "ECE 271A/Textbooks/book.pdf"
    other = "ECE 271A/Textbooks/other.pdf#pages=1-5"

    def seed() -> None:
        sources.save_checkpoint(
            settings.state_dir / lecture_docs.READS_DIR / sources.INDEX_NAME,
            {
                "version": 1,
                "files": {
                    f"{book}#pages=11-30": [1, 2, "sha", "k"],
                    f"{book}#pages=11-40": [1, 2, "sha", "k"],
                    other: [1, 2, "sha", "k"],
                },
            },
        )

    current_map = [_book("T", (BookEntry("Intro", 11, 30, ()), BookEntry("Rest", 31, 89, ())))]

    monkeypatch.setattr(sources, "pdf_page_count", lambda path: 700)
    monkeypatch.setattr(sources, "sha256_file", lambda path: "sha-book")
    monkeypatch.setattr(sources, "check_copies", lambda settings, books, *, linked, delete: [])
    monkeypatch.setattr(sources, "book_map", lambda settings, path, sha: current_map[0])

    seed()
    sources.expand_books(settings, listing)
    index = _index(settings)
    assert f"{book}#pages=11-30" in index
    assert other in index
    assert f"{book}#pages=11-40" not in index

    current_map[0] = _book("T", ())
    seed()
    sources.expand_books(settings, listing)
    index = _index(settings)
    assert f"{book}#pages=11-30" in index
    assert f"{book}#pages=11-40" in index
    assert other in index


def test_expand_books_skips_with_notice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    course_dir = settings.obsidian_academic_vault_dir / "ECE 271A"
    course_dir.mkdir(parents=True)
    _write(
        course_dir / "Textbooks" / "a.pdf",
        b"%PDF-1.7 a",
    )
    _write(
        course_dir / "Textbooks" / "b.pdf",
        b"%PDF-1.7 b",
    )

    listing = sources.list_sources(settings, "ECE 271A")

    def fake_pdf_page_count(path: Path) -> int:
        return 700

    def fake_sha256_file(path: Path) -> str:
        return "sha"

    def fake_book_map(settings: Any, path: Path, sha: str) -> BookMap:
        if path.name == "a.pdf":
            raise BookMapError("bad")
        return _book("Empty", ())

    check_calls: list[dict[str, Any]] = []

    def fake_check_copies(settings: Any, books: list[SourceFile], *, linked: bool, delete: bool) -> list[str]:
        check_calls.append({"linked": linked, "delete": delete})
        return []

    monkeypatch.setattr(sources, "pdf_page_count", fake_pdf_page_count)
    monkeypatch.setattr(sources, "sha256_file", fake_sha256_file)
    monkeypatch.setattr(sources, "book_map", fake_book_map)
    monkeypatch.setattr(sources, "check_copies", fake_check_copies)

    entries, notices = sources.expand_books(settings, listing)

    assert entries == []
    assert set(notices) == {"ECE 271A/Textbooks/a.pdf", "ECE 271A/Textbooks/b.pdf"}
    assert all(v.startswith("skipped:") for v in notices.values())
    assert check_calls == []


def test_expand_books_copy_check_report_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    course_dir = settings.obsidian_academic_vault_dir / "ECE 271A"
    course_dir.mkdir(parents=True)
    _write(
        course_dir / "Textbooks" / "a.pdf",
        b"%PDF-1.7 a",
    )
    _write(
        course_dir / "Textbooks" / "b.pdf",
        b"%PDF-1.7 b",
    )

    listing = sources.list_sources(settings, "ECE 271A")

    def fake_pdf_page_count(path: Path) -> int:
        return 700

    def fake_sha256_file(path: Path) -> str:
        return "sha"

    mapped = _book("Book", (BookEntry("One", 1, 160, ()),))

    def fake_book_map(settings: Any, path: Path, sha: str) -> BookMap:
        return mapped

    check_calls: list[dict[str, Any]] = []

    def fake_check_copies(settings: Any, books: list[SourceFile], *, linked: bool, delete: bool) -> list[str]:
        check_calls.append({"linked": linked, "delete": delete})
        return []

    monkeypatch.setattr(sources, "pdf_page_count", fake_pdf_page_count)
    monkeypatch.setattr(sources, "sha256_file", fake_sha256_file)
    monkeypatch.setattr(sources, "book_map", fake_book_map)
    monkeypatch.setattr(sources, "check_copies", fake_check_copies)

    entries, notices = sources.expand_books(settings, listing)

    assert len(entries) == 2
    assert notices == {}
    assert len(check_calls) == 1
    assert check_calls[0]["delete"] is False


def test_expand_books_ignores_long_pdf_outside_textbooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    course_dir = settings.obsidian_academic_vault_dir / "ECE 271A"
    course_dir.mkdir(parents=True)
    _write(course_dir / "big.pdf", b"%PDF-1.7 big")
    _write(
        course_dir / "Readings" / "paper.pdf",
        b"%PDF-1.7 paper",
    )

    counted: list[str] = []

    def fake_pdf_page_count(path: Path) -> int:
        counted.append(path.name)
        return 700

    def fake_book_map(settings: Any, path: Path, sha: str) -> BookMap:
        raise AssertionError("must not map")

    def fake_check_copies(
        settings: Any, books: Any, *, linked: bool, delete: bool
    ) -> list[str]:
        return []

    monkeypatch.setattr(sources, "pdf_page_count", fake_pdf_page_count)
    monkeypatch.setattr(sources, "book_map", fake_book_map)
    monkeypatch.setattr(sources, "check_copies", fake_check_copies)
    monkeypatch.setattr(sources, "sha256_file", lambda path: "sha")

    entries, notices = sources.expand_books(
        settings, sources.list_sources(settings, "ECE 271A")
    )

    assert [(e.rel, e.pages) for e in entries] == [
        ("ECE 271A/Readings/paper.pdf", None),
        ("ECE 271A/big.pdf", None),
    ]
    assert notices == {}
    assert counted == []


def test_expand_books_short_textbook_read_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    course_dir = settings.obsidian_academic_vault_dir / "ECE 271A"
    course_dir.mkdir(parents=True)
    _write(
        course_dir / "Textbooks" / "short.pdf",
        b"%PDF-1.7 short",
    )

    def fake_pdf_page_count(path: Path) -> int:
        return 40

    def fake_book_map(settings: Any, path: Path, sha: str) -> BookMap:
        raise AssertionError("must not map")

    monkeypatch.setattr(sources, "pdf_page_count", fake_pdf_page_count)
    monkeypatch.setattr(sources, "book_map", fake_book_map)
    monkeypatch.setattr(sources, "sha256_file", lambda path: "sha")

    entries, notices = sources.expand_books(
        settings, sources.list_sources(settings, "ECE 271A")
    )

    assert [(e.rel, e.pages) for e in entries] == [
        ("ECE 271A/Textbooks/short.pdf", None)
    ]
    assert notices == {}


def test_read_sources_range_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat: list[tuple[str, str]]
) -> None:
    settings = make_settings(tmp_path)
    _write(settings.obsidian_academic_vault_dir / "ECE 271A" / "book.pdf", b"%PDF-1.7 book")

    fake_render, ranges = _range_render([b"png1", b"png2", b"png3"])
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    entry = "ECE 271A/book.pdf#pages=31-33"
    outcome = sources.read_sources(
        settings, "ECE 271A", [entry], deadline=100.0, clock=_FakeClock()
    )

    assert ranges == [(31, 33)]
    assert entry in outcome.readings
    assert outcome.failed == {}
    assert entry in _index(settings)
    assert len(fake_chat) >= 1
    first_reading = outcome.readings[entry]

    fake_chat.clear()
    outcome = sources.read_sources(
        settings, "ECE 271A", [entry], deadline=100.0, clock=_FakeClock()
    )

    assert fake_chat == []
    assert ranges == [(31, 33)]
    assert entry in outcome.readings
    assert outcome.readings[entry] == first_reading


def test_read_sources_range_key_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat: list[tuple[str, str]]
) -> None:
    settings = make_settings(tmp_path)
    _write(settings.obsidian_academic_vault_dir / "ECE 271A" / "book.pdf", b"%PDF-1.7 book")

    fake_render, ranges = _range_render([b"png1", b"png2"])
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    whole = "ECE 271A/book.pdf"
    ranged = "ECE 271A/book.pdf#pages=1-2"

    outcome_whole = sources.read_sources(
        settings, "ECE 271A", [whole], deadline=100.0, clock=_FakeClock()
    )
    outcome_ranged = sources.read_sources(
        settings, "ECE 271A", [ranged], deadline=100.0, clock=_FakeClock()
    )

    assert outcome_whole.readings[whole] != outcome_ranged.readings[ranged]


def test_read_sources_range_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat: list[tuple[str, str]]
) -> None:
    settings = make_settings(tmp_path)
    _write(settings.obsidian_academic_vault_dir / "ECE 271A" / "book.pdf", b"%PDF-1.7 book")
    _write(settings.obsidian_academic_vault_dir / "ECE 271A" / "notes.md", "# n")

    fake_render, ranges = _range_render([b"png1"])
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    outcome = sources.read_sources(
        settings,
        "ECE 271A",
        ["ECE 271A/book.pdf#pages=bad", "ECE 271A/notes.md#pages=1-2"],
        deadline=100.0,
        clock=_FakeClock(),
    )

    assert "ECE 271A/book.pdf#pages=bad" in outcome.failed
    assert outcome.failed["ECE 271A/notes.md#pages=1-2"] == "page range on a non-document"
    assert outcome.readings == {}
    assert ranges == []
    assert fake_chat == []


def test_index_prune_keeps_range_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat: list[tuple[str, str]]
) -> None:
    settings = make_settings(tmp_path)
    book_path = settings.obsidian_academic_vault_dir / "ECE 271A" / "book.pdf"
    _write(book_path, b"%PDF-1.7 book")

    fake_render, ranges = _range_render([b"png1"])
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    entry = "ECE 271A/book.pdf#pages=1-1"
    sources.read_sources(settings, "ECE 271A", [entry], deadline=100.0, clock=_FakeClock())
    assert entry in _index(settings)

    sources.read_sources(settings, "ECE 271A", [], deadline=100.0, clock=_FakeClock())
    assert entry in _index(settings)

    book_path.unlink()
    _write(settings.obsidian_academic_vault_dir / "ECE 271A" / "keep.md", "# keep")

    sources.read_sources(settings, "ECE 271A", [], deadline=100.0, clock=_FakeClock())
    assert entry not in _index(settings)


def test_read_sources_textbook_prompt_for_ranges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    _write(
        settings.obsidian_academic_vault_dir / "ECE 271A" / "book.pdf",
        b"%PDF-1.7 book",
    )
    _write(
        settings.obsidian_academic_vault_dir / "ECE 271A" / "slides.pdf",
        b"%PDF-1.7 slides",
    )

    fake_render, ranges = _range_render([b"png1"])
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    prompts: list[str] = []

    def chat(
        messages: list[dict[str, object]],
        model: str,
        *,
        api_key: str,
        reasoning_effort: str,
        timeout_s: float,
        url: str | None = None,
    ) -> str:
        prompts.append(messages[0]["content"][0]["text"])
        return "### Page 1\nbody"

    monkeypatch.setattr(lecture_docs, "chat", chat)

    outcome = sources.read_sources(
        settings,
        "ECE 271A",
        ["ECE 271A/book.pdf#pages=1-1", "ECE 271A/slides.pdf"],
        deadline=100.0,
        clock=_FakeClock(),
    )

    assert "ECE 271A/book.pdf#pages=1-1" in outcome.readings
    assert "ECE 271A/slides.pdf" in outcome.readings
    assert any("of a textbook used in ECE 271A" in prompt for prompt in prompts)
    assert any("of lecture material for ECE 271A" in prompt for prompt in prompts)
    assert len(prompts) == 2


def test_read_sources_gemini_error_fails_one_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from libra.gemini import GeminiError

    settings = make_settings(tmp_path)
    _write(
        settings.obsidian_academic_vault_dir / "ECE 271A" / "book.pdf",
        b"%PDF-1.7 book",
    )
    _write(
        settings.obsidian_academic_vault_dir / "ECE 271A" / "slides.pdf",
        b"%PDF-1.7 slides",
    )

    fake_render, ranges = _range_render([b"png1"])
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    def chat(
        messages: list[dict[str, object]],
        model: str,
        *,
        api_key: str,
        reasoning_effort: str,
        timeout_s: float,
        url: str | None = None,
    ) -> str:
        if "of a textbook used in" in messages[0]["content"][0]["text"]:
            raise GeminiError(
                "gemini-x: no content (finish_reason content_filter: RECITATION)"
            )
        return "### Page 1\nbody"

    monkeypatch.setattr(lecture_docs, "chat", chat)

    outcome = sources.read_sources(
        settings,
        "ECE 271A",
        ["ECE 271A/book.pdf#pages=1-1", "ECE 271A/slides.pdf"],
        deadline=100.0,
        clock=_FakeClock(),
    )

    assert "ECE 271A/slides.pdf" in outcome.readings
    assert "ECE 271A/book.pdf#pages=1-1" not in outcome.readings
    assert outcome.failed["ECE 271A/book.pdf#pages=1-1"].startswith("GeminiError: ")


def test_read_sources_gemini_cap_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from libra.gemini import GeminiCapError

    settings = make_settings(tmp_path)
    _write(
        settings.obsidian_academic_vault_dir / "ECE 271A" / "book.pdf",
        b"%PDF-1.7 book",
    )

    fake_render, ranges = _range_render([b"png1"])
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    def chat(
        messages: list[dict[str, object]],
        model: str,
        *,
        api_key: str,
        reasoning_effort: str,
        timeout_s: float,
        url: str | None = None,
    ) -> str:
        raise GeminiCapError("gemini-x: HTTP 402")

    monkeypatch.setattr(lecture_docs, "chat", chat)

    with pytest.raises(GeminiCapError):
        sources.read_sources(
            settings,
            "ECE 271A",
            ["ECE 271A/book.pdf"],
            deadline=100.0,
            clock=_FakeClock(),
        )
