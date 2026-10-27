"""Tests for libra.source_pages (ADR-0039 S4)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from libra.config import Settings
from libra.source_pages import MAX_FETCH_PAGES, cached_pages, missing_entries, page_sections
from libra.sources import DOC_EFFORT, INDEX_NAME, SourceFile
from libra.lecture_docs import READ_PROMPT, READS_DIR, TEXTBOOK_READ_PROMPT, reading_key
from test_sources import _write, make_settings

REL = "ECE 108/deck.pdf"
SOURCE = SourceFile("ECE 108/deck.pdf", "doc", 100, 200)


def _index(settings: Settings, files: dict[str, list]) -> None:
    path = settings.state_dir / READS_DIR / INDEX_NAME
    _write(path, json.dumps({"version": 1, "files": files}))


def _reading(settings: Settings, render_key: str, prompt: str, body: str) -> None:
    key = reading_key(
        render_key,
        model=settings.ocr_model,
        effort=DOC_EFFORT,
        prompt_template=prompt,
    )
    _write(settings.state_dir / READS_DIR / f"{key}.md", body)


def test_page_sections_returns_only_page_marked_text():
    text = "---\ncourse: ECE 253\nkind: doc\n---\n\n### Page 1\n\ncontent one\n### Page 3\n\ncontent three"
    sections = page_sections(text)
    assert sections == {1: "content one", 3: "content three"}
    assert page_sections("no pages here\njust text") == {}


def test_cached_pages_whole_file(tmp_path):
    settings = make_settings(tmp_path)
    _index(settings, {REL: [100, 200, "sha", "rk-whole"]})
    _reading(
        settings,
        "rk-whole",
        READ_PROMPT,
        "---\ncourse: X\n---\n\n### Page 1\nalpha\n\n### Page 2\nbeta\n",
    )

    result = cached_pages(settings, SOURCE)

    assert result == {1: "alpha", 2: "beta"}


def test_cached_pages_merge_whole_and_range(tmp_path):
    settings = make_settings(tmp_path)
    _index(
        settings,
        {
            REL: [100, 200, "sha", "rk-whole"],
            f"{REL}#pages=2-3": [100, 200, "sha", "rk-range"],
        },
    )
    _reading(
        settings,
        "rk-whole",
        READ_PROMPT,
        "---\ncourse: X\n---\n\n### Page 1\nalpha\n\n### Page 2\nbeta\n",
    )
    _reading(
        settings,
        "rk-range",
        TEXTBOOK_READ_PROMPT,
        "---\ncourse: X\n---\n\n### Page 2\nrange-two\n\n### Page 3\ngamma\n",
    )

    result = cached_pages(settings, SOURCE)

    assert result == {1: "alpha", 2: "beta", 3: "gamma"}


def test_cached_pages_overlapping_ranges_lowest_first(tmp_path):
    settings = make_settings(tmp_path)
    _index(
        settings,
        {
            f"{REL}#pages=5-6": [100, 200, "sha", "rk-high"],
            f"{REL}#pages=3-5": [100, 200, "sha", "rk-low"],
        },
    )
    _reading(
        settings,
        "rk-high",
        TEXTBOOK_READ_PROMPT,
        "---\ncourse: X\n---\n\n### Page 5\nhigh-five\n\n### Page 6\nhigh-six\n",
    )
    _reading(
        settings,
        "rk-low",
        TEXTBOOK_READ_PROMPT,
        "---\ncourse: X\n---\n\n### Page 3\nlow-three\n\n### Page 4\nlow-four\n\n### Page 5\nlow-five\n",
    )

    result = cached_pages(settings, SOURCE)

    assert result[5] == "low-five"


@pytest.mark.parametrize(
    ("entry", "render_key"),
    [
        ([99, 200, "sha", "rk"], "rk"),
        ([100, 199, "sha", "rk"], "rk"),
        ([100, 200, "sha", ""], ""),
    ],
    ids=["size", "mtime", "no_render_key"],
)
def test_cached_pages_skips_stale_or_unkeyed(tmp_path: Path, entry: list, render_key: str) -> None:
    settings = make_settings(tmp_path)
    _index(settings, {f"{REL}#pages=1-1": entry})
    _reading(settings, render_key, TEXTBOOK_READ_PROMPT, "---\ncourse: X\n---\n\n### Page 1\nstale\n")

    result = cached_pages(settings, SOURCE)

    assert result == {}


def test_cached_pages_range_wrong_recipe_not_found(tmp_path):
    settings = make_settings(tmp_path)
    _index(settings, {f"{REL}#pages=1-1": [100, 200, "sha", "rk-wrong"]})
    _reading(
        settings,
        "rk-wrong",
        READ_PROMPT,
        "---\ncourse: X\n---\n\n### Page 1\nstored-under-read\n",
    )

    result = cached_pages(settings, SOURCE)

    assert result == {}


def test_cached_pages_ignores_other_rel_malformed_missing_file(tmp_path):
    settings = make_settings(tmp_path)
    _index(
        settings,
        {
            "other/deck.pdf": [100, 200, "sha", "rk-other"],
            f"{REL}#pages=9-2": [100, 200, "sha", "rk-malformed"],
            f"{REL}#pages=1-1": [100, 200, "sha", "rk-missing-file"],
        },
    )
    _reading(
        settings,
        "rk-other",
        READ_PROMPT,
        "---\ncourse: X\n---\n\n### Page 1\nother\n",
    )

    result = cached_pages(settings, SOURCE)

    assert result == {}


def test_cached_pages_no_index(tmp_path):
    settings = make_settings(tmp_path)

    result = cached_pages(settings, SOURCE)

    assert result == {}


def test_missing_entries():
    assert missing_entries("r.pdf", [3, 1, 2, 2], 3) == ["r.pdf"]
    assert missing_entries("r.pdf", [], 10) == []
    assert missing_entries("r.pdf", [1], 0) == ["r.pdf#pages=1-1"]
    assert missing_entries("r.pdf", [1, 2, 4, 7, 8], 10) == [
        "r.pdf#pages=1-2",
        "r.pdf#pages=4-4",
        "r.pdf#pages=7-8",
    ]


def test_max_fetch_pages():
    assert MAX_FETCH_PAGES == 25
