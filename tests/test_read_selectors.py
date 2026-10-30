"""Tests for `libra read` chapter and printed-page selectors."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

import libra.read as read_mod
from libra.config import Settings
from libra.lecture_docs import READS_DIR
from libra.sources import SourceFile
from libra.textbooks import BOOKS_DIR, BookEntry, BookMap


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    return Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "LIBRA_VAULT_DIR": str(vault),
            "GEMINI_API_KEY": "k",
        }
    )


def _fixture_entries() -> tuple[BookEntry, ...]:
    return (
        BookEntry("Introduction (part 1/2)", 21, 40, ()),
        BookEntry("Introduction (part 2/2)", 41, 50, ()),
        BookEntry("Linear Models for Regression", 51, 70, ()),
        BookEntry("Linear Models for Classification", 71, 90, ()),
        BookEntry("Appendix A Data Sets", 91, 95, ()),
    )


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> dict[str, Mock]:
    entries = _fixture_entries()
    texts = [f"{i - 20}\nbody words here" if i > 20 else "front matter" for i in range(1, 201)]

    mocks: dict[str, Mock] = {
        "course_dir": Mock(),
        "list_sources": Mock(
            return_value=[SourceFile(rel="ECE 271A/Textbooks/book.pdf", kind="doc", size=100, mtime_ns=1_000_000)]
        ),
        "pdf_page_count": Mock(return_value=200),
        "cached_pages": Mock(return_value={}),
        "reconcile_index": Mock(return_value=False),
        "missing_entries": Mock(return_value=object()),
        "read_sources": Mock(return_value=SimpleNamespace(failed={}, skipped=[])),
        "load_index": Mock(return_value={}),
        "sha256_file": Mock(return_value="abc"),
        "load_cached_map": Mock(
            return_value=BookMap("Test", "", None, None, 200, True, True, entries)
        ),
        "pdf_page_texts": Mock(return_value=texts),
    }
    for name, fake in mocks.items():
        monkeypatch.setattr(read_mod, name, fake)
    return mocks


def test_find_chapter_basic_selectors() -> None:
    entries = _fixture_entries()
    assert read_mod.find_chapter(entries, "1") == ("Introduction", 21, 50)
    assert read_mod.find_chapter(entries, " 2 ") == ("Linear Models for Regression", 51, 70)
    assert read_mod.find_chapter(entries, "regression") == ("Linear Models for Regression", 51, 70)

    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.find_chapter(entries, "4")
    assert exc.value.code == "unknown_chapter"
    assert exc.value.chapters == (
        "Introduction",
        "Linear Models for Regression",
        "Linear Models for Classification",
        "Appendix A Data Sets",
    )

    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.find_chapter(entries, "linear models")
    assert exc.value.code == "ambiguous_chapter"
    assert exc.value.chapters == (
        "Linear Models for Regression",
        "Linear Models for Classification",
    )

    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.find_chapter(entries, "zzz")
    assert exc.value.code == "unknown_chapter"


def test_find_chapter_exact_tiebreak() -> None:
    entries = (
        BookEntry("Sampling", 1, 10, ()),
        BookEntry("Sampling Methods", 11, 20, ()),
    )
    assert read_mod.find_chapter(entries, "SAMPLING") == ("Sampling", 1, 10)


def test_chapter_read(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["cached_pages"].return_value = {21: "x"}
    result: dict[str, Any] = read_mod.read_pages(
        settings,
        "ece 271a",
        "ECE 271A/Textbooks/book.pdf",
        chapter="1",
    )
    assert result["chapter"] == {"title": "Introduction", "first": 21, "last": 50}
    assert result["pages"] == [{"page": 21, "text": "x"}]
    assert result["missing"] == list(range(22, 51))
    assert "printed" not in result
    fakes["load_cached_map"].assert_called_once_with(
        settings.state_dir / READS_DIR / BOOKS_DIR / "abc.json",
        settings.obsidian_academic_vault_dir / "ECE 271A/Textbooks/book.pdf",
    )
    fakes["sha256_file"].assert_called_once()


def test_chapter_sha_from_index(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["load_index"].return_value = {
        "ECE 271A/Textbooks/book.pdf": [100, 1_000_000, "fromindex", ""]
    }
    read_mod.read_pages(
        settings,
        "ece 271a",
        "ECE 271A/Textbooks/book.pdf",
        chapter="1",
    )
    fakes["sha256_file"].assert_not_called()
    fakes["load_cached_map"].assert_called_once()
    assert fakes["load_cached_map"].call_args.args[0].name == "fromindex.json"


def test_chapter_sha_stale_index(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["load_index"].return_value = {
        "ECE 271A/Textbooks/book.pdf": [99, 1_000_000, "stale", ""]
    }
    read_mod.read_pages(
        settings,
        "ece 271a",
        "ECE 271A/Textbooks/book.pdf",
        chapter="1",
    )
    fakes["sha256_file"].assert_called_once()
    fakes["load_cached_map"].assert_called_once()
    assert fakes["load_cached_map"].call_args.args[0].name == "abc.json"


def test_no_chapter_map(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["load_cached_map"].return_value = None
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings,
            "ece 271a",
            "ECE 271A/Textbooks/book.pdf",
            chapter="1",
        )
    assert exc.value.code == "no_chapter_map"

    fakes["load_cached_map"].return_value = BookMap("Test", "", None, None, 200, True, True, ())
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings,
            "ece 271a",
            "ECE 271A/Textbooks/book.pdf",
            chapter="1",
        )
    assert exc.value.code == "no_chapter_map"
    fakes["read_sources"].assert_not_called()


def test_unknown_chapter_through_read_pages(settings: Settings, fakes: dict[str, Mock]) -> None:
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings,
            "ece 271a",
            "ECE 271A/Textbooks/book.pdf",
            chapter="nothing",
        )
    assert exc.value.code == "unknown_chapter"
    assert len(exc.value.chapters) == 4


def test_chapter_survives_reconcile_rebuild(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["cached_pages"].side_effect = [{}, {21: "y"}]
    fakes["reconcile_index"].return_value = True
    result = read_mod.read_pages(
        settings,
        "ece 271a",
        "ECE 271A/Textbooks/book.pdf",
        chapter="1",
    )
    assert result["chapter"] == {"title": "Introduction", "first": 21, "last": 50}
    assert result["pages"] == [{"page": 21, "text": "y"}]


def test_chapter_fetch_keeps_key(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["cached_pages"].side_effect = [{}, {}, {n: "t" for n in range(51, 71)}]
    fakes["read_sources"].return_value = SimpleNamespace(failed={}, skipped=[])
    result = read_mod.read_pages(
        settings,
        "ece 271a",
        "ECE 271A/Textbooks/book.pdf",
        chapter="regression",
        fetch=True,
    )
    fakes["read_sources"].assert_called_once()
    fakes["missing_entries"].assert_called_once_with(
        "ECE 271A/Textbooks/book.pdf",
        list(range(51, 71)),
        200,
    )
    assert result["missing"] == []
    assert result["chapter"] == {
        "title": "Linear Models for Regression",
        "first": 51,
        "last": 70,
    }
    assert result["failed"] == {}


def test_long_chapter_fetch_refused(
    settings: Settings,
    fakes: dict[str, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(read_mod, "MAX_FETCH_PAGES", 10)
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings,
            "ece 271a",
            "ECE 271A/Textbooks/book.pdf",
            chapter="1",
            fetch=True,
        )
    assert exc.value.code == "too_many_pages"
    fakes["read_sources"].assert_not_called()


def test_printed_read(settings: Settings, fakes: dict[str, Mock]) -> None:
    result = read_mod.read_pages(
        settings,
        "ece 271a",
        "ECE 271A/Textbooks/book.pdf",
        printed=(5, 7),
    )
    assert result["printed"] == {"first": 5, "last": 7}
    assert result["missing"] == [25, 26, 27]
    assert "chapter" not in result
    fakes["load_cached_map"].assert_not_called()


def test_printed_page_unknown(settings: Settings, fakes: dict[str, Mock]) -> None:
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings,
            "ece 271a",
            "ECE 271A/Textbooks/book.pdf",
            printed=(190, 195),
        )
    assert exc.value.code == "printed_page_unknown"


def test_printed_unreadable_source(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["pdf_page_texts"].side_effect = OSError()
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings,
            "ece 271a",
            "ECE 271A/Textbooks/book.pdf",
            printed=(5, 7),
        )
    assert exc.value.code == "unreadable_source"


@pytest.mark.parametrize(
    ("kwargs",),
    [
        ({"first": 1, "last": 2, "chapter": "1"},),
        ({"chapter": "1", "printed": (1, 2)},),
        ({"first": 1, "last": 1, "printed": (1, 1)},),
        ({"chapter": "   "},),
        ({"printed": (0, 3)},),
        ({"printed": (5, 3)},),
    ],
)
def test_selector_validation(
    settings: Settings,
    fakes: dict[str, Mock],
    kwargs: dict[str, Any],
) -> None:
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings,
            "ece 271a",
            "ECE 271A/Textbooks/book.pdf",
            **kwargs,
        )
    assert exc.value.code == "invalid_pages"


def test_chapter_beyond_pdf(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["pdf_page_count"].return_value = 60
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings,
            "ece 271a",
            "ECE 271A/Textbooks/book.pdf",
            chapter="3",
        )
    assert exc.value.code == "invalid_pages"
