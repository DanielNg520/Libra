from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from libra.config import Settings
from libra.gemini import GeminiError
from libra import textbooks
from libra.lecture_docs import READS_DIR


def make_settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir()
    return Settings.load(
        {
            "SEMAI_STATE_DIR": str(tmp_path / "state"),
            "SEMAI_OBSIDIAN_ACADEMIC_VAULT_DIR": str(vault),
            "GEMINI_API_KEY": "gem",
            "OPENROUTER_API_KEY": "or",
        }
    )


def _filler_words(n: int) -> str:
    return " ".join(f"word_{i}" for i in range(n))


def make_texts(pages: int = 120, offset: int = 10, index_printed: int = 100) -> list[str]:
    texts: list[str] = []
    for i in range(1, pages + 1):
        if i <= offset:
            texts.append(_filler_words(80))
            continue
        printed = i - offset
        lines = [str(printed), "Index"] if printed == index_printed else [str(printed)]
        lines.append(_filler_words(80))
        texts.append("\n".join(lines))
    return texts


def _chat_reply() -> str:
    payload = {
        "title": "Pattern Things",
        "authors": "A. Author",
        "edition": "2nd",
        "year": 2006,
        "chapters": [
            {"title": "Intro", "start": 1, "sections": []},
            {
                "title": "Long Chapter",
                "start": 21,
                "sections": [
                    {"title": "Part A", "start": 21},
                    {"title": "Part B", "start": 50},
                    {"title": "Part C", "start": 80},
                ],
            },
            {"title": "Last", "start": 95, "sections": []},
        ],
        "index_start": 100,
    }
    return json.dumps(payload)


def _patch_pdf_texts(monkeypatch: pytest.MonkeyPatch, texts: list[str]) -> None:
    monkeypatch.setattr(textbooks, "pdf_page_texts", lambda path: texts)


def _fake_chat(reply: str) -> Any:
    def fn(
        messages: list[dict[str, Any]],
        model: str,
        *,
        api_key: str,
        reasoning_effort: str,
        timeout_s: float,
        json_mode: bool,
    ) -> str:
        assert json_mode is True
        assert any("=== PDF page 1 ===" in m["content"] for m in messages if m.get("role") != "system")
        return reply

    return fn


def test_page_labels() -> None:
    filler = _filler_words(80)
    texts = [
        "1\n" + filler,
        filler + "\n2",
        "This is page 3\n" + filler,
        "77\n" + filler,
        "5\n" + filler + "\n9",
        filler,
    ]
    labels = textbooks.page_labels(texts)
    assert labels == [(1, 1), (2, 2), (3, 3), (5, 5)]


def test_page_labels_number_above_page_index() -> None:
    filler = _filler_words(80)
    texts = [f"{n}\n" + filler for n in (10, 11, 12, 13)]
    labels = textbooks.page_labels(texts)
    assert labels == [(1, 10), (2, 11), (3, 12), (4, 13)]


def test_locate_clean_offset() -> None:
    labels = [(i, i - 7) for i in range(10, 30)]
    assert textbooks.locate(labels, 10, 100) == 17


def test_locate_too_few_votes() -> None:
    labels = [(10, 3), (11, 4)]
    assert textbooks.locate(labels, 10, 100) is None


def test_locate_mixed_offsets() -> None:
    labels = [(10, 3), (11, 4), (12, 4), (13, 4), (14, 4)]
    assert textbooks.locate(labels, 3, 100) is None


def test_locate_past_end() -> None:
    labels = [(i, i - 7) for i in range(10, 15)]
    assert textbooks.locate(labels, 5, 11) is None
    assert textbooks.locate(labels, 5, 12) == 12


def test_build_entries_splitting() -> None:
    chapters = [
        ("Intro", 1, []),
        ("Long Chapter", 21, [("Part A", 21), ("Part B", 50), ("Part C", 80)]),
        ("Last", 95, []),
    ]
    entries = textbooks.build_entries(chapters, 100, 110)
    assert [(e.title, e.first, e.last, e.sections) for e in entries] == [
        ("Intro", 1, 20, ()),
        ("Long Chapter (part 1/2)", 21, 79, ("Part B",)),
        ("Long Chapter (part 2/2)", 80, 94, ("Part C",)),
        ("Last", 95, 99, ()),
    ]


def test_build_entries_drops_non_increasing() -> None:
    chapters = [
        ("A", 10, []),
        ("B", 5, []),
        ("C", 20, []),
    ]
    entries = textbooks.build_entries(chapters, None, 30)
    assert [(e.title, e.first, e.last) for e in entries] == [
        ("A", 10, 19),
        ("C", 20, 30),
    ]


def test_build_entries_index_end() -> None:
    chapters = [("A", 1, []), ("B", 10, [])]
    entries = textbooks.build_entries(chapters, 25, 100)
    assert [(e.title, e.first, e.last) for e in entries] == [
        ("A", 1, 9),
        ("B", 10, 24),
    ]


def test_has_gap() -> None:
    def labels(runs: list[tuple[int, int]]) -> list[tuple[int, int]]:
        labels: list[tuple[int, int]] = []
        page = 100
        for offset, count in runs:
            for _ in range(count):
                labels.append((page, page - offset))
                page += 1
        return labels

    assert textbooks.has_gap(labels([(15, 6), (-31, 6)]))
    assert not textbooks.has_gap(labels([(18, 6), (17, 6), (16, 6)]))
    assert not textbooks.has_gap(labels([(10, 6), (121, 2), (10, 6)]))
    assert not textbooks.has_gap(labels([(5, 6), (40, 6)]))
    assert not textbooks.has_gap([])


def test_build_entries_sections_in_page_order() -> None:
    entries = textbooks.build_entries([("Ch", 1, [("Zeta", 5), ("Alpha", 10), ("Mid", 3)])], None, 20)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.title == "Ch"
    assert entry.first == 1
    assert entry.last == 20
    assert entry.sections == ("Mid", "Zeta", "Alpha")


def test_normalize_title() -> None:
    assert textbooks.normalize_title("The Elements of Statistical Learning: Data Mining") == "elements of statistical learning data mining"
    assert textbooks.normalize_title(" Pattern Recognition!  and Machine Learning ") == "pattern recognition and machine learning"
    assert textbooks.normalize_title("the quick  brown fox") == "quick brown fox"


def test_is_searchable_empty() -> None:
    assert textbooks.is_searchable([]) is False


def test_is_searchable_sparse() -> None:
    texts = ["word " * 10, "word " * 100, "word " * 5]
    assert textbooks.is_searchable(texts) is False


def test_is_searchable_dense() -> None:
    texts = ["word " * 60, "word " * 80, "word " * 120]
    assert textbooks.is_searchable(texts) is True


def test_book_map_full_build_and_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    texts = make_texts()
    _patch_pdf_texts(monkeypatch, texts)
    chat_fn = _fake_chat("```json\n" + _chat_reply() + "\n```")
    path = tmp_path / "book.pdf"
    path.write_bytes(b"x")
    sha = "abc123"

    result = textbooks.book_map(settings, path, sha, chat_fn=chat_fn)
    assert result.pages == 120
    assert result.searchable is True
    assert result.complete is True
    assert result.edition == "2nd"
    assert result.year == 2006
    assert result.built is True
    assert [(e.title, e.first, e.last, e.sections) for e in result.entries] == [
        ("Intro", 11, 30, ()),
        ("Long Chapter (part 1/2)", 31, 89, ("Part B",)),
        ("Long Chapter (part 2/2)", 90, 104, ("Part C",)),
        ("Last", 105, 109, ()),
    ]

    cache_file = settings.state_dir / READS_DIR / "books" / f"{sha}.json"
    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert data["version"] == 1

    def raises(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("chat_fn called on cached map")

    cached = textbooks.book_map(settings, path, sha, chat_fn=raises)
    assert cached.built is False
    assert cached.entries == result.entries


def test_book_map_key_mismatch_rebuilds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    settings = make_settings(tmp_path)
    texts = make_texts()
    _patch_pdf_texts(monkeypatch, texts)

    sha = "k1"
    textbooks.book_map(settings, tmp_path / "book.pdf", sha, chat_fn=_fake_chat(_chat_reply()))
    cache_path = settings.state_dir / textbooks.READS_DIR / "books" / f"{sha}.json"
    cached = json.loads(cache_path.read_text())
    assert cached["key"] == textbooks.MAP_KEY

    cached["key"] = "stale"
    cache_path.write_text(json.dumps(cached))

    calls = 0

    def counting_chat(*args: Any, **kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        return _chat_reply()

    result = textbooks.book_map(settings, tmp_path / "book.pdf", sha, chat_fn=counting_chat)
    assert calls == 1
    assert result.built is True


def test_book_map_unusable_fresh_served_from_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    texts = make_texts(pages=40, offset=10, index_printed=100)
    _patch_pdf_texts(monkeypatch, texts)

    reply = json.loads(_chat_reply())
    reply["chapters"] = [
        {"title": "Near", "start": 1, "sections": []},
        {"title": "Far", "start": 500, "sections": []},
        {"title": "Farther", "start": 900, "sections": []},
    ]

    sha = "k2"
    textbooks.book_map(settings, tmp_path / "book.pdf", sha, chat_fn=_fake_chat(json.dumps(reply)))

    def raises(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("chat_fn called")

    result = textbooks.book_map(settings, tmp_path / "book.pdf", sha, chat_fn=raises)
    assert result.entries == ()
    assert result.built is False


def test_book_map_unusable_stale_rebuilds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import time

    settings = make_settings(tmp_path)
    texts = make_texts(pages=40, offset=10, index_printed=100)
    _patch_pdf_texts(monkeypatch, texts)

    reply = json.loads(_chat_reply())
    reply["chapters"] = [
        {"title": "Near", "start": 1, "sections": []},
        {"title": "Far", "start": 500, "sections": []},
        {"title": "Farther", "start": 900, "sections": []},
    ]

    sha = "k3"
    textbooks.book_map(settings, tmp_path / "book.pdf", sha, chat_fn=_fake_chat(json.dumps(reply)))
    cache_path = settings.state_dir / textbooks.READS_DIR / "books" / f"{sha}.json"
    os.utime(cache_path, (time.time() - textbooks.UNUSABLE_RETRY_S - 60,) * 2)

    calls = 0

    def counting_chat(*args: Any, **kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        return json.dumps(reply)

    result = textbooks.book_map(settings, tmp_path / "book.pdf", sha, chat_fn=counting_chat)
    assert calls == 1
    assert result.built is True


def test_book_map_index_beyond_book(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    texts = make_texts(pages=110, offset=10, index_printed=115)
    _patch_pdf_texts(monkeypatch, texts)
    chat_fn = _fake_chat(_chat_reply())
    path = tmp_path / "book.pdf"
    path.write_bytes(b"x")

    result = textbooks.book_map(settings, path, "sha1", chat_fn=chat_fn)
    assert result.complete is False


def test_book_map_few_chapters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    texts = make_texts(pages=40, offset=10, index_printed=100)
    _patch_pdf_texts(monkeypatch, texts)
    reply = json.loads(_chat_reply())
    reply["chapters"] = [
        {"title": "Near", "start": 1, "sections": []},
        {"title": "Far", "start": 500, "sections": []},
        {"title": "Farther", "start": 900, "sections": []},
    ]
    chat_fn = _fake_chat(json.dumps(reply))
    path = tmp_path / "book.pdf"
    path.write_bytes(b"x")

    result = textbooks.book_map(settings, path, "sha2", chat_fn=chat_fn)
    assert result.entries == ()


def test_parse_json_reply_repairs_invalid_escapes() -> None:
    reply = r'{"text": "Gain 5\% at x\_1 and \(a\) \{b\}"}'
    parsed = textbooks._parse_json_reply(reply)
    assert parsed["text"] == r"Gain 5\% at x\_1 and \(a\) \{b\}"


def test_parse_json_reply_keeps_valid_escapes_when_repairing() -> None:
    reply = r'{"a": "\\frac{1}{2} \% \"q\" \u00e9\nend"}'
    parsed = textbooks._parse_json_reply(reply)
    assert parsed["a"] == "\\frac{1}{2} \\% \"q\" é\nend"


def test_parse_json_reply_odd_backslash_run() -> None:
    reply = r'{"a": "x\\\%y"}'
    parsed = textbooks._parse_json_reply(reply)
    assert parsed["a"] == "x\\\\%y"


def test_parse_json_reply_repairs_inside_fence() -> None:
    reply = '```json\n' + r'{"text": "Gain 5\% at x\_1 and \(a\) \{b\}"}' + '\n```'
    parsed = textbooks._parse_json_reply(reply)
    assert parsed["text"] == r"Gain 5\% at x\_1 and \(a\) \{b\}"


def test_parse_json_reply_other_errors_still_raise() -> None:
    with pytest.raises(textbooks.BookMapError, match="Invalid JSON reply"):
        textbooks._parse_json_reply("not json {")


def test_parse_json_reply_unrepairable_raises() -> None:
    with pytest.raises(textbooks.BookMapError, match="Invalid JSON reply"):
        textbooks._parse_json_reply(r'{"a": "x\%"')


def test_parse_json_reply_repairs_invalid_u_escape() -> None:
    parsed = textbooks._parse_json_reply(r'{"a": "\underline{x} and \upsilon"}')
    assert parsed["a"] == r"\underline{x} and \upsilon"


def test_parse_json_reply_repairs_mixed_u_and_brace_escapes() -> None:
    parsed = textbooks._parse_json_reply(r'{"a": "\underline{v} \{b\} \\frac{1}{2} é"}')
    assert parsed["a"] == "\\underline{v} \\{b\\} \\frac{1}{2} é"


def test_book_map_malformed_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    _patch_pdf_texts(monkeypatch, make_texts())
    chat_fn = _fake_chat("not json {")
    path = tmp_path / "book.pdf"
    path.write_bytes(b"x")
    sha = "sha3"

    with pytest.raises(textbooks.BookMapError):
        textbooks.book_map(settings, path, sha, chat_fn=chat_fn)
    cache_file = settings.state_dir / READS_DIR / "books" / f"{sha}.json"
    assert not cache_file.exists()


def test_book_map_missing_title_uses_file_stem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    _patch_pdf_texts(monkeypatch, make_texts())
    reply = json.loads(_chat_reply())
    del reply["title"]
    path = tmp_path / "Duda copy.pdf"
    path.write_bytes(b"x")
    result = textbooks.book_map(settings, path, "sha6", chat_fn=_fake_chat(json.dumps(reply)))
    assert result.title == "Duda copy"
    assert result.built is True
    assert (settings.state_dir / READS_DIR / "books" / "sha6.json").exists()


def test_book_map_gemini_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    _patch_pdf_texts(monkeypatch, make_texts())

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        raise GeminiError("boom")

    path = tmp_path / "book.pdf"
    path.write_bytes(b"x")
    sha = "sha4"

    with pytest.raises(GeminiError):
        textbooks.book_map(settings, path, sha, chat_fn=chat_fn)
    cache_file = settings.state_dir / READS_DIR / "books" / f"{sha}.json"
    assert not cache_file.exists()


def test_book_map_scanned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    texts = ["word " * 10] * 30
    _patch_pdf_texts(monkeypatch, texts)

    rendered_calls: list[tuple[Any, ...]] = []

    def render_pages(kind: str, sources: list[Path], workdir: Path, page_range: tuple[int, int] | None = None) -> list[tuple[str, bytes]]:
        rendered_calls.append((kind, sources, workdir, page_range))
        return [("image/png", b"x")]

    def read_pages(settings_: Settings, prompt: str, pages: list[tuple[str, bytes]], *, model: str, effort: str) -> str:
        return json.dumps({
            "title": "Scanned Book",
            "authors": "Unreadable",
            "edition": "1st",
            "year": 1999,
        })

    monkeypatch.setattr(textbooks, "render_pages", render_pages)
    monkeypatch.setattr(textbooks, "read_pages", read_pages)

    chat_called = False

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        nonlocal chat_called
        chat_called = True
        raise AssertionError("chat_fn should not be called")

    path = tmp_path / "scanned.pdf"
    path.write_bytes(b"x")

    result = textbooks.book_map(settings, path, "sha5", chat_fn=chat_fn)
    assert result.searchable is False
    assert result.complete is False
    assert result.entries == ()
    assert result.title == "Scanned Book"
    assert not chat_called
    assert len(rendered_calls) == 1
    call_path = rendered_calls[0][1][0]
    assert call_path == path
    assert rendered_calls[0][3] == (1, 12)
    assert rendered_calls[0][0] == "doc"


def _make_book(
    title: str,
    edition: str,
    year: int,
    pages: int,
    *,
    complete: bool = True,
    searchable: bool = True,
    built: bool = False,
    authors: str = "Test Author",
) -> textbooks.BookMap:
    return textbooks.BookMap(
        title=title,
        authors=authors,
        edition=edition,
        year=year,
        pages=pages,
        searchable=searchable,
        complete=complete,
        entries=(),
        built=built,
    )


def test_check_copies_incomplete_report_only(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    bad_path = settings.obsidian_academic_vault_dir / "bad.pdf"
    bad_path.write_bytes(b"data")
    good = _make_book("Same Title", "2nd", 2010, 200)
    incomplete = _make_book("Same Title", "2nd", 2010, 200, complete=False)
    lines = textbooks.check_copies(settings, {"good.pdf": good, "bad.pdf": incomplete}, linked=set(), delete=False)
    assert lines == ["bad.pdf: incomplete; keep good.pdf (report only)"]
    assert bad_path.exists()

def test_check_copies_incomplete_delete(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    course_dir = settings.obsidian_academic_vault_dir / "ECE 253" / "Textbooks"
    course_dir.mkdir(parents=True)
    bad_path = course_dir / "bad.pdf"
    bad_path.write_bytes(b"data")
    good_path = course_dir / "good.pdf"
    good_path.write_bytes(b"good")
    good = _make_book("Same Title", "2nd", 2010, 200)
    incomplete = _make_book("Same Title", "2nd", 2010, 200, complete=False)
    lines = textbooks.check_copies(
        settings,
        {"ECE 253/Textbooks/good.pdf": good, "ECE 253/Textbooks/bad.pdf": incomplete},
        linked=set(),
        delete=True,
    )
    assert lines == ["ECE 253/Textbooks/bad.pdf: incomplete; keep ECE 253/Textbooks/good.pdf (deleted)"]
    assert not bad_path.exists()
    assert good_path.read_bytes() == b"good"

def test_check_copies_delete_nested_textbooks_kept(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    course_dir = settings.obsidian_academic_vault_dir / "ECE 253" / "Textbooks" / "old"
    course_dir.mkdir(parents=True)
    bad_path = course_dir / "bad.pdf"
    bad_path.write_bytes(b"data")
    good_path = course_dir / "good.pdf"
    good_path.write_bytes(b"good")
    good = _make_book("Same Title", "2nd", 2010, 200)
    incomplete = _make_book("Same Title", "2nd", 2010, 200, complete=False)
    lines = textbooks.check_copies(
        settings,
        {"ECE 253/Textbooks/old/good.pdf": good, "ECE 253/Textbooks/old/bad.pdf": incomplete},
        linked=set(),
        delete=True,
    )
    assert lines == ["ECE 253/Textbooks/old/bad.pdf: incomplete; keep ECE 253/Textbooks/old/good.pdf (outside Textbooks, kept)"]
    assert bad_path.exists()
    assert good_path.read_bytes() == b"good"


def test_check_copies_delete_outside_textbooks_kept(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    bad_path = settings.obsidian_academic_vault_dir / "bad.pdf"
    bad_path.write_bytes(b"data")
    good_path = settings.obsidian_academic_vault_dir / "good.pdf"
    good_path.write_bytes(b"good")
    good = _make_book("Same Title", "2nd", 2010, 200)
    incomplete = _make_book("Same Title", "2nd", 2010, 200, complete=False)
    lines = textbooks.check_copies(settings, {"good.pdf": good, "bad.pdf": incomplete}, linked=set(), delete=True)
    assert lines == ["bad.pdf: incomplete; keep good.pdf (outside Textbooks, kept)"]
    assert bad_path.exists()
    assert good_path.read_bytes() == b"good"


def test_check_copies_delete_textbooks_root_kept(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    textbooks_dir = settings.obsidian_academic_vault_dir / "Textbooks"
    textbooks_dir.mkdir(parents=True)
    bad_path = textbooks_dir / "bad.pdf"
    bad_path.write_bytes(b"data")
    good_path = textbooks_dir / "good.pdf"
    good_path.write_bytes(b"good")
    good = _make_book("Same Title", "2nd", 2010, 200)
    incomplete = _make_book("Same Title", "2nd", 2010, 200, complete=False)
    lines = textbooks.check_copies(
        settings,
        {"Textbooks/good.pdf": good, "Textbooks/bad.pdf": incomplete},
        linked=set(),
        delete=True,
    )
    assert lines == ["Textbooks/bad.pdf: incomplete; keep Textbooks/good.pdf (outside Textbooks, kept)"]
    assert bad_path.exists()
    assert good_path.read_bytes() == b"good"

def test_check_copies_linked_kept(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    good = _make_book("Same Title", "2nd", 2010, 200)
    incomplete = _make_book("Same Title", "2nd", 2010, 200, complete=False)
    lines = textbooks.check_copies(settings, {"good.pdf": good, "bad.pdf": incomplete}, linked={"bad.pdf"}, delete=True)
    assert lines == ["bad.pdf: incomplete; keep good.pdf (linked, kept)"]

def test_check_copies_built_kept(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    good = _make_book("Same Title", "2nd", 2010, 200)
    incomplete = _make_book("Same Title", "2nd", 2010, 200, complete=False, built=True)
    lines = textbooks.check_copies(settings, {"good.pdf": good, "bad.pdf": incomplete}, linked=set(), delete=True)
    assert lines == ["bad.pdf: incomplete; keep good.pdf (built this run, kept)"]

def test_check_copies_edition_logged_only(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    old_path = settings.obsidian_academic_vault_dir / "old.pdf"
    old_path.write_bytes(b"data")
    old = _make_book("Same Title", "1st", 2005, 100)
    new = _make_book("Same Title", "2nd", 2010, 200)
    lines = textbooks.check_copies(settings, {"old.pdf": old, "new.pdf": new}, linked=set(), delete=True)
    assert lines == ["old.pdf: older or same edition; keep new.pdf (logged only)"]
    assert old_path.exists()

def test_check_copies_different_titles(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    a = _make_book("Alpha", "1st", 2000, 100)
    b = _make_book("Beta", "1st", 2000, 100)
    assert textbooks.check_copies(settings, {"a.pdf": a, "b.pdf": b}, linked=set(), delete=True) == []


def test_check_copies_distinct_volumes_not_grouped(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    a = _make_book("Probabilistic Machine Learning: An Introduction", "1st", 2000, 100)
    b = _make_book("Probabilistic Machine Learning: Advanced Topics", "1st", 2000, 100, complete=False)
    assert textbooks.check_copies(settings, {"a.pdf": a, "b.pdf": b}, linked=set(), delete=True) == []


def test_check_copies_same_title_other_authors_not_grouped(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    a = _make_book("Signals and Systems", "1st", 2000, 100, authors="Oppenheim, Willsky")
    b = _make_book("Signals and Systems", "1st", 2000, 100, complete=False, authors="Haykin, Van Veen")
    assert textbooks.check_copies(settings, {"a.pdf": a, "b.pdf": b}, linked=set(), delete=True) == []
