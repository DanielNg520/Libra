from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from libra import reading_export, sources
from libra.config import Settings
from libra.lecture_docs import READ_PROMPT, READS_DIR, reading_key
from libra.source_pages import cached_pages
from test_sources import make_settings


def _deck(settings: Settings, course: str, name: str, data: bytes) -> Path:
    path = Path(settings.obsidian_academic_vault_dir) / course / "Slides" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _write_index(settings: Settings, files: dict) -> None:
    path = settings.state_dir / READS_DIR / sources.INDEX_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "files": files}))


def _read_index(settings: Settings) -> dict:
    path = settings.state_dir / READS_DIR / sources.INDEX_NAME
    return json.loads(path.read_text())["files"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source(settings: Settings, course: str, rel: str) -> sources.SourceFile:
    return next(s for s in sources.list_sources(settings, course) if s.rel == rel)


def _cache_reading(settings: Settings, render_key: str, text: str) -> None:
    key = reading_key(
        render_key,
        model=settings.ocr_model,
        effort=sources.DOC_EFFORT,
        prompt_template=READ_PROMPT,
    )
    path = settings.state_dir / READS_DIR / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_rename_adopts_orphan_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    data = b"%PDF-1.7 deck one"
    path = _deck(settings, "ECE 253", "New.pdf", data)
    size = path.stat().st_size
    mtime = path.stat().st_mtime_ns
    sha = _sha(data)
    _write_index(
        settings,
        {
            "ECE 253/Slides/Old.pdf": [size, 1, sha, "rk"],
            "ECE 253/Slides/Old.pdf#pages=1-3": [size, 1, "rsha", "rrk"],
        },
    )

    result = sources.reconcile_index(settings, "ECE 253", sources.list_sources(settings, "ECE 253"))

    assert result is True
    index = _read_index(settings)
    assert index["ECE 253/Slides/New.pdf"] == [size, mtime, sha, "rk"]
    assert index["ECE 253/Slides/New.pdf#pages=1-3"] == [size, mtime, "rsha", "rrk"]
    assert "ECE 253/Slides/Old.pdf" not in index
    assert "ECE 253/Slides/Old.pdf#pages=1-3" not in index


def test_touched_mtime_refreshes_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    data = b"%PDF-1.7 deck one"
    path = _deck(settings, "ECE 253", "A.pdf", data)
    size = path.stat().st_size
    mtime = path.stat().st_mtime_ns
    sha = _sha(data)
    _write_index(
        settings,
        {
            "ECE 253/Slides/A.pdf": [size, 1, sha, "rk"],
            "ECE 253/Slides/A.pdf#pages=2-4": [size, 1, "rsha", "rrk"],
        },
    )

    result = sources.reconcile_index(settings, "ECE 253", sources.list_sources(settings, "ECE 253"))

    assert result is True
    index = _read_index(settings)
    assert index["ECE 253/Slides/A.pdf"] == [size, mtime, sha, "rk"]
    assert index["ECE 253/Slides/A.pdf#pages=2-4"] == [size, mtime, "rsha", "rrk"]


def test_same_size_different_bytes_not_adopted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    data = b"%PDF-1.7 deck one"
    path = _deck(settings, "ECE 253", "New.pdf", data)
    size = path.stat().st_size
    _write_index(
        settings,
        {"ECE 253/Slides/Old.pdf": [size, 1, "other", "rk"]},
    )

    result = sources.reconcile_index(settings, "ECE 253", sources.list_sources(settings, "ECE 253"))

    assert result is False
    index = _read_index(settings)
    assert index == {"ECE 253/Slides/Old.pdf": [size, 1, "other", "rk"]}
    assert "ECE 253/Slides/New.pdf" not in index


def test_listed_entry_never_taken(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    data = b"%PDF-1.7 deck one"
    path_a = _deck(settings, "ECE 253", "A.pdf", data)
    _deck(settings, "ECE 253", "B.pdf", data)
    size = path_a.stat().st_size
    mtime = path_a.stat().st_mtime_ns
    sha = _sha(data)
    _write_index(
        settings,
        {"ECE 253/Slides/A.pdf": [size, mtime, sha, "rk"]},
    )

    result = sources.reconcile_index(settings, "ECE 253", sources.list_sources(settings, "ECE 253"))

    assert result is False
    index = _read_index(settings)
    assert "ECE 253/Slides/B.pdf" not in index
    assert index["ECE 253/Slides/A.pdf"] == [size, mtime, sha, "rk"]


def test_other_course_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    data = b"%PDF-1.7 deck one"
    path = _deck(settings, "ECE 253", "New.pdf", data)
    size = path.stat().st_size
    sha = _sha(data)
    _write_index(
        settings,
        {"ECE 108/Slides/Old.pdf": [size, 1, sha, "rk"]},
    )

    result = sources.reconcile_index(settings, "ECE 253", sources.list_sources(settings, "ECE 253"))

    assert result is False
    index = _read_index(settings)
    assert index["ECE 108/Slides/Old.pdf"] == [size, 1, sha, "rk"]


def test_no_hash_without_same_size_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    data = b"%PDF-1.7 deck one"
    path = _deck(settings, "ECE 253", "New.pdf", data)
    size = path.stat().st_size
    _write_index(
        settings,
        {"ECE 253/Slides/Old.pdf": [size + 1, 1, "whatever", "rk"]},
    )
    hashed: list[bytes] = []

    def fake_sha256_file(path: Path) -> str:
        hashed.append(path.read_bytes())
        raise AssertionError("should not hash")

    monkeypatch.setattr(sources, "sha256_file", fake_sha256_file)

    result = sources.reconcile_index(settings, "ECE 253", sources.list_sources(settings, "ECE 253"))

    assert result is False
    assert hashed == []


def test_vault_none_returns_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings.load({"LIBRA_STATE_DIR": str(tmp_path / "state")})
    assert sources.reconcile_index(settings, "ECE 253", []) is False


def test_cached_pages_after_adoption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    data = b"%PDF-1.7 deck one"
    path = _deck(settings, "ECE 253", "New.pdf", data)
    size = path.stat().st_size
    sha = _sha(data)
    _write_index(
        settings,
        {
            "ECE 253/Slides/Old.pdf": [size, 1, sha, "rk"],
            "ECE 253/Slides/Old.pdf#pages=1-3": [size, 1, "rsha", "rrk"],
        },
    )
    _cache_reading(settings, "rk", "### Page 1\nhello")
    new_source = _source(settings, "ECE 253", "ECE 253/Slides/New.pdf")

    assert cached_pages(settings, new_source) == {}

    sources.reconcile_index(settings, "ECE 253", sources.list_sources(settings, "ECE 253"))

    assert cached_pages(settings, new_source) == {1: "hello"}


def test_read_sources_adopts_without_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    data = b"%PDF-1.7 deck one"
    path = _deck(settings, "ECE 253", "New.pdf", data)
    size = path.stat().st_size
    sha = _sha(data)
    _write_index(
        settings,
        {
            "ECE 253/Slides/Old.pdf": [size, 1, sha, "rk"],
            "ECE 253/Slides/Old.pdf#pages=1-3": [size, 1, "rsha", "rrk"],
        },
    )
    _cache_reading(settings, "rk", "### Page 1\nhello")

    def fail_render(*args, **kwargs):
        raise AssertionError("should not render")

    monkeypatch.setattr(sources, "render_pages", fail_render)

    outcome = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/Slides/New.pdf"],
        deadline=100.0,
        clock=lambda: 0.0,
    )

    assert outcome.failed == {}
    assert "ECE 253/Slides/New.pdf" in outcome.readings
    index = _read_index(settings)
    assert "ECE 253/Slides/New.pdf" in index
    assert "ECE 253/Slides/Old.pdf" not in index


def test_export_writes_renamed_deck(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    data = b"%PDF-1.7 deck one"
    path = _deck(settings, "ECE 1", "New.pdf", data)
    (Path(settings.obsidian_academic_vault_dir) / "ECE 1" / "Transcripts").mkdir()
    size = path.stat().st_size
    sha = _sha(data)
    _write_index(
        settings,
        {
            "ECE 1/Slides/Old.pdf": [size, 1, sha, "rk"],
            "ECE 1/Slides/Old.pdf#pages=1-3": [size, 1, "rsha", "rrk"],
        },
    )
    _cache_reading(settings, "rk", "### Page 1\nhello")

    def fail_pdf_texts(*args, **kwargs):
        raise AssertionError("should not use pdf_page_texts")

    monkeypatch.setattr(reading_export, "pdf_page_texts", fail_pdf_texts)

    written = reading_export.write_readings(settings)

    target = Path(settings.obsidian_academic_vault_dir) / "Tools" / "readings" / "ECE 1" / "Slides" / "New.pdf.md"
    assert target in written
    assert "hello" in target.read_text()
    index = _read_index(settings)
    assert "ECE 1/Slides/New.pdf" in index
