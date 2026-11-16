"""Self study plan files: Current.md and Master index.md (owner, 2026-11-16)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

log = logging.getLogger(__name__)

CATEGORIES: tuple[str, ...] = ("PR", "LA", "OP", "DSP", "C", "PY", "DSA", "EXTRA")

CURRENT = PurePosixPath("Self study/Current.md")
MASTER_INDEX = PurePosixPath("Self study/Master index.md")
PLAN_FILES: tuple[PurePosixPath, ...] = (CURRENT, MASTER_INDEX)

_WIKILINK_RE = re.compile(r"^\[\[([^|\]]+?)(?:\|([^\]]+))?\]\]$")
_CODE_RE = re.compile(r"^`([^`]+)`$")
_ITEM_RE = re.compile(
    r"^- \[([ xX])\] (" + "|".join(map(re.escape, CATEGORIES)) + r"): (.*)$"
)


@dataclass(frozen=True)
class Item:
    cat: str
    label: str
    path: str | None
    code: str | None
    done: bool
    line: str


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


def parse_items(text: str) -> tuple[Item, ...]:
    items: list[Item] = []
    for line in text.splitlines():
        m = _ITEM_RE.match(line)
        if not m:
            continue
        cat = m.group(2)
        label, path, code = _parse_target(m.group(3))
        items.append(Item(cat, label, path, code, m.group(1).lower() == "x", line))
    return tuple(items)


def plan_items(vault: Path) -> tuple[Item, ...]:
    items: list[Item] = []
    for plan_file in PLAN_FILES:
        file_path = vault / plan_file
        try:
            text = file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError:
            log.warning("Could not read plan file: %s", plan_file)
            continue
        except UnicodeDecodeError:
            log.warning("Could not decode plan file: %s", plan_file)
            continue
        items.extend(parse_items(text))
    return tuple(items)


__all__ = ["CATEGORIES", "CURRENT", "MASTER_INDEX", "PLAN_FILES", "Item", "parse_items", "plan_items"]
