"""
libra.study.frontmatter
───────────────────────
Minimal, dependency-free YAML-frontmatter read/write for vault notes.

Deliberately not a general YAML implementation — flat `key: value` scalars
(plus block lists of scalars) only; scalar values may be strings, ints,
floats, bools, None, which is everything a vault note needs. Reaching for
a real YAML lib is fine once the vault needs nested structures; until
then this module stays stdlib-only.

Format matches what Obsidian and every static-site generator expects:

    ---
    key: value
    ---
    body text
"""
from __future__ import annotations

_SCALAR_NONE = "null"


def _dump_scalar(value: object) -> str:
    if value is None:
        return _SCALAR_NONE
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    # Quote if it contains anything YAML would otherwise misparse — OR if
    # it looks like a number/bool/null and would silently come back as a
    # DIFFERENT TYPE on load. Found by tests/test_instructions.py: a
    # string field like version="1.0" was written unquoted, then read
    # back as the float 1.0 — round-trip type corruption, not just a
    # cosmetic issue. `_load_scalar` is the actual authority on what
    # counts as ambiguous, so ask it rather than duplicating its rules.
    needs_quoting = (
        any(c in text for c in ":#\"'\n\r")
        or text.strip() != text
        or text in ("", "null", "true", "false")
        or _load_scalar(text) != text
    )
    if needs_quoting:
        escaped = (
            text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )
        return f'"{escaped}"'
    return text


def _load_scalar(text: str) -> object:
    text = text.strip()
    if text == _SCALAR_NONE or text == "":
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        inner = text[1:-1]
        out: list[str] = []
        i = 0
        while i < len(inner):
            c = inner[i]
            if c == "\\" and i + 1 < len(inner):
                nxt = inner[i + 1]
                if nxt == "\\":
                    out.append("\\")
                    i += 2
                    continue
                if nxt == '"':
                    out.append('"')
                    i += 2
                    continue
                if nxt == "n":
                    out.append("\n")
                    i += 2
                    continue
                if nxt == "r":
                    out.append("\r")
                    i += 2
                    continue
            out.append(c)
            i += 1
        return "".join(out)
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def dump(frontmatter: dict[str, object], body: str = "") -> str:
    """Render `frontmatter` + `body` as a markdown file with a YAML header."""
    lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, (list, tuple)):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {_dump_scalar(item)}")
        else:
            lines.append(f"{k}: {_dump_scalar(v)}")
    lines.append("---")
    text = "\n".join(lines) + "\n"
    if body:
        text += "\n" + body.rstrip("\n") + "\n"
    return text


class FrontmatterError(ValueError):
    """The file has no `---`-delimited header, or a line inside it doesn't parse."""


class NoFrontmatterHeader(FrontmatterError):
    """Specifically "this file never had a `---` header at all" — distinct
    from a header that started but is malformed (bad line, never closed).
    A caller reading a vault where not every note carries frontmatter
    (Obsidian doesn't require it) needs to tell those apart: "no header"
    is a legitimate, common case to fall back on; "header present but
    broken" is real data corruption that should be quarantined, not
    silently reinterpreted as body text. Subclasses FrontmatterError, so
    a caller that doesn't care about the distinction can keep catching the
    base class unchanged."""


def load(text: str) -> tuple[dict[str, object], str]:
    """Returns (frontmatter_dict, body). Raises FrontmatterError if malformed."""
    if not text.startswith("---\n") and text.strip() != "---":
        raise NoFrontmatterHeader("no frontmatter header found (must start with '---')")
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise NoFrontmatterHeader("no frontmatter header found (must start with '---')")
    fm: dict[str, object] = {}
    last_key: str | None = None
    last_key_empty: bool = False
    result: list[object] | None = None
    result_key: str | None = None
    i = 1
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            break
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- ") or stripped == "-":
            if last_key is None:
                raise FrontmatterError(f"malformed frontmatter line {i}: {line!r}")
            if not last_key_empty:
                raise FrontmatterError(f"malformed frontmatter line {i}: {line!r}")
            if result_key != last_key:
                result = []
                result_key = last_key
                fm[last_key] = result
            assert result is not None
            item_text = stripped[1:].strip() if stripped != "-" else ""
            result.append(_load_scalar(item_text))
            continue
        if ":" not in line:
            raise FrontmatterError(f"malformed frontmatter line {i}: {line!r}")
        key, _, raw_value = line.partition(":")
        value = _load_scalar(raw_value)
        fm[key.strip()] = value
        last_key = key.strip()
        last_key_empty = raw_value.strip() == ""
        result_key = None
    else:
        raise FrontmatterError("frontmatter header never closed with '---'")
    body = "\n".join(lines[i + 1:]).strip("\n")
    return fm, body
