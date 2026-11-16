"""Parser and editor for weekly study plan files (ADR-0043)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePosixPath

from libra.study.frontmatter import FrontmatterError, dump, load

__all__ = [
    "CATEGORIES",
    "DAY_ABBRS",
    "DONE_HEADING",
    "Item",
    "DoneEntry",
    "Week",
    "StaleItemError",
    "week_monday",
    "week_relpath",
    "item_id",
    "parse_week",
    "parse_done",
    "tick",
    "carry_over",
    "close_week",
    "open_week",
]

CATEGORIES: tuple[str, ...] = ("PR", "LA", "OP", "DSP", "C", "PY", "DSA", "EXTRA")
DAY_ABBRS: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DONE_HEADING = "## Done this week"

_DAY_ABBR_TO_NUM = {abbr: i for i, abbr in enumerate(DAY_ABBRS)}
_HEADING_RE = re.compile(r"^## (Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{4}-\d{2}-\d{2})$")
_ITEM_RE = re.compile(r"^- \[([ xX])\] ([A-Z]+): (.+?)(?: \(carried from (Mon|Tue|Wed|Thu|Fri|Sat|Sun)\))?$")
_WIKILINK_RE = re.compile(r"^\[\[([^|\]]+?)(?:\|([^\]]+))?\]\]$")
_CODE_RE = re.compile(r"^`([^`]+)`$")
_DONE_RE = re.compile(r"^- ([A-Z]+): (.+)$")


@dataclass(frozen=True)
class Item:
    id: str
    day: date
    line_no: int
    cat: str
    label: str
    path: str | None
    code: str | None
    done: bool
    carried_from: str | None
    line: str


@dataclass(frozen=True)
class Week:
    frontmatter: dict[str, object]
    days: tuple[date, ...]
    items: tuple[Item, ...]
    skipped: tuple[int, ...]


@dataclass(frozen=True)
class DoneEntry:
    cat: str
    label: str
    path: str | None
    code: str | None


class StaleItemError(LookupError):
    """No item in the text has the given id."""


def week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_relpath(d: date) -> PurePosixPath:
    monday = week_monday(d)
    return PurePosixPath("Self study") / "Weekly" / str(monday.year) / f"{monday.isoformat()}.md"


def item_id(key: str, line: str) -> str:
    return hashlib.sha256(f"{key}\n{line}".encode()).hexdigest()[:12]


def _parse_target(raw: str) -> tuple[str, str | None, str | None]:
    m = _WIKILINK_RE.match(raw)
    if m:
        link_path = m.group(1)
        if not link_path.endswith(".md"):
            link_path += ".md"
        alias = m.group(2)
        label = alias if alias is not None else link_path.rsplit("/", 1)[-1][:-3]
        return label, link_path, None
    m = _CODE_RE.match(raw)
    if m:
        return PurePosixPath(m.group(1)).name, None, m.group(1)
    return raw, None, None


def _body_start(lines: list[str]) -> int:
    if not lines or lines[0] != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i] == "---":
            return i + 1
    return 0


def _heading_date(line: str) -> tuple[str, date] | None:
    m = _HEADING_RE.match(line)
    if not m:
        return None
    abbr = m.group(1)
    try:
        d = date.fromisoformat(m.group(2))
    except ValueError:
        return None
    if d.weekday() != _DAY_ABBR_TO_NUM[abbr]:
        return None
    return abbr, d


def _find_heading(lines: list[str], abbr: str, day: date | None = None) -> int | None:
    for i, line in enumerate(lines):
        hd = _heading_date(line)
        if hd and hd[0] == abbr:
            if day is not None and hd[1] != day:
                continue
            return i
    return None


def parse_week(text: str, key: str) -> Week:
    lines = text.split("\n")
    start = _body_start(lines)
    frontmatter: dict[str, object] = {}
    if start > 0:
        header = "\n".join(lines[:start])
        try:
            frontmatter = load(header)[0]
        except FrontmatterError:
            frontmatter = {}

    days: list[date] = []
    items: list[Item] = []
    skipped: list[int] = []
    current_day: date | None = None

    for i in range(start, len(lines)):
        line = lines[i]
        hd = _heading_date(line)
        if hd:
            current_day = hd[1]
            days.append(hd[1])
            continue
        if line.startswith("## "):
            current_day = None
            continue
        if current_day is None:
            continue
        if line.startswith("- ["):
            im = _ITEM_RE.match(line)
            if not im or im.group(2) not in CATEGORIES:
                skipped.append(i)
                continue
            done = im.group(1).lower() == "x"
            cat = im.group(2)
            raw_target = im.group(3)
            label, path, code = _parse_target(raw_target)
            carried = im.group(4)
            items.append(
                Item(
                    id=item_id(key, line),
                    day=current_day,
                    line_no=i,
                    cat=cat,
                    label=label,
                    path=path,
                    code=code,
                    done=done,
                    carried_from=carried,
                    line=line,
                )
            )

    return Week(
        frontmatter=frontmatter,
        days=tuple(days),
        items=tuple(items),
        skipped=tuple(skipped),
    )


def parse_done(text: str) -> tuple[DoneEntry, ...]:
    lines = text.splitlines()
    try:
        start = lines.index(DONE_HEADING)
    except ValueError:
        return ()
    entries: list[DoneEntry] = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        match = _DONE_RE.match(line)
        if match and match.group(1) in CATEGORIES:
            label, path, code = _parse_target(match.group(2))
            entries.append(DoneEntry(match.group(1), label, path, code))
    return tuple(entries)


def _match_item(line: str) -> re.Match[str] | None:
    im = _ITEM_RE.match(line)
    if im and im.group(2) in CATEGORIES:
        return im
    return None


def tick(text: str, key: str, target_id: str, done: bool) -> str:
    week = parse_week(text, key)
    target = next((item for item in week.items if item.id == target_id), None)
    if target is None:
        raise StaleItemError(target_id)
    lines = text.split("\n")
    line = lines[target.line_no]
    new_check = "[x]" if done else "[ ]"
    lines[target.line_no] = line[:2] + new_check + line[5:]
    return "\n".join(lines)


def _get_day_range(lines: list[str], abbr: str, day: date) -> tuple[int, int] | None:
    start = _find_heading(lines, abbr, day)
    if start is None:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return start, end


def carry_over(text: str, today: date) -> str:
    lines = text.split("\n")
    yesterday = today - timedelta(days=1)
    yd = _get_day_range(lines, DAY_ABBRS[yesterday.weekday()], yesterday)
    td = _get_day_range(lines, DAY_ABBRS[today.weekday()], today)
    if yd is None or td is None:
        return text

    y_start, y_end = yd
    carried_abbr = DAY_ABBRS[yesterday.weekday()]

    to_move: list[str] = []
    new_lines: list[str] = []
    for i in range(y_start, y_end):
        line = lines[i]
        im = _match_item(line)
        if im and im.group(1).lower() != "x":
            if im.group(4) is None:
                line += f" (carried from {carried_abbr})"
            to_move.append(line)
        else:
            new_lines.append(line)

    result = lines[:y_start] + new_lines + lines[y_end:]
    t_start = _find_heading(result, DAY_ABBRS[today.weekday()], today)
    assert t_start is not None
    result = result[: t_start + 1] + to_move + result[t_start + 1 :]
    return "\n".join(result)


def close_week(text: str) -> tuple[str, list[str]]:
    lines = text.split("\n")
    sun = _find_heading(lines, "Sun")
    if sun is not None:
        sun_hd = _heading_date(lines[sun])
        assert sun_hd is not None
        sun_range = _get_day_range(lines, "Sun", sun_hd[1])
        assert sun_range is not None

        carried: list[str] = []
        kept: list[str] = []
        for i in range(sun_range[0], sun_range[1]):
            line = lines[i]
            im = _match_item(line)
            if im and im.group(1).lower() != "x":
                if im.group(4) is None:
                    line += " (carried from Sun)"
                carried.append(line)
            else:
                kept.append(line)

        lines = lines[: sun_range[0]] + kept + lines[sun_range[1] :]
    else:
        carried = []

    week = parse_week("\n".join(lines), "")
    done_index: list[str] = []
    for item in week.items:
        if item.done:
            im = _ITEM_RE.match(item.line)
            assert im is not None
            done_index.append(f"- {item.cat}: {im.group(3)}")

    done_start = None
    for i, line in enumerate(lines):
        if line == DONE_HEADING:
            done_start = i
            break

    if done_start is not None:
        done_end = len(lines)
        for i in range(done_start + 1, len(lines)):
            if lines[i].startswith("## "):
                done_end = i
                break
        lines = lines[:done_start] + [DONE_HEADING, *done_index, ""] + lines[done_end:]
    else:
        first_day = None
        for i, line in enumerate(lines):
            hd = _heading_date(line)
            if hd:
                first_day = i
                break
        if first_day is None:
            return text, carried
        insert_at = first_day
        lines = lines[:insert_at] + [DONE_HEADING, *done_index, ""] + lines[insert_at:]

    return "\n".join(lines), carried


def open_week(text: str | None, monday: date, carried: list[str], stage: object = None) -> str:
    if monday.weekday() != 0:
        raise ValueError("monday must be a Monday")

    if text is None:
        fm: dict[str, object] = {"tags": ["weekly"], "week": monday.isoformat()}
        if stage is not None:
            fm["stage"] = stage
        lines = dump(fm).split("\n")
        for i in range(7):
            d = monday + timedelta(days=i)
            lines.append(f"## {DAY_ABBRS[i]} {d.isoformat()}")
            lines.append("")
        if carried:
            lines = lines[: lines.index(f"## Mon {monday.isoformat()}") + 1] + carried + lines[lines.index(f"## Mon {monday.isoformat()}") + 1 :]
        return "\n".join(lines)

    lines = text.split("\n")
    if not carried:
        return text
    mon_idx = _find_heading(lines, "Mon", monday)
    if mon_idx is None:
        raise ValueError(f"no heading for {monday.isoformat()}")
    insert = [c for c in carried if c not in lines]
    if not insert:
        return text
    return "\n".join(lines[: mon_idx + 1] + insert + lines[mon_idx + 1 :])
