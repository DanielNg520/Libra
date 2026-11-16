"""Tests for libra.study.plan (Self study plan files, owner 2026-11-16)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from libra.study.plan import CURRENT, MASTER_INDEX, Item, parse_items, plan_items

PLAN_DIR = Path("Self study")


def _write_plan(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / PLAN_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestParseItems:
    def test_unticked_item(self) -> None:
        items = parse_items("- [ ] PR: something\n")
        assert len(items) == 1
        item = items[0]
        assert isinstance(item, Item)
        assert (item.cat, item.label, item.path, item.code, item.done) == (
            "PR",
            "something",
            None,
            None,
            False,
        )
        assert item.line == "- [ ] PR: something"

    @pytest.mark.parametrize("tick", ["x", "X"])
    def test_ticked_item(self, tick: str) -> None:
        items = parse_items(f"- [{tick}] PR: something\n")
        assert len(items) == 1
        assert items[0].done is True

    def test_wikilink_with_alias(self) -> None:
        items = parse_items("- [ ] LA: [[path/to/file|Nice Name]]\n")
        assert len(items) == 1
        item = items[0]
        assert item.label == "Nice Name"
        assert item.path == "path/to/file.md"
        assert item.code is None

    def test_wikilink_without_alias(self) -> None:
        items = parse_items("- [ ] DSP: [[path/to/My Course]]\n")
        assert len(items) == 1
        item = items[0]
        assert item.label == "My Course"
        assert item.path == "path/to/My Course.md"
        assert item.code is None

    def test_backtick_code_target(self) -> None:
        items = parse_items("- [ ] PY: `src/libra/core.py`\n")
        assert len(items) == 1
        item = items[0]
        assert item.label == "core.py"
        assert item.path is None
        assert item.code == "src/libra/core.py"

    def test_plain_extra_text(self) -> None:
        items = parse_items("- [ ] EXTRA: just some words here\n")
        assert len(items) == 1
        item = items[0]
        assert item.label == "just some words here"
        assert item.path is None
        assert item.code is None

    def test_unknown_category_ignored(self) -> None:
        items = parse_items("- [ ] ZZ: not a category\n")
        assert items == ()

    def test_malformed_checkbox_ignored(self) -> None:
        items = parse_items("- [y] PR: bad tick\n")
        assert items == ()

    def test_prose_headings_frontmatter_ignored(self) -> None:
        text = "\n".join(
            [
                "---",
                "title: My Plan",
                "---",
                "# Heading",
                "Some prose line",
                "- [ ] PR: real item",
                "",
            ]
        )
        items = parse_items(text)
        assert len(items) == 1
        assert items[0].line == "- [ ] PR: real item"


class TestPlanItems:
    def test_current_before_master(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, CURRENT.name, "- [ ] PR: current item\n")
        _write_plan(tmp_path, MASTER_INDEX.name, "- [ ] PR: master item\n")
        items = plan_items(tmp_path)
        assert [item.label for item in items] == ["current item", "master item"]

    def test_missing_files_give_empty_tuple(self, tmp_path: Path) -> None:
        assert plan_items(tmp_path) == ()

    def test_unreadable_file_skipped_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write_plan(tmp_path, MASTER_INDEX.name, "- [ ] PR: master item\n")
        bad_path = tmp_path / PLAN_DIR / CURRENT.name
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_bytes(b"\xff\xfe invalid utf-8")

        with caplog.at_level(logging.WARNING):
            items = plan_items(tmp_path)

        assert [item.label for item in items] == ["master item"]
        assert any(str(CURRENT) in record.message for record in caplog.records)
        assert len(caplog.records) == 1
