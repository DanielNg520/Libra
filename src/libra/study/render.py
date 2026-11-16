"""Markdown-to-HTML renderer for Obsidian study notes in the PWA Study view (ADR-0043)."""

from __future__ import annotations

import functools
import html
import logging
import re
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.rules_core import StateCore
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token
from markdown_it.utils import OptionsDict
from mdit_py_plugins.dollarmath import dollarmath_plugin

from libra.study.frontmatter import FrontmatterError, NoFrontmatterHeader, load

log = logging.getLogger(__name__)

LinkResolver = Callable[[str], str | None]
EmbedLoader = Callable[[str, str, int], str | None]

IMAGE_SUFFIXES: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
)


_WIKILINK_RE = re.compile(r"!?\[\[([^\]\n]+)\]\]")
_CALLOUT_RE = re.compile(r"^\[!([A-Za-z][\w-]*)\]([-+]?)(?:\s+(.*))?$")

HIDDEN_MARKERS: tuple[str, ...] = ("Definition.", "Axiom.", "Stated without proof.")

_FACT_INLINE_RE = re.compile(r"^\*\*[^*]+?:\*\*\s")


def _make_parser() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    dollarmath_plugin(md, allow_space=True, allow_digits=True, double_inline=True)
    md.inline.ruler.before("image", "wikilink", _wikilink_rule)
    md.add_render_rule("image", _render_md_image)
    md.core.ruler.push("fact_marker", _fact_marker_rule)
    md.core.ruler.push("callout", _callout_rule)
    md.core.ruler.push("embed", _embed_rule)
    return md


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    try:
        return load(text)
    except NoFrontmatterHeader:
        return {}, text
    except FrontmatterError:
        log.warning("Failed to parse frontmatter", exc_info=True)
        return {}, text


def _default_label(target: str) -> str:
    name = PurePosixPath(target).name
    if name.endswith(".md"):
        name = name[:-3]
    return name


def _wikilink_rule(state: StateInline, silent: bool) -> bool:
    if state.src[state.pos] not in ("[", "!"):
        return False
    match = _WIKILINK_RE.match(state.src, state.pos)
    if not match:
        return False
    if silent:
        state.pos = match.end()
        return True

    inner = match.group(1)
    embedded = state.src[state.pos] == "!"
    target, alias = _split_inner(inner)
    if not target:
        return False

    resolved = state.env["resolve"](target)
    suffix = PurePosixPath(target).suffix.lower()
    name = PurePosixPath(target).name

    if embedded and suffix in IMAGE_SUFFIXES:
        _render_image(state, target, name, alias, resolved)
    else:
        label = alias if alias and not alias.isdigit() else _default_label(target)
        token = _render_link(state, label, target, resolved)
        if embedded and resolved is not None:
            token.meta = {"embed": resolved, "label": label}

    state.pos = match.end()
    return True


def _split_inner(inner: str) -> tuple[str, str]:
    if "|" in inner:
        target, alias = inner.split("|", 1)
        return target.split("#", 1)[0].strip(), alias.strip()
    return inner.split("#", 1)[0].strip(), ""


def _render_image(
    state: StateInline, target: str, name: str, alias: str, resolved: str | None
) -> None:
    width = alias if alias.isdigit() else ""
    token = state.push("html_inline", "", 0)
    token.content = _image_html(name, name, width, resolved)


def _image_html(name: str, alt: str, width: str, resolved: str | None) -> str:
    if resolved is None:
        return (
            '<span class="wikilink missing">' + html.escape(name, quote=True) + "</span>"
        )
    attrs = f'class="study-img" src="/api/study/file?path={urllib.parse.quote(resolved, safe="/")}" alt="{html.escape(alt, quote=True)}" loading="lazy"'
    if width:
        attrs += f' width="{html.escape(width, quote=True)}"'
    return f"<img {attrs}>"


def _render_md_image(
    self: RendererHTML,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: dict[str, Any],
) -> str:
    token = tokens[idx]
    src = token.attrGet("src") or ""
    alt = self.renderInlineAsText(token.children or [], options, env)
    try:
        scheme = urllib.parse.urlsplit(src).scheme
    except ValueError:
        scheme = ""
    if scheme or src.startswith("//"):
        label = alt or src
        return (
            f'<a class="external-img" href="{html.escape(src, quote=True)}" rel="noopener noreferrer">'
            f"{html.escape(label, quote=True)}</a>"
        )
    target = urllib.parse.unquote(src)
    resolved = env["resolve"](target)
    name = PurePosixPath(target).name
    return _image_html(name, alt or name, "", resolved)


def _render_link(
    state: StateInline, label: str, target: str, resolved: str | None
) -> Token:
    if resolved is None:
        token = state.push("html_inline", "", 0)
        token.content = (
            '<span class="wikilink missing">' + html.escape(label, quote=True) + "</span>"
        )
        return token
    attrs = f'class="wikilink" href="#study/{urllib.parse.quote(resolved, safe="/")}" data-path="{html.escape(resolved, quote=True)}"'
    token = state.push("html_inline", "", 0)
    token.content = f"<a {attrs}>{html.escape(label, quote=True)}</a>"
    return token


def _fact_marker_rule(state: StateCore) -> None:
    for i, token in enumerate(state.tokens):
        if i < 2 or token.type != "inline":
            continue
        if state.tokens[i - 1].type != "paragraph_open":
            continue
        if state.tokens[i - 2].type != "list_item_open":
            continue
        if not _FACT_INLINE_RE.match(token.content) or not token.children:
            continue
        last = token.children[-1]
        if last.type != "text":
            continue
        stripped = last.content.rstrip()
        for marker in HIDDEN_MARKERS:
            if stripped.endswith(marker):
                last.content = stripped[: -len(marker)].rstrip()
                break


def _callout_rule(state: StateCore) -> None:
    for i, token in enumerate(state.tokens):
        if token.type != "blockquote_open":
            continue
        inline = _peek_inline(state.tokens, i)
        if inline is None:
            continue
        match = _match_callout(inline)
        if match is None:
            continue
        callout_type, fold, title_tokens = match
        title_html = state.md.renderer.renderInline(
            title_tokens, state.md.options, state.env
        ).strip()
        if not title_html:
            title_html = html.escape(callout_type.capitalize(), quote=True)
        _strip_title(inline)
        close_idx = _find_matching_close(state.tokens, i)
        if close_idx is None:
            continue
        _replace_with_html(state.tokens, i, close_idx, callout_type, fold, title_html)


def _peek_inline(tokens: list[Token], blockquote_idx: int) -> Token | None:
    if blockquote_idx + 2 >= len(tokens):
        return None
    if tokens[blockquote_idx + 1].type != "paragraph_open":
        return None
    inline = tokens[blockquote_idx + 2]
    if inline.type != "inline":
        return None
    return inline


def _match_callout(inline: Token) -> tuple[str, str, list[Token]] | None:
    if not inline.children:
        return None
    first = inline.children[0]
    if first.type != "text":
        return None
    match = _CALLOUT_RE.match(first.content)
    if not match:
        return None
    callout_type = match.group(1).lower()
    fold = match.group(2)
    remainder = (match.group(3) or "").lstrip()
    title_tokens: list[Token] = []
    if remainder:
        title_tokens.append(Token("text", "", 0, content=remainder))
    for child in inline.children[1:]:
        if child.type in ("softbreak", "hardbreak"):
            break
        title_tokens.append(child)
    return callout_type, fold, title_tokens


def _strip_title(inline: Token) -> None:
    children = inline.children
    drop_count = 0
    for child in children:
        drop_count += 1
        if child.type in ("softbreak", "hardbreak"):
            break
    del children[:drop_count]
    first_newline = inline.content.find("\n")
    if first_newline != -1:
        inline.content = inline.content[first_newline + 1 :]
    else:
        inline.content = ""


def _find_matching_close(tokens: list[Token], open_idx: int) -> int | None:
    depth = 0
    for i in range(open_idx, len(tokens)):
        if tokens[i].type == "blockquote_open":
            depth += 1
        elif tokens[i].type == "blockquote_close":
            depth -= 1
            if depth == 0:
                return i
    return None


def _replace_with_html(
    tokens: list[Token],
    open_idx: int,
    close_idx: int,
    callout_type: str,
    fold: str,
    title_html: str,
) -> None:
    class_type = re.sub(r"[^a-z0-9-]", "", callout_type)
    if fold == "-":
        open_html = f'<details class="callout callout-{class_type}">\n<summary>{title_html}</summary>\n'
        close_html = "</details>\n"
    elif fold == "+":
        open_html = f'<details class="callout callout-{class_type}" open>\n<summary>{title_html}</summary>\n'
        close_html = "</details>\n"
    else:
        open_html = f'<div class="callout callout-{class_type}">\n<div class="callout-title">{title_html}</div>\n'
        close_html = "</div>\n"

    open_token = Token("html_block", "", 0)
    open_token.content = open_html
    close_token = Token("html_block", "", 0)
    close_token.content = close_html
    tokens[open_idx] = open_token
    tokens[close_idx] = close_token


def _embed_children(paragraph: Token) -> list[Token]:
    """Embed tokens of an embed-only paragraph (only embeds and whitespace), else an empty list."""
    embeds = [
        child
        for child in paragraph.children or []
        if child.type == "html_inline" and "embed" in (child.meta or {})
    ]
    if embeds and all(
        child.type == "html_inline" and "embed" in (child.meta or {})
        or child.type in ("softbreak", "hardbreak")
        or child.type == "text" and not child.content.strip()
        for child in paragraph.children or []
    ):
        return embeds
    return []


def _embed_rule(state: StateCore) -> None:
    embed = state.env.get("embed")
    if embed is None:
        return

    new_tokens: list[Token] = []
    i = 0
    while i < len(state.tokens):
        if (
            state.tokens[i].type == "paragraph_open"
            and i + 2 < len(state.tokens)
            and state.tokens[i + 1].type == "inline"
            and state.tokens[i + 2].type == "paragraph_close"
        ):
            paragraph = state.tokens[i + 1]
            embeds = _embed_children(paragraph)
            if embeds:
                for embed_token in embeds:
                    number = state.env["embed_count"] + 1
                    result = embed(
                        embed_token.meta["embed"], embed_token.meta["label"], number
                    )
                    if isinstance(result, str):
                        state.env["embed_count"] += 1
                        token = Token("html_block", "", 0)
                        token.content = result
                        new_tokens.append(token)
                    else:
                        token = Token("html_block", "", 0)
                        token.content = "<p>" + embed_token.content + "</p>\n"
                        new_tokens.append(token)
                i += 3
                continue
        new_tokens.append(state.tokens[i])
        i += 1
    state.tokens = new_tokens


_md = _make_parser()


@dataclass(frozen=True)
class Fence:
    start: int
    end: int
    info: str
    content: str
    quoted: bool
    closed: bool


@dataclass(frozen=True)
class Embed:
    line: int
    target: str
    label: str


@dataclass(frozen=True)
class BlockScan:
    code: tuple[bool, ...]
    fences: tuple[Fence, ...]
    embeds: tuple[Embed, ...]


def _scan_resolve(target: str) -> str:
    return target


@functools.lru_cache(maxsize=64)
def scan_blocks(lines: tuple[str, ...]) -> BlockScan:
    """Code lines, fences and embed-only paragraphs exactly as the page parser sees them."""
    source = "\n".join(lines)
    tokens = _md.parse(source, {"resolve": _scan_resolve})

    code = [False] * len(lines)
    fences: list[Fence] = []
    embeds: list[Embed] = []

    for i, token in enumerate(tokens):
        if token.map is None:
            continue
        if token.type in ("fence", "code_block"):
            for line in range(token.map[0], min(token.map[1], len(lines))):
                code[line] = True
        if token.type == "fence":
            markup = token.markup or ""
            source_prefix = lines[token.map[0]][: lines[token.map[0]].find(markup)] if markup else lines[token.map[0]]
            quoted = ">" in source_prefix
            closed = False
            if token.map[1] - token.map[0] >= 2 and markup:
                last = re.sub(r"^[\s>]*", "", lines[token.map[1] - 1]).rstrip()
                closed = bool(last) and all(c == markup[0] for c in last) and len(last) >= len(markup)
            fences.append(
                Fence(
                    start=token.map[0],
                    end=token.map[1],
                    info=(token.info or "").strip(),
                    content=token.content,
                    quoted=quoted,
                    closed=closed,
                )
            )
        if (
            i + 2 < len(tokens)
            and token.type == "paragraph_open"
            and tokens[i + 1].type == "inline"
            and tokens[i + 2].type == "paragraph_close"
        ):
            for child in _embed_children(tokens[i + 1]):
                embeds.append(
                    Embed(
                        line=token.map[0],
                        target=child.meta["embed"],
                        label=child.meta["label"],
                    )
                )

    return BlockScan(code=tuple(code), fences=tuple(fences), embeds=tuple(embeds))


__all__ = [
    "LinkResolver",
    "EmbedLoader",
    "IMAGE_SUFFIXES",
    "split_frontmatter",
    "Fence",
    "Embed",
    "BlockScan",
    "scan_blocks",
]
