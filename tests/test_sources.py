"""Tests for libra.sources."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from libra.config import Settings
from libra import sources
from libra.gemini import GeminiError
from libra import lecture_docs
from libra.lecture_docs import READS_DIR, TooManyPages


def make_settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir()
    return Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "LIBRA_VAULT_DIR": str(vault),
            "GEMINI_API_KEY": "gem",
            "OPENROUTER_API_KEY": "or",
        }
    )


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data)
    else:
        path.write_bytes(data)


def _index(settings: Settings) -> dict:
    raw = json.loads((settings.state_dir / READS_DIR / sources.INDEX_NAME).read_text())
    return raw["files"]


class _FakeClock:
    def __init__(self, values: list[float] | None = None, default: float = 0.0) -> None:
        self.values = list(values) if values else []
        self.default = default
        self.calls = 0
        self.now = default

    def __call__(self) -> float:
        self.calls += 1
        if self.values:
            self.now = self.values.pop(0)
        return self.now


def _make_fake_render(pages_by_file: dict[str, list[bytes]]):
    calls: list[tuple[str, list[Path], Path]] = []

    def fake_render(kind: str, srcs, workdir, page_range=None) -> list[tuple[str, bytes]]:
        calls.append((kind, list(srcs), Path(workdir)))
        if kind == "photos":
            return [("image/jpeg", b"jpg")]
        results: list[tuple[str, bytes]] = []
        for src in srcs:
            name = Path(src).name
            for png in pages_by_file.get(name, []):
                results.append(("image/png", png))
        return results

    return fake_render, calls


@pytest.fixture
def fake_chat(monkeypatch):
    calls: list[tuple[str, str]] = []

    def chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None) -> str:
        calls.append((model, reasoning_effort))
        page_count = len(messages[0]["content"]) - 1
        return "\n\n".join(f"### Page {i}\nbody" for i in range(1, page_count + 1))

    monkeypatch.setattr(lecture_docs, "chat", chat)
    return calls


def test_list_sources_kinds_and_order(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    course = "ECE 253"

    _write(vault / course / "SlideDeck 1.pdf", b"%PDF-1.7 fake pdf")
    _write(vault / course / "Ask uploads" / "Lecture board " / "IMG_1.JPG", b"\xff\xd8\xff")
    _write(vault / course / "Ask uploads" / "Lecture board " / "IMG_2.webp", b"RIFF\x00\x00\x00\x00WEBP")
    _write(vault / course / "Homework" / "Quiz 1" / "Quiz_Tips.md", "# Tips\n")
    _write(vault / course / "canvasdl", b"%PDF-1.7 x")
    _write(vault / course / "notes.docx", b"PK\x03\x04")
    _write(vault / course / ".hidden" / "a.pdf", b"%PDF-1.7")
    _write(vault / course / "~$tmp.pptx", b"ignored")

    result = sources.list_sources(settings, course)

    assert [(s.rel, s.kind) for s in result] == [
        ("ECE 253/Ask uploads/Lecture board /IMG_1.JPG", "photo"),
        ("ECE 253/Ask uploads/Lecture board /IMG_2.webp", "photo"),
        ("ECE 253/Homework/Quiz 1/Quiz_Tips.md", "text"),
        ("ECE 253/SlideDeck 1.pdf", "doc"),
        ("ECE 253/canvasdl", "doc"),
    ]


@pytest.mark.parametrize(
    "course, setup",
    [
        ("../x", None),
        ("Concepts", "folder"),
        ("Archive", "folder"),
        ("Academic Planning", "folder"),
        ("Personal", "folder"),
        (".git", None),
        ("", None),
        ("missing", None),
    ],
)
def test_course_dir_rejects(tmp_path: Path, course: str, setup: str | None) -> None:
    settings = make_settings(tmp_path)
    if setup == "folder":
        (settings.obsidian_academic_vault_dir / course).mkdir()

    with pytest.raises(ValueError):
        sources.course_dir(settings, course)


def test_course_dir_rejects_vault_none(tmp_path: Path) -> None:
    settings = Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "GEMINI_API_KEY": "gem",
            "OPENROUTER_API_KEY": "or",
        }
    )
    with pytest.raises(ValueError):
        sources.course_dir(settings, "ECE 253")


def test_cache_miss_then_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat) -> None:
    settings = make_settings(tmp_path)
    pdf_bytes = b"%PDF-1.7 fake pdf content"
    _write(settings.obsidian_academic_vault_dir / "ECE 253" / "SlideDeck 1.pdf", pdf_bytes)

    fake_render, render_calls = _make_fake_render({"SlideDeck 1.pdf": [b"png1", b"png2"]})
    monkeypatch.setattr(sources, "render_pages", fake_render)
    lect_render_calls: list = []
    monkeypatch.setattr(lecture_docs, "render_pages", lambda kind, srcs, workdir, page_range=None: lect_render_calls.append((kind, srcs, workdir)) or fake_render(kind, srcs, workdir))

    clock = _FakeClock()
    outcome = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/SlideDeck 1.pdf"],
        deadline=100.0,
        clock=clock,
    )

    assert len(fake_chat) == 1
    assert fake_chat[0] == (settings.ocr_model, "low")
    assert outcome.readings
    reading = outcome.readings["ECE 253/SlideDeck 1.pdf"]
    assert reading.exists()
    assert reading.is_relative_to(settings.state_dir / READS_DIR)
    index_path = settings.state_dir / READS_DIR / sources.INDEX_NAME
    assert index_path.exists()
    assert len(render_calls) == 1
    assert render_calls[0][0] == "doc"
    assert not lect_render_calls

    fake_chat.clear()
    render_calls.clear()
    lect_render_calls.clear()
    outcome2 = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/SlideDeck 1.pdf"],
        deadline=100.0,
        clock=clock,
    )

    assert not fake_chat
    assert outcome2.readings["ECE 253/SlideDeck 1.pdf"] == reading
    assert not render_calls
    assert not lect_render_calls


def test_annotation_blind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat
) -> None:
    settings = make_settings(tmp_path)
    pdf_path = settings.obsidian_academic_vault_dir / "ECE 253" / "SlideDeck 1.pdf"
    _write(pdf_path, b"%PDF-1.7 original")

    pages = [b"png1", b"png2"]
    fake_render, render_calls = _make_fake_render({"SlideDeck 1.pdf": pages})
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    clock = _FakeClock()
    outcome = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/SlideDeck 1.pdf"],
        deadline=100.0,
        clock=clock,
    )
    first_path = outcome.readings["ECE 253/SlideDeck 1.pdf"]
    assert len(fake_chat) == 1

    _write(pdf_path, b"%PDF-1.7 completely different bytes much longer than before")
    fake_chat.clear()
    render_calls.clear()

    outcome2 = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/SlideDeck 1.pdf"],
        deadline=100.0,
        clock=clock,
    )
    assert not fake_chat
    assert outcome2.readings["ECE 253/SlideDeck 1.pdf"] == first_path
    assert len(render_calls) == 1  # key re-derived from pixels, no model call

    pages.clear()
    pages.extend([b"png3", b"png4"])
    _write(pdf_path, b"%PDF-1.7 corrected deck, new slides")
    outcome3 = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/SlideDeck 1.pdf"],
        deadline=100.0,
        clock=clock,
    )
    assert len(fake_chat) == 1
    third_path = outcome3.readings["ECE 253/SlideDeck 1.pdf"]
    assert third_path.exists()
    assert third_path != first_path


def test_reader_change_rereads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat) -> None:
    settings = make_settings(tmp_path)
    entry = "ECE 253/SlideDeck 1.pdf"
    _write(settings.obsidian_academic_vault_dir / "ECE 253" / "SlideDeck 1.pdf", b"%PDF-1.7 deck")

    fake_render, _ = _make_fake_render({"SlideDeck 1.pdf": [b"png1", b"png2"]})
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    clock = _FakeClock()
    outcome = sources.read_sources(
        settings,
        "ECE 253",
        [entry],
        deadline=100.0,
        clock=clock,
    )

    assert len(fake_chat) == 1
    first = outcome.readings[entry]
    render_key = _index(settings)[entry][3]

    outcome = sources.read_sources(
        settings,
        "ECE 253",
        [entry],
        deadline=100.0,
        clock=clock,
        doc_model="gemini-other",
    )

    assert len(fake_chat) == 2
    assert fake_chat[-1][0] == "gemini-other"
    second = outcome.readings[entry]
    assert second != first
    assert first.exists()
    assert second.exists()
    assert _index(settings)[entry][3] == render_key

    outcome = sources.read_sources(
        settings,
        "ECE 253",
        [entry],
        deadline=100.0,
        clock=clock,
    )

    assert len(fake_chat) == 2
    assert outcome.readings[entry] == first


def test_photo_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat
) -> None:
    settings = make_settings(tmp_path)
    _write(
        settings.obsidian_academic_vault_dir / "ECE 253" / "Ask uploads" / "Lecture board " / "IMG_1.JPG",
        b"\xff\xd8\xff\xe0",
    )

    fake_render, _ = _make_fake_render({})
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    clock = _FakeClock()
    outcome = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/Ask uploads/Lecture board /IMG_1.JPG"],
        deadline=100.0,
        clock=clock,
    )

    assert len(fake_chat) == 1
    assert fake_chat[0] == (sources.PHOTO_MODEL, sources.PHOTO_EFFORT)
    assert outcome.readings


def test_budget_already_spent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat
) -> None:
    settings = make_settings(tmp_path)
    pdf_path = settings.obsidian_academic_vault_dir / "ECE 253" / "SlideDeck 1.pdf"
    _write(pdf_path, b"%PDF-1.7 budget test")

    fake_render, render_calls = _make_fake_render({"SlideDeck 1.pdf": [b"png1"]})
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    clock = _FakeClock(default=5.0)
    uncached = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/SlideDeck 1.pdf"],
        deadline=1.0,
        clock=clock,
    )
    assert not fake_chat
    assert not render_calls
    assert "ECE 253/SlideDeck 1.pdf" in uncached.skipped
    assert not (settings.state_dir / READS_DIR / sources.INDEX_NAME).exists()

    clock = _FakeClock()
    cached = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/SlideDeck 1.pdf"],
        deadline=100.0,
        clock=clock,
    )
    assert len(fake_chat) == 1
    cached_path = cached.readings["ECE 253/SlideDeck 1.pdf"]

    fake_chat.clear()
    render_calls.clear()
    spent = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/SlideDeck 1.pdf"],
        deadline=1.0,
        clock=_FakeClock(default=5.0),
    )
    assert not fake_chat
    assert not render_calls
    assert spent.readings["ECE 253/SlideDeck 1.pdf"] == cached_path


def test_budget_mid_file_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat
) -> None:
    settings = make_settings(tmp_path)
    _write(
        settings.obsidian_academic_vault_dir / "ECE 253" / "BigDeck.pdf",
        b"%PDF-1.7 big deck",
    )

    pages = [f"png{i}".encode() for i in range(10)]
    fake_render, _ = _make_fake_render({"BigDeck.pdf": pages})
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    class AdvancingClock:
        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = AdvancingClock()
    orig_chat = lecture_docs.chat

    def advancing_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None) -> str:
        result = orig_chat(messages, model, api_key=api_key, reasoning_effort=reasoning_effort, timeout_s=timeout_s, url=url)
        clock.now = 9.0
        return result

    monkeypatch.setattr(lecture_docs, "chat", advancing_chat)

    outcome = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/BigDeck.pdf"],
        deadline=5.0,
        clock=clock,
    )

    assert "ECE 253/BigDeck.pdf" in outcome.skipped
    assert len(fake_chat) == 1
    reads_dir = settings.state_dir / READS_DIR
    assert list(reads_dir.glob("*.partial.json"))

    monkeypatch.setattr(lecture_docs, "chat", orig_chat)
    fake_chat.clear()
    outcome2 = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/BigDeck.pdf"],
        deadline=100.0,
        clock=_FakeClock(),
    )
    assert len(fake_chat) == 1
    reading = outcome2.readings["ECE 253/BigDeck.pdf"]
    assert reading.exists()


def test_failures_do_not_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat
) -> None:
    settings = make_settings(tmp_path)
    _write(settings.obsidian_academic_vault_dir / "ECE 253" / "Huge.pdf", b"%PDF-1.7 huge")
    _write(settings.obsidian_academic_vault_dir / "ECE 253" / "Normal.pdf", b"%PDF-1.7 normal")

    def flaky_render(kind: str, srcs, workdir, page_range=None) -> list[tuple[str, bytes]]:
        if any(Path(src).name == "Huge.pdf" for src in srcs):
            raise TooManyPages("200 pages")
        if kind == "doc":
            return [("image/png", b"png-normal")]
        return [("image/jpeg", b"jpg")]

    monkeypatch.setattr(sources, "render_pages", flaky_render)
    monkeypatch.setattr(lecture_docs, "render_pages", flaky_render)

    clock = _FakeClock()
    outcome = sources.read_sources(
        settings,
        "ECE 253",
        [
            "ECE 253/Huge.pdf",
            "ECE 253/Normal.pdf",
            "ECE 253/missing.pdf",
        ],
        deadline=100.0,
        clock=clock,
    )

    assert "TooManyPages" in outcome.failed["ECE 253/Huge.pdf"]
    assert len(fake_chat) == 1
    assert "ECE 253/Normal.pdf" in outcome.readings
    assert "not a source of ECE 253" in outcome.failed["ECE 253/missing.pdf"]


def test_text_file_resolves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat) -> None:
    settings = make_settings(tmp_path)
    md_path = settings.obsidian_academic_vault_dir / "ECE 253" / "Homework" / "Quiz 1" / "Quiz_Tips.md"
    _write(md_path, "# Tips\n")

    render_calls: list = []
    monkeypatch.setattr(sources, "render_pages", lambda *a, **kw: render_calls.append((a, kw)) or [])
    monkeypatch.setattr(lecture_docs, "render_pages", lambda *a, **kw: render_calls.append((a, kw)) or [])

    clock = _FakeClock()
    outcome = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/Homework/Quiz 1/Quiz_Tips.md"],
        deadline=100.0,
        clock=clock,
    )

    assert outcome.readings["ECE 253/Homework/Quiz 1/Quiz_Tips.md"] == md_path.resolve()
    assert not fake_chat
    assert not render_calls


def test_model_error_fails_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    _write(
        settings.obsidian_academic_vault_dir / "ECE 253" / "SlideDeck 1.pdf",
        b"%PDF-1.7 error test",
    )

    fake_render, _ = _make_fake_render({"SlideDeck 1.pdf": [b"png1"]})
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    def boom(messages, model, *, api_key, reasoning_effort, timeout_s, url=None) -> str:
        raise GeminiError("boom")

    monkeypatch.setattr(lecture_docs, "chat", boom)

    clock = _FakeClock()
    outcome = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/SlideDeck 1.pdf"],
        deadline=100.0,
        clock=clock,
    )
    assert outcome.failed == {"ECE 253/SlideDeck 1.pdf": "GeminiError: boom"}
    assert outcome.readings == {}
    assert (settings.state_dir / READS_DIR / sources.INDEX_NAME).exists()


def test_index_prune(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat) -> None:
    settings = make_settings(tmp_path)
    _write(settings.obsidian_academic_vault_dir / "ECE 253" / "A.pdf", b"%PDF-1.7 a")
    _write(settings.obsidian_academic_vault_dir / "ECE 253" / "B.pdf", b"%PDF-1.7 b")

    fake_render, _ = _make_fake_render({"A.pdf": [b"a1"], "B.pdf": [b"b1"]})
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    first_clock = _FakeClock()
    sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/A.pdf", "ECE 253/B.pdf"],
        deadline=100.0,
        clock=first_clock,
    )

    (settings.obsidian_academic_vault_dir / "ECE 253" / "B.pdf").unlink()
    index_path = settings.state_dir / READS_DIR / sources.INDEX_NAME
    index_data = json.loads(index_path.read_text())
    index_data["files"]["ECE 108/x.pdf"] = [1, 2, "sha108", "key108"]
    index_path.write_text(json.dumps(index_data))

    sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/A.pdf"],
        deadline=100.0,
        clock=_FakeClock(),
    )

    updated = _index(settings)
    assert "ECE 253/B.pdf" not in updated
    assert "ECE 253/A.pdf" in updated
    assert "ECE 108/x.pdf" in updated


def test_list_sources_unified_folders(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    _write(vault / "ECE 253" / "Slides" / "Deck.pdf", b"%PDF-1.7 x")
    _write(vault / "ECE 253" / "Textbooks" / "Book.pdf", b"%PDF-1.7 x")
    _write(vault / "ECE 253" / "Readings" / "Paper.pdf", b"%PDF-1.7 x")
    _write(vault / "ECE 253" / "syllabus.pdf", b"%PDF-1.7 x")
    _write(vault / "ECE 108" / "Readings" / "Other.pdf", b"%PDF-1.7 x")

    listed = [(s.rel, s.kind) for s in sources.list_sources(settings, "ECE 253")]

    assert listed == [
        ("ECE 253/Readings/Paper.pdf", "doc"),
        ("ECE 253/Slides/Deck.pdf", "doc"),
        ("ECE 253/Textbooks/Book.pdf", "doc"),
        ("ECE 253/syllabus.pdf", "doc"),
    ]


def test_list_sources_allowlist_and_output_dirs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    _write(vault / "ECE 253" / "Slides.pdf", b"%PDF-1.7 x")
    _write(vault / "ECE 253" / "Study notes" / "mine.md", "text")
    _write(vault / "ECE 253" / "Transcripts" / "2026-10-01.json", "[]")
    _write(vault / "ECE 253" / "Lecture notes" / "n.md", "text")
    _write(vault / "ECE 253" / "Agent scratch" / "a.md", "text")
    _write(vault / "ECE 253" / "Week 1" / "n.md", "text")
    (vault / "ECE 253" / "Empty").mkdir()
    _write(vault / "ECE 253" / "Textbooks" / "b.pdf", b"%PDF-1.7 x")
    _write(vault / "ECE 253" / "Textbooks" / "Study notes" / "x.md", "text")
    _write(vault / "ECE 253" / "Readings" / "r.pdf", b"%PDF-1.7 x")

    with caplog.at_level(logging.WARNING, logger="libra.sources"):
        listed = [s.rel for s in sources.list_sources(settings, "ECE 253")]

    assert listed == [
        "ECE 253/Readings/r.pdf",
        "ECE 253/Slides.pdf",
        "ECE 253/Textbooks/b.pdf",
    ]
    assert len(caplog.records) == 1
    assert "Week 1" in caplog.records[0].getMessage()


def test_list_sources_skips_outdated_folders(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir

    _write(vault / "ECE 158A" / "Slides" / "Lec7-Add-Multicast Notes.pdf", b"%PDF-1.7 x")
    _write(vault / "ECE 158A" / "Slides" / "Outdated" / "Lec7-Addendum.pdf", b"%PDF-1.7 x")
    _write(vault / "ECE 158A" / "Homework" / "Outdated" / "Week 1" / "old.pdf", b"%PDF-1.7 x")
    _write(vault / "ECE 158A" / "Readings" / "outdated" / "keep.pdf", b"%PDF-1.7 x")

    listed = [s.rel for s in sources.list_sources(settings, "ECE 158A")]

    assert listed == ["ECE 158A/Readings/outdated/keep.pdf", "ECE 158A/Slides/Lec7-Add-Multicast Notes.pdf"]


def test_source_roots_skips_missing_and_symlinked(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    _write(vault / "ECE 253" / "File.pdf", b"%PDF-1.7 x")

    assert sources.source_roots(settings, "ECE 253") == [(vault / "ECE 253").resolve()]

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _write(elsewhere / "Outside.pdf", b"%PDF-1.7 x")
    (vault / "ECE 253" / "Textbooks").symlink_to(elsewhere)

    assert sources.source_roots(settings, "ECE 253") == [(vault / "ECE 253").resolve()]
    assert not any(
        s.rel.startswith("ECE 253/Textbooks/")
        for s in sources.list_sources(settings, "ECE 253")
    )


def test_moved_file_reuses_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat: list[tuple[str, str]]
) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    _write(vault / "ECE 253" / "Deck.pdf", b"%PDF-1.7 deck")

    fake_render, render_calls = _make_fake_render({"Deck.pdf": [b"p1", b"p2"]})
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    outcome = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/Deck.pdf"],
        deadline=100.0,
        clock=_FakeClock(),
    )
    first = outcome.readings["ECE 253/Deck.pdf"]
    assert len(fake_chat) == 1

    new_dir = vault / "ECE 253" / "Textbooks"
    new_dir.mkdir(parents=True)
    (vault / "ECE 253" / "Deck.pdf").rename(new_dir / "Deck.pdf")
    fake_chat.clear()

    outcome2 = sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/Textbooks/Deck.pdf"],
        deadline=100.0,
        clock=_FakeClock(),
    )

    assert fake_chat == []
    assert outcome2.readings["ECE 253/Textbooks/Deck.pdf"] == first
    assert outcome2.failed == {}
    index = _index(settings)
    assert "ECE 253/Textbooks/Deck.pdf" in index
    assert "ECE 253/Deck.pdf" not in index


def test_index_prune_unified_prefixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_chat: list[tuple[str, str]]
) -> None:
    settings = make_settings(tmp_path)
    vault = settings.obsidian_academic_vault_dir
    _write(vault / "ECE 253" / "A.pdf", b"%PDF-1.7 x")

    fake_render, render_calls = _make_fake_render({"A.pdf": [b"a1"]})
    monkeypatch.setattr(sources, "render_pages", fake_render)
    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)

    sources.read_sources(
        settings,
        "ECE 253",
        ["ECE 253/A.pdf"],
        deadline=100.0,
        clock=_FakeClock(),
    )

    index_path = settings.state_dir / READS_DIR / sources.INDEX_NAME
    data = json.loads(index_path.read_text())
    data["files"]["ECE 253/Textbooks/gone.pdf#pages=1-9"] = [1, 2, "s", "k"]
    data["files"]["ECE 253/Readings/gone.pdf"] = [1, 2, "s", "k"]
    data["files"]["ECE 108/Readings/keep.pdf"] = [1, 2, "s", "k"]
    index_path.write_text(json.dumps(data))

    sources.read_sources(settings, "ECE 253", [], deadline=100.0, clock=_FakeClock())

    index = _index(settings)
    assert "ECE 253/Textbooks/gone.pdf#pages=1-9" not in index
    assert "ECE 253/Readings/gone.pdf" not in index
    assert "ECE 108/Readings/keep.pdf" in index
    assert "ECE 253/A.pdf" in index
