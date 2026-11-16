"""Unit tests for libra.study.render."""

from __future__ import annotations

import logging

import pytest

from libra.study.check_facts import DEFAULT_MARKERS
from libra.study.render import HIDDEN_MARKERS, scan_blocks, split_frontmatter


def test_scan_tilde_and_long_fences() -> None:
    scan = scan_blocks(
        (
            "a",
            "~~~python",
            "x = 1",
            "~~~",
            "````md",
            "```",
            "inner",
            "```",
            "````",
            "b",
        )
    )

    assert scan.code == (False, True, True, True, True, True, True, True, True, False)

    assert len(scan.fences) == 2

    first = scan.fences[0]
    assert first.info == "python"
    assert first.content == "x = 1\n"
    assert first.closed

    second = scan.fences[1]
    assert second.start == 4
    assert second.end == 9
    assert second.content == "```\ninner\n```\n"


def test_scan_indented_code_is_code() -> None:
    scan = scan_blocks(("text", "", "    ![[Hidden]]", "", "after"))

    assert scan.code[2]
    assert not scan.code[0]
    assert scan.embeds == ()
    assert scan.fences == ()


def test_scan_quoted_fence() -> None:
    scan = scan_blocks(("> [!note] Title", "> ```python", "> print(1)", "> ```"))

    assert len(scan.fences) == 1
    fence = scan.fences[0]
    assert fence.quoted
    assert fence.closed
    assert fence.start == 1
    assert fence.content == "print(1)\n"


def test_scan_unclosed_fence() -> None:
    scan = scan_blocks(("a", "```py", "x", "y"))

    assert len(scan.fences) == 1
    assert not scan.fences[0].closed
    assert scan.code == (False, True, True, True)


def test_scan_embeds_any_container() -> None:
    scan = scan_blocks(
        (
            "![[Top]]",
            "",
            "- ![[In list|Listed]]",
            "",
            "> ![[Quoted.md#Part|7]]",
            "",
            "See ![[Inline]] here",
            "",
            "![[fig.png]]",
        )
    )

    assert [(e.line, e.target, e.label) for e in scan.embeds] == [
        (0, "Top", "Top"),
        (2, "In list", "Listed"),
        (4, "Quoted.md", "Quoted"),
    ]


def test_scan_cached_and_empty() -> None:
    scan = scan_blocks(())

    assert scan.code == ()
    assert scan.fences == ()
    assert scan.embeds == ()

    assert scan_blocks(("a",)) is scan_blocks(("a",))





def test_split_frontmatter_no_header() -> None:
    assert split_frontmatter("no header") == ({}, "no header")


def test_split_frontmatter_malformed(caplog: pytest.LogCaptureFixture) -> None:
    text = "---\nbad line\n---\nbody"
    with caplog.at_level(logging.WARNING, logger="libra.study.render"):
        result = split_frontmatter(text)
    assert result == ({}, text)
    assert any(record.levelno == logging.WARNING and record.name == "libra.study.render" for record in caplog.records)





def test_hidden_markers_subset_of_checker() -> None:
    for marker in HIDDEN_MARKERS:
        assert marker in DEFAULT_MARKERS
    assert "Proof:" not in HIDDEN_MARKERS
    assert "Why:" not in HIDDEN_MARKERS

