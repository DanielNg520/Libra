"""Tests for libra.read."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from libra.config import Settings
from libra.gemini import GeminiCapError
from libra.sources import SourceFile
import libra.read as read_mod


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


@pytest.fixture
def no_key_settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    return Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "LIBRA_VAULT_DIR": str(vault),
        }
    )


def _source(rel: str = "notes/lec1.pdf", kind: str = "doc") -> SourceFile:
    return SourceFile(rel=rel, kind=kind, size=100, mtime_ns=1_000_000)


@pytest.fixture
def fakes(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> dict[str, Mock]:
    course_dir = Mock()
    list_sources = Mock(return_value=[_source()])
    pdf_page_count = Mock(return_value=5)
    cached_pages = Mock(return_value={})
    missing_entries = Mock(return_value=object())
    read_sources = Mock(
        return_value=SimpleNamespace(failed={}, skipped=[])
    )
    monkeypatch.setattr(read_mod, "course_dir", course_dir)
    monkeypatch.setattr(read_mod, "list_sources", list_sources)
    monkeypatch.setattr(read_mod, "pdf_page_count", pdf_page_count)
    monkeypatch.setattr(read_mod, "cached_pages", cached_pages)
    monkeypatch.setattr(read_mod, "missing_entries", missing_entries)
    monkeypatch.setattr(read_mod, "read_sources", read_sources)
    return {
        "course_dir": course_dir,
        "list_sources": list_sources,
        "pdf_page_count": pdf_page_count,
        "cached_pages": cached_pages,
        "missing_entries": missing_entries,
        "read_sources": read_sources,
    }


def test_invalid_path_and_pages(settings: Settings, fakes: dict[str, Mock]) -> None:
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(settings, "ece 108", "")
    assert exc.value.code == "invalid_path"

    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(settings, "ece 108", "a#b")
    assert exc.value.code == "invalid_path"

    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(settings, "ece 108", "notes/lec1.pdf", first=2)
    assert exc.value.code == "invalid_pages"

    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(settings, "ece 108", "notes/lec1.pdf", first=0, last=1)
    assert exc.value.code == "invalid_pages"

    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(settings, "ece 108", "notes/lec1.pdf", first=3, last=2)
    assert exc.value.code == "invalid_pages"


def test_course_folder_missing(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["course_dir"].side_effect = ValueError("no folder")
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(settings, "ece 108", "notes/lec1.pdf")
    assert exc.value.code == "course_folder_missing"


def test_unknown_and_unsupported(settings: Settings, fakes: dict[str, Mock]) -> None:
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(settings, "ece 108", "other.pdf")
    assert exc.value.code == "unknown_source"

    fakes["list_sources"].return_value = [
        SourceFile(rel="photo.jpg", kind="photo", size=1, mtime_ns=1)
    ]
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(settings, "ece 108", "photo.jpg")
    assert exc.value.code == "unsupported_source"

    fakes["list_sources"].return_value = [
        SourceFile(rel="deck.PPTX", kind="doc", size=1, mtime_ns=1)
    ]
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(settings, "ece 108", "deck.PPTX")
    assert exc.value.code == "unsupported_source"


def test_unreadable_and_range(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["pdf_page_count"].side_effect = OSError("boom")
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(settings, "ece 108", "notes/lec1.pdf")
    assert exc.value.code == "unreadable_source"

    fakes["pdf_page_count"].side_effect = None
    fakes["pdf_page_count"].return_value = 5
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings, "ece 108", "notes/lec1.pdf", first=1, last=9
        )
    assert exc.value.code == "invalid_pages"


def test_cached_only(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["cached_pages"].return_value = {1: "a", 3: "c"}
    result = read_mod.read_pages(settings, "ece 108", "notes/lec1.pdf")
    assert result == {
        "ok": True,
        "path": "notes/lec1.pdf",
        "pages": [
            {"page": 1, "text": "a"},
            {"page": 3, "text": "c"},
        ],
        "missing": [2, 4, 5],
    }
    fakes["read_sources"].assert_not_called()


def test_missing_reconcile_true(
    settings: Settings, fakes: dict[str, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes["cached_pages"].side_effect = [
        {1: "a", 3: "c"},
        {1: "a", 2: "b", 3: "c", 4: "d", 5: "e"},
    ]
    reconcile = Mock(return_value=True)
    monkeypatch.setattr(read_mod, "reconcile_index", reconcile)
    result = read_mod.read_pages(settings, "ece 108", "notes/lec1.pdf")
    assert result == {
        "ok": True,
        "path": "notes/lec1.pdf",
        "pages": [
            {"page": 1, "text": "a"},
            {"page": 2, "text": "b"},
            {"page": 3, "text": "c"},
            {"page": 4, "text": "d"},
            {"page": 5, "text": "e"},
        ],
        "missing": [],
    }
    reconcile.assert_called_once_with(
        settings, "ECE 108", fakes["list_sources"].return_value
    )
    fakes["read_sources"].assert_not_called()


def test_nothing_missing_no_reconcile(
    settings: Settings, fakes: dict[str, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes["cached_pages"].return_value = {
        1: "a",
        2: "b",
        3: "c",
        4: "d",
        5: "e",
    }
    reconcile = Mock(return_value=True)
    monkeypatch.setattr(read_mod, "reconcile_index", reconcile)
    result = read_mod.read_pages(settings, "ece 108", "notes/lec1.pdf")
    assert result == {
        "ok": True,
        "path": "notes/lec1.pdf",
        "pages": [
            {"page": 1, "text": "a"},
            {"page": 2, "text": "b"},
            {"page": 3, "text": "c"},
            {"page": 4, "text": "d"},
            {"page": 5, "text": "e"},
        ],
        "missing": [],
    }
    reconcile.assert_not_called()
    fakes["read_sources"].assert_not_called()


def test_missing_reconcile_false(
    settings: Settings, fakes: dict[str, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes["cached_pages"].return_value = {1: "a", 3: "c"}
    reconcile = Mock(return_value=False)
    monkeypatch.setattr(read_mod, "reconcile_index", reconcile)
    result = read_mod.read_pages(settings, "ece 108", "notes/lec1.pdf")
    assert result == {
        "ok": True,
        "path": "notes/lec1.pdf",
        "pages": [
            {"page": 1, "text": "a"},
            {"page": 3, "text": "c"},
        ],
        "missing": [2, 4, 5],
    }
    fakes["cached_pages"].assert_called_once()
    fakes["read_sources"].assert_not_called()


def test_fetch_guards(
    settings: Settings,
    no_key_settings: Settings,
    fakes: dict[str, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(read_mod, "MAX_FETCH_PAGES", 2)
    fakes["cached_pages"].return_value = {1: "a"}

    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings, "ece 108", "notes/lec1.pdf", fetch=True
        )
    assert exc.value.code == "too_many_pages"

    monkeypatch.setattr(read_mod, "MAX_FETCH_PAGES", 10)
    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            no_key_settings, "ece 108", "notes/lec1.pdf", fetch=True
        )
    assert exc.value.code == "read_unavailable"


def test_fetch_reads_missing_under_lock(
    settings: Settings,
    tmp_path: Path,
    fakes: dict[str, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(read_mod, "MAX_FETCH_PAGES", 10)
    entries_obj = object()
    fakes["cached_pages"].side_effect = [
        {1: "a"},
        {1: "a"},
        {1: "a", 2: "b", 3: "c", 4: "d", 5: "e"},
    ]
    fakes["missing_entries"].return_value = entries_obj

    result = read_mod.read_pages(
        settings, "ece 108", "notes/lec1.pdf", fetch=True
    )

    assert result["pages"] == [
        {"page": n, "text": t}
        for n, t in [(1, "a"), (2, "b"), (3, "c"), (4, "d"), (5, "e")]
    ]
    assert result["missing"] == []
    assert result["failed"] == {}
    assert result["skipped"] == []

    call = fakes["read_sources"].call_args
    assert call.args[0] is settings
    assert call.args[1] == "ECE 108"
    assert call.args[2] is entries_obj
    assert "deadline" in call.kwargs

    fakes["missing_entries"].assert_called_once_with(
        "notes/lec1.pdf", [2, 3, 4, 5], 5
    )

    assert (tmp_path / "state" / "read.lock").exists()


def test_gemini_cap(settings: Settings, fakes: dict[str, Mock]) -> None:
    fakes["cached_pages"].return_value = {1: "a"}
    fakes["read_sources"].side_effect = GeminiCapError("cap")

    with pytest.raises(read_mod.ReadError) as exc:
        read_mod.read_pages(
            settings, "ece 108", "notes/lec1.pdf", fetch=True
        )
    assert exc.value.code == "gemini_cap"


def test_reconcile_never_runs_under_index_lock(
    settings: Settings, fakes: dict[str, Mock], monkeypatch: pytest.MonkeyPatch
) -> None:
    held = False
    entries = 0
    reconcile_calls = 0

    @contextlib.contextmanager
    def fake_index_lock(_settings: Settings) -> Iterator[None]:
        nonlocal held, entries
        held = True
        entries += 1
        try:
            yield
        finally:
            held = False

    def fake_reconcile(
        _settings: Settings, _code: str, sources: object
    ) -> bool:
        nonlocal reconcile_calls
        reconcile_calls += 1
        assert not held
        return False

    monkeypatch.setattr(read_mod, "MAX_FETCH_PAGES", 10)
    monkeypatch.setattr(read_mod, "index_lock", fake_index_lock)
    monkeypatch.setattr(read_mod, "reconcile_index", fake_reconcile)
    fakes["cached_pages"].side_effect = [
        {1: "a"},
        {1: "a"},
        {1: "a", 2: "b", 3: "c", 4: "d", 5: "e"},
    ]

    result = read_mod.read_pages(settings, "ece 108", "notes/lec1.pdf", fetch=True)

    assert entries == 1
    assert reconcile_calls == 1
    assert fakes["read_sources"].call_count == 1
    assert result["missing"] == []
