import base64
import json
import re
from pathlib import Path

import pytest

from libra.config import Settings
from libra.gemini import GeminiCapError, GeminiError
from libra import lecture_docs
from libra.lecture_docs import (
    BATCH_PAGES,
    OPENROUTER_CHAT_URL,
    READS_DIR,
    TooManyPages,
)


def make_settings(tmp_path: Path) -> Settings:
    return Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "GEMINI_API_KEY": "gem",
            "OPENROUTER_API_KEY": "or",
        }
    )


KEY = "a" * 64
COURSE = "ECE 108"
KIND = "doc"
PATHS = ["ECE 108/lecture1.pdf"]
MODEL = "gemini-3.5-flash"
EFFORT = "medium"


def fake_render(kind, sources, workdir):
    return [("image/png", f"p{i}".encode()) for i in range(10)]


def _headed(messages, text):
    return "\n\n".join(f"### Page 0\n{text}" for _ in range(len(messages[0]["content"]) - 1))


def _page_numbers(content):
    return [int(n) for n in re.findall(r"^### Page (\d+)$", content, re.MULTILINE)]


def _run_read_document(
    monkeypatch,
    settings,
    chat,
    pages,
    sources,
    on_batch=None,
):
    monkeypatch.setattr(lecture_docs, "chat", chat)
    monkeypatch.setattr(lecture_docs, "render_pages", lambda *a, **kw: pages)
    return lecture_docs.read_document(
        settings,
        key=KEY,
        course=COURSE,
        kind=KIND,
        paths=PATHS,
        sources=sources,
        model=MODEL,
        effort=EFFORT,
        on_batch=on_batch,
    )


def test_read_document_batches(monkeypatch, tmp_path):
    calls = []
    on_batch_calls = []

    def chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        calls.append((messages, model, api_key, reasoning_effort, timeout_s, url))
        return _headed(messages, f"reply {len(calls)}")

    settings = make_settings(tmp_path)
    sources = [tmp_path / "lecture1.pdf"]
    reading = _run_read_document(
        monkeypatch,
        settings,
        chat,
        fake_render(KIND, sources, tmp_path),
        sources,
        on_batch=lambda: on_batch_calls.append(1),
    )

    assert len(calls) == 2
    first_messages, second_messages = calls[0][0], calls[1][0]
    assert len(first_messages[0]["content"]) == 1 + BATCH_PAGES
    assert len(second_messages[0]["content"]) == 1 + 2
    for messages, model, api_key, reasoning_effort, timeout_s, url in calls:
        assert model == MODEL
        assert api_key == "gem"
        assert reasoning_effort == EFFORT
        assert timeout_s == 120.0
        assert url is None
    assert "ECE 108" in first_messages[0]["content"][0]["text"]
    assert "pages 1-8" in first_messages[0]["content"][0]["text"]
    assert "pages 9-10" in second_messages[0]["content"][0]["text"]
    assert len(on_batch_calls) == 2
    expected = settings.state_dir / READS_DIR / f"{KEY}.md"
    assert reading == expected
    content = reading.read_text()
    assert content.startswith("---")
    assert "course: ECE 108" in content
    assert "pages: 10" in content
    assert "model: gemini-3.5-flash" in content
    assert "ECE 108/lecture1.pdf" in content
    assert "reply 1" in content
    assert "reply 2" in content
    assert content.index("reply 1") < content.index("reply 2")
    assert _page_numbers(content) == list(range(1, 11))
    assert not (settings.state_dir / READS_DIR / f"{KEY}.partial.json").exists()


def test_read_pages_encodes_images(monkeypatch, tmp_path):
    calls = []

    def chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        calls.append((messages, model, api_key, reasoning_effort, timeout_s, url))
        return "fake reply"

    monkeypatch.setattr(lecture_docs, "chat", chat)
    settings = make_settings(tmp_path)
    result = lecture_docs.read_pages(
        settings,
        "prompt",
        [("image/png", b"x"), ("image/jpeg", b"y")],
        model=MODEL,
        effort=EFFORT,
    )
    assert result == "fake reply"
    assert len(calls) == 1
    messages, model, api_key, reasoning_effort, timeout_s, url = calls[0]
    assert model == MODEL
    assert api_key == "gem"
    assert reasoning_effort == EFFORT
    assert timeout_s == 120.0
    assert url is None
    content = messages[0]["content"]
    assert messages[0]["role"] == "user"
    assert content[0] == {"type": "text", "text": "prompt"}
    assert content[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(b"x").decode()
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert len(content) == 3


def test_cap_fallback(monkeypatch, tmp_path):
    recorded = []

    def chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        if url is None:
            raise GeminiCapError("cap")
        recorded.append((model, api_key, url))
        return "### Page 1"

    settings = make_settings(tmp_path)
    sources = [tmp_path / "lecture1.pdf"]
    reading = _run_read_document(
        monkeypatch,
        settings,
        chat,
        [("image/png", b"page")],
        sources,
    )
    assert recorded == [("google/gemini-3.5-flash", "or", OPENROUTER_CHAT_URL)]
    assert reading.exists()


def test_resume_from_legacy_checkpoint(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    checkpoint_dir = settings.state_dir / READS_DIR
    checkpoint_dir.mkdir(parents=True)
    checkpoint = checkpoint_dir / f"{KEY}.partial.json"
    checkpoint.write_text(
        json.dumps(
            {
                "classified": True,
                "batches": {"1": "### Page 1 cached"},
                "batch_pages": BATCH_PAGES,
            }
        )
    )

    calls = []
    on_batch_calls = []

    def chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        calls.append(messages)
        return _headed(messages, "fresh")

    pages = [("image/png", f"p{i}".encode()) for i in range(10)]
    sources = [tmp_path / "lecture1.pdf"]
    reading = _run_read_document(
        monkeypatch,
        settings,
        chat,
        pages,
        sources,
        on_batch=lambda: on_batch_calls.append(1),
    )

    assert len(calls) == 1
    assert len(on_batch_calls) == 1
    content = reading.read_text()
    assert "### Page 1 cached" in content
    assert "fresh" in content
    assert content.index("### Page 1 cached") < content.index("fresh")
    assert "### Page 9\nfresh" in content
    assert "### Page 10\nfresh" in content
    assert not checkpoint.exists()


def test_checkpoint_batch_size_mismatch_discarded(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    checkpoint_dir = settings.state_dir / READS_DIR
    checkpoint_dir.mkdir(parents=True)
    checkpoint = checkpoint_dir / f"{KEY}.partial.json"
    checkpoint.write_text(
        json.dumps({"batches": {"1": "stale"}, "batch_pages": BATCH_PAGES + 1})
    )

    calls = []

    def chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        calls.append(messages)
        return _headed(messages, f"reply {len(calls)}")

    sources = [tmp_path / "lecture1.pdf"]
    reading = _run_read_document(
        monkeypatch,
        settings,
        chat,
        fake_render(KIND, sources, tmp_path),
        sources,
    )

    assert len(calls) == 2
    content = reading.read_text()
    assert "stale" not in content
    assert "reply 1" in content
    assert "reply 2" in content


def test_model_error_keeps_finished_batches(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    calls = []

    def chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        calls.append(messages)
        if len(calls) == 1:
            return _headed(messages, "first")
        raise GeminiError("boom")

    sources = [tmp_path / "lecture1.pdf"]
    with pytest.raises(GeminiError):
        _run_read_document(
            monkeypatch,
            settings,
            chat,
            fake_render(KIND, sources, tmp_path),
            sources,
        )

    checkpoint = settings.state_dir / READS_DIR / f"{KEY}.partial.json"
    assert checkpoint.exists()
    data = json.loads(checkpoint.read_text())
    assert list(data["batches"]) == ["1"]
    assert _page_numbers(data["batches"]["1"]) == list(range(1, 9))
    assert not (settings.state_dir / READS_DIR / f"{KEY}.md").exists()


def test_too_many_pages_removes_checkpoint(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    checkpoint_dir = settings.state_dir / READS_DIR
    checkpoint_dir.mkdir(parents=True)
    checkpoint = checkpoint_dir / f"{KEY}.partial.json"
    checkpoint.write_text(json.dumps({"batches": {}, "batch_pages": BATCH_PAGES}))

    def render(kind, sources, workdir, page_range=None):
        raise TooManyPages("200 pages")

    def chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        return "unused"

    monkeypatch.setattr(lecture_docs, "chat", chat)
    monkeypatch.setattr(lecture_docs, "render_pages", render)
    with pytest.raises(TooManyPages):
        lecture_docs.read_document(
            settings,
            key=KEY,
            course=COURSE,
            kind=KIND,
            paths=PATHS,
            sources=[tmp_path / "lecture1.pdf"],
            model=MODEL,
            effort=EFFORT,
        )
    assert not checkpoint.exists()


def test_no_pages_raises(monkeypatch, tmp_path):
    settings = make_settings(tmp_path)
    called = []

    def chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        called.append(messages)
        return "unused"

    sources = [tmp_path / "lecture1.pdf"]
    with pytest.raises(ValueError):
        _run_read_document(monkeypatch, settings, chat, [], sources)
    assert not called


def test_render_pages_rejects_bad_kind(tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    with pytest.raises(ValueError):
        lecture_docs.render_pages("doc", [a, b], tmp_path)
    with pytest.raises(ValueError):
        lecture_docs.render_pages("video", [a], tmp_path)


def test_render_pages_photos_rejects_page_range(tmp_path):
    with pytest.raises(ValueError):
        lecture_docs.render_pages("photos", [tmp_path / "a.jpg"], tmp_path, page_range=(1, 2))


def test_render_pdf_range_passes_first_last_and_sorts(tmp_path, monkeypatch):
    monkeypatch.setattr(lecture_docs, "pdf_page_count", lambda pdf: 867)
    recorded = {}

    def fake_run(args, check, capture_output, timeout):
        recorded["args"] = args
        for name, content in (
            ("page-101.png", b"101"),
            ("page-099.png", b"099"),
            ("page-100.png", b"100"),
            ("page-098.png", b"098"),
        ):
            (tmp_path / name).write_bytes(content)
        return None

    monkeypatch.setattr(lecture_docs.subprocess, "run", fake_run)
    result = lecture_docs._render_pdf(tmp_path / "book.pdf", tmp_path, page_range=(98, 101))
    assert recorded["args"][5:9] == ["-f", "98", "-l", "101"]
    assert recorded["args"][4] == "-png"
    assert result == [
        ("image/png", b"098"),
        ("image/png", b"099"),
        ("image/png", b"100"),
        ("image/png", b"101"),
    ]


@pytest.mark.parametrize(
    ("page_range", "exc"),
    [
        ((0, 5), ValueError),
        ((10, 5), ValueError),
        ((800, 868), ValueError),
        ((1, 151), TooManyPages),
    ],
)
def test_render_pdf_range_validation(tmp_path, monkeypatch, page_range, exc):
    monkeypatch.setattr(lecture_docs, "pdf_page_count", lambda pdf: 867)
    monkeypatch.setattr(
        lecture_docs.subprocess,
        "run",
        lambda args, check, capture_output, timeout: pytest.fail("subprocess.run should not be called"),
    )
    with pytest.raises(exc):
        lecture_docs._render_pdf(tmp_path / "book.pdf", tmp_path, page_range=page_range)


def test_render_pdf_range_under_cap_on_long_book(tmp_path, monkeypatch):
    monkeypatch.setattr(lecture_docs, "pdf_page_count", lambda pdf: 867)
    monkeypatch.setattr(
        lecture_docs.subprocess,
        "run",
        lambda args, check, capture_output, timeout: None,
    )
    result = lecture_docs._render_pdf(tmp_path / "book.pdf", tmp_path, page_range=(1, 150))
    assert result == []


def test_read_document_page_range_absolute_numbers(tmp_path, monkeypatch):
    recorded = {}

    def fake_render(kind, sources, workdir, page_range=None):
        recorded["page_range"] = page_range
        return [("image/png", f"p{i}".encode()) for i in range(10)]

    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)
    prompts = []

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        prompts.append(messages[0]["content"][0]["text"])
        return _headed(messages, "x")

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)
    reading = lecture_docs.read_document(
        make_settings(tmp_path),
        key=KEY,
        course=COURSE,
        kind=KIND,
        paths=PATHS,
        sources=[tmp_path / "book.pdf"],
        model=MODEL,
        effort=EFFORT,
        page_range=(101, 110),
    )
    assert recorded["page_range"] == (101, 110)
    assert len(prompts) == 2
    assert prompts[0].startswith("These are pages 101-108 ")
    assert prompts[1].startswith("These are pages 109-110 ")
    assert _page_numbers(reading.read_text()) == list(range(101, 111))


def test_read_document_page_range_checkpoint_keys_absolute(tmp_path, monkeypatch):
    def fake_render(kind, sources, workdir, page_range=None):
        return [("image/png", f"p{i}".encode()) for i in range(10)]

    monkeypatch.setattr(lecture_docs, "render_pages", fake_render)
    calls = {"count": 0}

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return _headed(messages, "x")
        raise RuntimeError("boom")

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)
    settings = make_settings(tmp_path)
    with pytest.raises(RuntimeError):
        lecture_docs.read_document(
            settings,
            key=KEY,
            course=COURSE,
            kind=KIND,
            paths=PATHS,
            sources=[tmp_path / "book.pdf"],
            model=MODEL,
            effort=EFFORT,
            page_range=(101, 110),
        )
    checkpoint = settings.state_dir / READS_DIR / f"{KEY}.partial.json"
    data = json.loads(checkpoint.read_text())
    assert list(data["batches"]) == ["101"]
    assert _page_numbers(data["batches"]["101"]) == list(range(101, 109))


def test_recitation_refusal_retries_with_textbook_prompt(tmp_path, monkeypatch):
    from libra.gemini import GeminiRecitationError

    settings = make_settings(tmp_path)
    prompts: list[str] = []

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        prompts.append(messages[0]["content"][0]["text"])
        if "of lecture material for" in prompts[-1]:
            raise GeminiRecitationError("m: no content (finish_reason content_filter: RECITATION)")
        return _headed(messages, "study notes")

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)

    result = lecture_docs.read_document(
        settings,
        key=KEY,
        course=COURSE,
        kind=KIND,
        paths=PATHS,
        sources=[tmp_path / "x.pdf"],
        model=MODEL,
        effort=EFFORT,
        pages=[("image/png", b"p0"), ("image/png", b"p1")],
    )

    assert len(prompts) == 2
    assert "of lecture material for" in prompts[0]
    assert "of a textbook used in" in prompts[1]
    assert "study notes" in result.read_text()


def test_recitation_refusal_with_textbook_prompt_propagates(tmp_path, monkeypatch):
    from libra.gemini import GeminiRecitationError

    settings = make_settings(tmp_path)
    prompts: list[str] = []

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        prompts.append(messages[0]["content"][0]["text"])
        raise GeminiRecitationError("m: no content (finish_reason content_filter: RECITATION)")

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)

    with pytest.raises(GeminiRecitationError):
        lecture_docs.read_document(
            settings,
            key=KEY,
            course=COURSE,
            kind=KIND,
            paths=PATHS,
            sources=[tmp_path / "x.pdf"],
            model=MODEL,
            effort=EFFORT,
            pages=[("image/png", b"p0"), ("image/png", b"p1")],
            prompt_template=lecture_docs.TEXTBOOK_READ_PROMPT,
        )

    assert len(prompts) == 1


def test_printed_page_numbers_relabelled_absolute(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        return "### Page 145\nalpha\n\n### Page 146\nbeta"

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)
    reading = lecture_docs.read_document(
        settings,
        key=KEY,
        course=COURSE,
        kind=KIND,
        paths=PATHS,
        sources=[tmp_path / "book.pdf"],
        model=MODEL,
        effort=EFFORT,
        pages=[("image/png", b"p0"), ("image/png", b"p1")],
        page_range=(165, 166),
    )
    content = reading.read_text()
    assert "### Page 165\nalpha" in content
    assert "### Page 166\nbeta" in content
    assert "### Page 145" not in content


def test_page_heading_count_mismatch_raises(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        return "### Page 1\na\n\n### Page 2\nb\n\n### Page 3\nc"

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)
    with pytest.raises(GeminiError, match="expected 1 for pages 1-1, got 3"):
        lecture_docs.read_document(
            settings,
            key=KEY,
            course=COURSE,
            kind=KIND,
            paths=PATHS,
            sources=[tmp_path / "book.pdf"],
            model=MODEL,
            effort=EFFORT,
            pages=[("image/png", b"p0"), ("image/png", b"p1")],
        )
    assert not (settings.state_dir / READS_DIR / f"{KEY}.partial.json").exists()
    assert not (settings.state_dir / READS_DIR / f"{KEY}.md").exists()


def test_renumber_pages_normalizes_heading_variants():
    reply = "## Page 5:\nalpha\n\n#### page 6 - Intro\nbeta\n\n### PAGE 7\ngamma"
    expected = "### Page 1\nalpha\n\n### Page 2\nIntro\nbeta\n\n### Page 3\ngamma"
    assert lecture_docs._renumber_pages(reply, first=1, last=3) == expected


def test_renumber_pages_ignores_non_headings():
    reply = "### Page 9\n### Pages 3\n##### Page 2\n# Page 1\nPage 4"
    expected = "### Page 4\n### Pages 3\n##### Page 2\n# Page 1\nPage 4"
    assert lecture_docs._renumber_pages(reply, first=4, last=4) == expected


def test_page_heading_mismatch_retries_batch_once(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    calls = 0

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "### Page 1\nonly one"
        return _headed(messages, "fixed")

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)
    reading = lecture_docs.read_document(
        settings,
        key=KEY,
        course=COURSE,
        kind=KIND,
        paths=PATHS,
        sources=[tmp_path / "book.pdf"],
        model=MODEL,
        effort=EFFORT,
        pages=[("image/png", b"p0"), ("image/png", b"p1")],
    )
    assert calls == 2
    text = reading.read_text()
    assert _page_numbers(text) == [1, 2]
    assert "fixed" in text
    assert "only one" not in text
    assert not (settings.state_dir / READS_DIR / f"{KEY}.partial.json").exists()


def test_page_heading_mismatch_raises_when_single_page_fails(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    calls = 0

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        nonlocal calls
        calls += 1
        return "### Page 1\na\n\n### Page 2\nb\n\n### Page 3\nc"

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)
    with pytest.raises(lecture_docs.PageHeadingError):
        lecture_docs.read_document(
            settings,
            key=KEY,
            course=COURSE,
            kind=KIND,
            paths=PATHS,
            sources=[tmp_path / "book.pdf"],
            model=MODEL,
            effort=EFFORT,
            pages=[("image/png", b"p0"), ("image/png", b"p1")],
        )
    assert calls == 3


def test_page_heading_mismatch_falls_back_to_single_pages(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    calls = 0

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return "### Page 1\nonly one"
        url = messages[0]["content"][1]["image_url"]["url"]
        image = base64.b64decode(url.split(",", 1)[1])
        if image == b"p0":
            return "alpha"
        return "## page 9\nbeta"

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)
    reading = lecture_docs.read_document(
        settings,
        key=KEY,
        course=COURSE,
        kind=KIND,
        paths=PATHS,
        sources=[tmp_path / "book.pdf"],
        model=MODEL,
        effort=EFFORT,
        pages=[("image/png", b"p0"), ("image/png", b"p1")],
        page_range=(165, 166),
    )
    text = reading.read_text()
    assert calls == 4
    assert _page_numbers(text) == [165, 166]
    assert "### Page 165\nalpha" in text
    assert "### Page 166\nbeta" in text
    assert "only one" not in text
    assert not (settings.state_dir / READS_DIR / f"{KEY}.partial.json").exists()


def test_reading_key_tracks_reader(monkeypatch):
    base = dict(
        model="m1",
        effort="low",
        prompt_template=lecture_docs.READ_PROMPT,
    )
    key = lecture_docs.reading_key("r" * 64, **base)
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    assert lecture_docs.reading_key("r" * 64, **base) == key

    variants = [
        dict(model="m2"),
        dict(effort="medium"),
        dict(prompt_template=lecture_docs.TEXTBOOK_READ_PROMPT),
    ]
    for variant in variants:
        assert lecture_docs.reading_key("r" * 64, **{**base, **variant}) != key
    assert lecture_docs.reading_key("s" * 64, **base) != key

    monkeypatch.setattr(lecture_docs, "READER_VERSION", lecture_docs.READER_VERSION + 1)
    assert lecture_docs.reading_key("r" * 64, **base) != key


def test_read_document_rejects_page_count_mismatch(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    calls = []

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        calls.append(messages)
        return _headed(messages, "x")

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)
    with pytest.raises(ValueError, match="2") as excinfo:
        lecture_docs.read_document(
            settings,
            key=KEY,
            course=COURSE,
            kind=KIND,
            paths=PATHS,
            sources=[tmp_path / "book.pdf"],
            model=MODEL,
            effort=EFFORT,
            pages=[("image/png", b"p0"), ("image/png", b"p1")],
            page_range=(5, 7),
        )
    assert "3" in str(excinfo.value)
    assert calls == []
    assert not (settings.state_dir / READS_DIR / f"{KEY}.partial.json").exists()


def test_read_document_accepts_matching_page_count(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    calls = []

    def fake_chat(messages, model, *, api_key, reasoning_effort, timeout_s, url=None):
        calls.append(messages)
        return _headed(messages, "x")

    monkeypatch.setattr(lecture_docs, "chat", fake_chat)
    reading = lecture_docs.read_document(
        settings,
        key=KEY,
        course=COURSE,
        kind=KIND,
        paths=PATHS,
        sources=[tmp_path / "book.pdf"],
        model=MODEL,
        effort=EFFORT,
        pages=[("image/png", b"p0"), ("image/png", b"p1"), ("image/png", b"p2")],
        page_range=(5, 7),
    )
    assert len(calls) == 1
    assert _page_numbers(reading.read_text()) == [5, 6, 7]
