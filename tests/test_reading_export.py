from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest

from libra.config import Settings
from libra import reading_export
from test_sources import make_settings


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, Path]:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    assert vault is not None
    course = vault / "ECE 1"
    (course / "Transcripts").mkdir(parents=True)
    (course / "Slides").mkdir()
    (course / "Textbooks").mkdir()
    (course / "Slides" / "lec1.pdf").write_bytes(b"%PDF-1.4\nlec1")
    (course / "Slides" / "notes.md").write_text("# notes")
    (course / "Slides" / "fig.png").write_bytes(b"\x89PNG")
    (course / "Textbooks" / "book.pdf").write_bytes(b"%PDF-1.4\nbook")

    cached = {
        "ECE 1/Slides/lec1.pdf": {2: "Second page", 1: "First page", 3: "   "},
        "ECE 1/Slides/fig.png": {},
    }
    monkeypatch.setattr(
        reading_export,
        "cached_pages",
        lambda settings, source: cached.get(source.rel, {}),
    )
    monkeypatch.setattr(
        reading_export,
        "pdf_page_texts",
        lambda path: ["Chapter one", "", "Chapter two"],
    )
    return settings, vault


def test_exports_readings_and_textbooks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, vault = _setup(tmp_path, monkeypatch)
    readings = vault / "Tools" / "readings"
    written = reading_export.write_readings(settings)
    assert len(written) == 2
    assert set(written) == {
        readings / "ECE 1" / "Slides" / "lec1.pdf.md",
        readings / "ECE 1" / "Textbooks" / "book.pdf.md",
    }
    lec1_body = (readings / "ECE 1" / "Slides" / "lec1.pdf.md").read_text()
    assert lec1_body == (
        "# ECE 1/Slides/lec1.pdf\n"
        "Kind: reading\n\n"
        "### Page 1\n\n"
        "First page\n\n"
        "### Page 2\n\n"
        "Second page\n"
    )
    book_body = (readings / "ECE 1" / "Textbooks" / "book.pdf.md").read_text()
    assert book_body == (
        "# ECE 1/Textbooks/book.pdf\n"
        "Kind: textbook\n\n"
        "### Page 1\n\n"
        "Chapter one\n\n"
        "### Page 3\n\n"
        "Chapter two\n"
    )
    assert not (readings / "ECE 1" / "Slides" / "fig.png.md").exists()
    assert not (readings / "ECE 1" / "Slides" / "notes.md.md").exists()
    manifest = json.loads((readings / "manifest.json").read_text())
    assert manifest["version"] == 1
    assert set(manifest["files"]) == {
        "ECE 1/Slides/lec1.pdf",
        "ECE 1/Textbooks/book.pdf",
    }


def test_unchanged_rerun_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, vault = _setup(tmp_path, monkeypatch)
    calls: list[str] = []

    def fake_pdf(path: Path) -> list[str]:
        calls.append(path.name)
        return ["Chapter one", "", "Chapter two"]

    monkeypatch.setattr(reading_export, "pdf_page_texts", fake_pdf)
    first = reading_export.write_readings(settings)
    assert len(first) == 2
    readings = vault / "Tools" / "readings"
    mtimes = {
        p: p.stat().st_mtime_ns for p in [*first, readings / "manifest.json"]
    }
    second = reading_export.write_readings(settings)
    assert second == []
    assert len(calls) == 1
    for p, mt in mtimes.items():
        assert p.stat().st_mtime_ns == mt


def test_changed_textbook_reextracts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, vault = _setup(tmp_path, monkeypatch)
    reading_export.write_readings(settings)
    (vault / "ECE 1" / "Textbooks" / "book.pdf").write_bytes(b"%PDF-1.4\nbook v2")
    monkeypatch.setattr(reading_export, "pdf_page_texts", lambda path: ["New text"])
    written = reading_export.write_readings(settings)
    assert written == [vault / "Tools" / "readings" / "ECE 1" / "Textbooks" / "book.pdf.md"]
    body = written[0].read_text()
    assert "New text" in body


def test_orphan_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, vault = _setup(tmp_path, monkeypatch)
    reading_export.write_readings(settings)
    (vault / "ECE 1" / "Slides" / "lec1.pdf").unlink()
    written = reading_export.write_readings(settings)
    readings = vault / "Tools" / "readings"
    assert written == []
    assert not (readings / "ECE 1" / "Slides" / "lec1.pdf.md").exists()
    assert not (readings / "ECE 1" / "Slides").exists()
    assert (readings / "ECE 1" / "Textbooks" / "book.pdf.md").exists()
    manifest = json.loads((readings / "manifest.json").read_text())
    assert "ECE 1/Slides/lec1.pdf" not in manifest["files"]
    assert "ECE 1/Textbooks/book.pdf" in manifest["files"]


def test_extraction_failure_logs_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings, vault = _setup(tmp_path, monkeypatch)

    def fake_pdf(path: Path) -> list[str]:
        raise subprocess.CalledProcessError(1, ["pdftotext"])

    monkeypatch.setattr(reading_export, "pdf_page_texts", fake_pdf)
    with caplog.at_level(logging.WARNING):
        written = reading_export.write_readings(settings)
    assert written == [vault / "Tools" / "readings" / "ECE 1" / "Slides" / "lec1.pdf.md"]
    assert any(
        "readings export: text extraction failed for ECE 1/Textbooks/book.pdf: CalledProcessError"
        in rec.message
        for rec in caplog.records
        if rec.levelno == logging.WARNING
    )


def test_course_failure_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    settings, vault = _setup(tmp_path, monkeypatch)
    ece2 = vault / "ECE 2"
    (ece2 / "Transcripts").mkdir(parents=True)
    (ece2 / "Slides").mkdir()
    (ece2 / "Slides" / "a.pdf").write_bytes(b"%PDF-1.4\na")
    cached = {
        "ECE 1/Slides/lec1.pdf": {1: "First page"},
        "ECE 1/Slides/fig.png": {},
        "ECE 2/Slides/a.pdf": {1: "A"},
    }
    monkeypatch.setattr(
        reading_export, "cached_pages", lambda settings, source: cached.get(source.rel, {})
    )
    monkeypatch.setattr(reading_export, "pdf_page_texts", lambda path: ["Chapter one", "", "Chapter two"])
    reading_export.write_readings(settings)
    ece1_export = vault / "Tools" / "readings" / "ECE 1" / "Slides" / "lec1.pdf.md"
    assert ece1_export.exists()

    real_list_sources = reading_export.list_sources

    def failing_list(settings: Settings, course: str) -> list[Any]:
        if course == "ECE 1":
            raise RuntimeError("boom")
        return real_list_sources(settings, course)

    monkeypatch.setattr(reading_export, "list_sources", failing_list)
    with caplog.at_level(logging.WARNING):
        written = reading_export.write_readings(settings)
    assert ece1_export.exists()
    assert any(
        "readings export ECE 1 failed: RuntimeError" in rec.message
        for rec in caplog.records
        if rec.levelno == logging.WARNING
    )
    assert all(p.name != "lec1.pdf.md" for p in written)


def test_vault_none_returns_empty(tmp_path: Path) -> None:
    settings = Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "GEMINI_API_KEY": "gem",
            "OPENROUTER_API_KEY": "or",
        }
    )
    assert settings.obsidian_academic_vault_dir is None
    assert reading_export.write_readings(settings) == []


def test_uncached_pdf_falls_back_to_pdftotext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, vault = _setup(tmp_path, monkeypatch)
    (vault / "ECE 1" / "Homework").mkdir(parents=True)
    (vault / "ECE 1" / "Homework" / "hw1.pdf").write_bytes(b"%PDF-1.4\nhw1")
    (vault / "ECE 1" / "Slides" / "scan.pdf").write_bytes(b"%PDF-1.4\nscan")
    extracted: list[str] = []

    def fake_pdf_page_texts(pdf_path: Path) -> list[str]:
        extracted.append(pdf_path.name)
        if pdf_path.name == "hw1.pdf":
            return ["Problem one text"]
        if pdf_path.name == "scan.pdf":
            return [""]
        return ["Chapter one", "", "Chapter two"]

    monkeypatch.setattr(reading_export, "pdf_page_texts", fake_pdf_page_texts)
    monkeypatch.setattr(
        reading_export,
        "is_searchable",
        lambda texts: any(t.strip() for t in texts),
    )

    result = reading_export.write_readings(settings)

    hw1_md = vault / "Tools" / "readings" / "ECE 1" / "Homework" / "hw1.pdf.md"
    scan_md = vault / "Tools" / "readings" / "ECE 1" / "Slides" / "scan.pdf.md"
    assert result
    assert hw1_md.read_text() == (
        "# ECE 1/Homework/hw1.pdf\nKind: reading\n\n### Page 1\n\n"
        "Problem one text\n"
    )
    assert not scan_md.exists()
    assert "lec1.pdf" not in extracted
    assert extracted.count("hw1.pdf") == 1

    assert reading_export.write_readings(settings) == []
    assert extracted.count("hw1.pdf") == 1
