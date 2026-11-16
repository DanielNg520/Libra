from __future__ import annotations

from datetime import date
from pathlib import PurePosixPath

import pytest

from libra.study.week import (
    DoneEntry,
    StaleItemError,
    carry_over,
    close_week,
    item_id,
    open_week,
    parse_done,
    parse_week,
    tick,
    week_monday,
    week_relpath,
)

WEEK = """---
tags:
  - weekly
week: 2026-11-09
stage: 2
---

## Mon 2026-11-09
- [ ] PR: [[Self study/Probability/03 Bayes rule|Bayes rule]]
- [x] C: `Coding Practice/Bare Metal C/day3.c`
- [ ] ZZ: bad category
Owner note.
## Tue 2026-11-10
- [ ] EXTRA: read chapter 2
## Wed 2026-11-11

## Thu 2026-11-12

## Fri 2026-11-13

## Sat 2026-11-14

## Sun 2026-11-15
- [ ] LA: [[Self study/Linear algebra/04 Rank]]
- [x] OP: [[Self study/Optimization/02 Convexity|Convexity]] (carried from Sat)
## Notes
- [ ] PR: not an item
"""


def test_parse_week_frontmatter_days_items_skipped() -> None:
    week = parse_week(WEEK, "k")
    assert week.frontmatter == {"tags": ["weekly"], "week": "2026-11-09", "stage": 2}
    assert week.days == (
        date(2026, 11, 9),
        date(2026, 11, 10),
        date(2026, 11, 11),
        date(2026, 11, 12),
        date(2026, 11, 13),
        date(2026, 11, 14),
        date(2026, 11, 15),
    )
    assert len(week.items) == 5
    zz_line = WEEK.split("\n").index("- [ ] ZZ: bad category")
    assert week.skipped == (zz_line,)


def test_parse_week_targets_done_carried() -> None:
    items = list(parse_week(WEEK, "k").items)
    pr = items[0]
    assert pr.label == "Bayes rule"
    assert pr.path == "Self study/Probability/03 Bayes rule.md"
    assert pr.code is None
    assert pr.done is False
    assert pr.carried_from is None

    code = items[1]
    assert code.label == "day3.c"
    assert code.code == "Coding Practice/Bare Metal C/day3.c"
    assert code.path is None
    assert code.done is True

    extra = items[2]
    assert extra.label == "read chapter 2"
    assert extra.path is None
    assert extra.code is None

    la = items[3]
    assert la.label == "04 Rank"
    assert la.path == "Self study/Linear algebra/04 Rank.md"

    op = items[4]
    assert op.label == "Convexity"
    assert op.done is True
    assert op.carried_from == "Sat"


def test_parse_week_ignores_notes_section() -> None:
    week = parse_week(WEEK, "k")
    assert all(item.label != "not an item" for item in week.items)


def test_parse_week_rejects_mismatched_heading() -> None:
    text = """---

## Tue 2026-11-09
- [ ] PR: some item
"""
    week = parse_week(text, "k")
    assert week.days == ()
    assert week.items == ()


def test_parse_week_without_frontmatter() -> None:
    text = """## Mon 2026-11-09
- [ ] PR: some item
"""
    week = parse_week(text, "k")
    assert week.frontmatter == {}
    assert len(week.items) == 1


def test_item_id_stability_and_parse_match() -> None:
    line = "- [ ] PR: some item"
    assert item_id("key", line) == item_id("key", line)
    assert len(item_id("key", line)) == 12
    assert all(c in "0123456789abcdef" for c in item_id("key", line))
    assert item_id("key", line) != item_id("other", line)

    week = parse_week(WEEK, "k")
    for item in week.items:
        assert item.id == item_id("k", item.line)


def test_tick_sets_and_unsets_checkbox() -> None:
    lines = WEEK.split("\n")
    pr_line = lines.index("- [ ] PR: [[Self study/Probability/03 Bayes rule|Bayes rule]]")
    pr_id = item_id("k", WEEK.split("\n")[pr_line])

    ticked = tick(WEEK, "k", pr_id, True)
    ticked_lines = ticked.split("\n")
    assert ticked_lines[pr_line].startswith("- [x] PR:")
    for i, line in enumerate(WEEK.split("\n")):
        if i != pr_line:
            assert ticked_lines[i] == line
    assert ticked.endswith("\n")

    unticked = tick(ticked, "k", item_id("k", ticked_lines[pr_line]), False)
    unticked_lines = unticked.split("\n")
    assert unticked_lines[pr_line].startswith("- [ ] PR:")
    for i, line in enumerate(WEEK.split("\n")):
        if i != pr_line:
            assert unticked_lines[i] == line

    reticked = tick(ticked, "k", item_id("k", ticked_lines[pr_line]), True)
    assert reticked == ticked


def test_tick_unknown_id_raises_stale() -> None:
    with pytest.raises(StaleItemError):
        tick(WEEK, "k", "unknownid00", True)


def test_tick_changed_line_raises_stale() -> None:
    lines = WEEK.split("\n")
    pr_line = lines.index("- [ ] PR: [[Self study/Probability/03 Bayes rule|Bayes rule]]")
    pr_id = item_id("k", lines[pr_line])

    modified = lines.copy()
    modified[pr_line] = "- [ ] PR: modified line"
    new_text = "\n".join(modified)
    with pytest.raises(StaleItemError):
        tick(new_text, "k", pr_id, True)


def test_tick_skipped_line_raises_stale() -> None:
    zz_line = WEEK.split("\n").index("- [ ] ZZ: bad category")
    zz_id = item_id("k", WEEK.split("\n")[zz_line])
    with pytest.raises(StaleItemError):
        tick(WEEK, "k", zz_id, True)


def test_carry_over_moves_unticked_items() -> None:
    out = carry_over(WEEK, date(2026, 11, 10))
    lines = out.split("\n")
    mon_idx = lines.index("## Mon 2026-11-09")
    tue_idx = lines.index("## Tue 2026-11-10")
    assert "- [ ] PR: [[Self study/Probability/03 Bayes rule|Bayes rule]]" not in lines[mon_idx + 1 : tue_idx]
    assert "- [ ] PR: [[Self study/Probability/03 Bayes rule|Bayes rule]] (carried from Mon)" == lines[tue_idx + 1]
    assert "- [ ] EXTRA: read chapter 2" in lines[tue_idx + 2 : tue_idx + 5]
    assert "- [x] C: `Coding Practice/Bare Metal C/day3.c`" in lines[mon_idx + 1 : tue_idx]
    assert "- [ ] ZZ: bad category" in lines[mon_idx + 1 : tue_idx]
    assert carry_over(out, date(2026, 11, 10)) == out


def test_carry_over_keeps_existing_suffix() -> None:
    small = """## Mon 2026-11-09
- [ ] LA: [[Self study/Linear algebra/04 Rank]] (carried from Sat)
## Tue 2026-11-10
- [ ] EXTRA: read
"""
    out = carry_over(small, date(2026, 11, 10))
    lines = out.split("\n")
    tue_idx = lines.index("## Tue 2026-11-10")
    assert lines[tue_idx + 1] == "- [ ] LA: [[Self study/Linear algebra/04 Rank]] (carried from Sat)"


def test_carry_over_same_day_unchanged() -> None:
    assert carry_over(WEEK, date(2026, 11, 9)) == WEEK


def test_close_week_moves_unticked_sunday_items() -> None:
    out, carried = close_week(WEEK)
    assert carried == ["- [ ] LA: [[Self study/Linear algebra/04 Rank]] (carried from Sun)"]
    assert "- [ ] LA: [[Self study/Linear algebra/04 Rank]]" not in out.split("## Sun 2026-11-15")[1]
    assert "## Done this week" in out
    done_section = out.split("## Done this week")[1].split("## Mon 2026-11-09")[0]
    assert "- C: `Coding Practice/Bare Metal C/day3.c`" in done_section
    assert "- OP: [[Self study/Optimization/02 Convexity|Convexity]]" in done_section
    assert "not an item" not in done_section
    assert done_section.index("- C: `Coding Practice/Bare Metal C/day3.c`") < done_section.index(
        "- OP: [[Self study/Optimization/02 Convexity|Convexity]]"
    )
    result_week = parse_week(out, "k")
    assert len(result_week.items) == 4


def test_close_week_idempotent() -> None:
    out, _ = close_week(WEEK)
    out2, carried2 = close_week(out)
    assert out2 == out
    assert carried2 == []


def test_close_week_replaces_existing_done_section() -> None:
    text = """## Done this week
- stale item

## Mon 2026-11-09
- [x] C: `a.c`
"""
    out, _ = close_week(text)
    assert out.count("## Done this week") == 1
    assert "- stale item" not in out


def test_open_week_none_creates_new_week() -> None:
    carried = ["- [ ] LA: [[Self study/Linear algebra/04 Rank]] (carried from Sun)"]
    text = open_week(None, date(2026, 11, 16), carried, stage=2)
    week = parse_week(text, "k")
    assert week.frontmatter["week"] == "2026-11-16"
    assert week.frontmatter["stage"] == 2
    assert week.days == (
        date(2026, 11, 16),
        date(2026, 11, 17),
        date(2026, 11, 18),
        date(2026, 11, 19),
        date(2026, 11, 20),
        date(2026, 11, 21),
        date(2026, 11, 22),
    )
    assert week.items[0].day == date(2026, 11, 16)
    assert week.items[0].carried_from == "Sun"

    new_week = parse_week(open_week(None, date(2026, 11, 16), [], stage=None), "k")
    assert "stage" not in new_week.frontmatter


def test_open_week_existing_inserts_after_monday() -> None:
    text = open_week(None, date(2026, 11, 16), [], stage=2)
    carried = ["- [ ] PR: new item"]
    out = open_week(text, date(2026, 11, 16), carried)
    lines = out.split("\n")
    mon_idx = lines.index("## Mon 2026-11-16")
    assert lines[mon_idx + 1] == "- [ ] PR: new item"
    assert open_week(out, date(2026, 11, 16), carried) == out


def test_open_week_empty_carried_unchanged() -> None:
    text = open_week(None, date(2026, 11, 16), [], stage=2)
    assert open_week(text, date(2026, 11, 16), []) == text


def test_open_week_non_monday_raises() -> None:
    with pytest.raises(ValueError):
        open_week(None, date(2026, 11, 15), [])


def test_open_week_missing_monday_heading_raises() -> None:
    text = "## Tue 2026-11-17\n"
    with pytest.raises(ValueError):
        open_week(text, date(2026, 11, 16), ["- [ ] PR: item"])


def test_parse_done_reads_index() -> None:
    text = "\n".join(
        [
            "---",
            "title: test",
            "---",
            "",
            "## Done this week",
            "- PR: [[Self study/P/02 x|PR 02]]",
            "- C: `lab/main.c`",
            "- ZZ: [[bad]]",
            "not an entry",
            "",
            "## Mon 2026-11-09",
            "- [x] LA: after heading",
        ]
    )
    assert parse_done(text) == (
        DoneEntry("PR", "PR 02", "Self study/P/02 x.md", None),
        DoneEntry("C", "main.c", None, "lab/main.c"),
    )


def test_parse_done_without_heading_is_empty() -> None:
    assert parse_done("## Mon 2026-11-09\n- [x] PR: x\n") == ()


def test_parse_done_round_trips_close_week() -> None:
    closed, _ = close_week(WEEK)
    assert [e.cat for e in parse_done(closed)] == [
        i.cat for i in parse_week(WEEK, "k").items if i.done
    ]


def test_week_monday_and_relpath() -> None:
    assert week_monday(date(2026, 11, 15)) == date(2026, 11, 9)
    assert week_relpath(date(2027, 1, 1)) == PurePosixPath("Self study/Weekly/2026/2026-12-28.md")


def test_parse_week_dsa_line() -> None:
    text = "## Mon 2026-11-09\n- [ ] DSA: [[Coding Practice/DSA/Arrays and hashing|LC 1 Two Sum]]\n"
    week = parse_week(text, "k")
    assert week.items[0].cat == "DSA"
    assert week.items[0].label == "LC 1 Two Sum"
    assert week.items[0].path == "Coding Practice/DSA/Arrays and hashing.md"
    assert week.items[0].code is None
    assert week.items[0].done is False
    assert week.skipped == ()
    assert "- [x] DSA: [[Coding Practice/DSA/Arrays and hashing|LC 1 Two Sum]]" in tick(text, "k", week.items[0].id, True)


def test_parse_done_dsa_line() -> None:
    text = "## Done this week\n- DSA: [[Coding Practice/DSA/Arrays and hashing|LC 1 Two Sum]]\n"
    assert parse_done(text) == (DoneEntry("DSA", "LC 1 Two Sum", "Coding Practice/DSA/Arrays and hashing.md", None),)
