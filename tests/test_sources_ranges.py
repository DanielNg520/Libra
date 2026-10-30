from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from libra import sources
from libra.sources import SourceFile, split_entry
from libra import lecture_docs
from test_sources import _FakeClock, _index, _write, fake_chat, make_settings  # noqa: F401


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
