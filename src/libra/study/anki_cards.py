"""Anki card text for studied lessons (ADR-0045): Recall extraction, prompt, parse and lint, HTML, GUID."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from libra.study.check_kinds import RECALL_ITEM_RE
from libra.study.render import scan_blocks


__all__ = [
    "DECKS",
    "MAX_ANSWER_CHARS",
    "MAX_SECTION_CARDS",
    "Card",
    "recall_questions",
    "reading_sections",
    "reading_embeds",
    "signal_cards",
    "build_card_prompt",
    "parse_cards",
    "to_anki_html",
    "note_guid",
    "lesson_tag",
]


DECKS: dict[str, str] = {
    "PR": "Self study::Probability",
    "LA": "Self study::Linear Algebra",
    "OP": "Self study::Optimization",
    "DSP": "Self study::Signal Processing",
    "C": "Self study::C",
    "PY": "Self study::Python",
    "DSA": "Self study::DSA",
}

MAX_ANSWER_CHARS = 1200

MAX_SECTION_CARDS = 3


@dataclass(frozen=True)
class Card:
    question: str
    answer: str
    section: str | None = None


def recall_questions(text: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line == "## Recall":
            start = i
            break
    if start is None:
        return []

    questions: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if RECALL_ITEM_RE.match(line):
            stripped = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()
            questions.append(stripped)
    return questions


def reading_sections(text: str) -> list[str]:
    code = scan_blocks(tuple(text.splitlines())).code
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line == "## Reading" and not code[i]:
            start = i
            break
    if start is None:
        return []

    headings: list[str] = []
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if code[i]:
            continue
        if line.startswith("## "):
            break
        if line.startswith("### "):
            heading = line[4:].strip()
            if heading:
                headings.append(heading)
    return headings


def reading_embeds(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    scan = scan_blocks(tuple(lines))
    start = None
    for i, line in enumerate(lines):
        if line == "## Reading" and not scan.code[i]:
            start = i
            break
    if start is None:
        return []

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## ") and not scan.code[i]:
            end = i
            break

    return [(e.target, e.label) for e in scan.embeds if start < e.line < end]


_SIGNAL_RE = re.compile(r"^[-*] (.+)$")


def signal_cards(text: str, pattern: str) -> list[Card]:
    lines = text.splitlines()
    code = scan_blocks(tuple(lines)).code

    try:
        reading_start = next(
            i for i, line in enumerate(lines) if not code[i] and line == "## Reading"
        )
    except StopIteration:
        return []

    reading_end = next(
        (
            i
            for i in range(reading_start + 1, len(lines))
            if not code[i] and lines[i].startswith("## ")
        ),
        len(lines),
    )

    try:
        signals_start = next(
            i
            for i in range(reading_start + 1, reading_end)
            if not code[i] and lines[i] == "### Signals"
        )
    except StopIteration:
        return []

    signals_end = next(
        (
            i
            for i in range(signals_start + 1, reading_end)
            if not code[i]
            and (lines[i].startswith("### ") or lines[i].startswith("## "))
        ),
        reading_end,
    )

    seen: set[str] = set()
    cards: list[Card] = []
    for i in range(signals_start + 1, signals_end):
        if code[i]:
            continue
        match = _SIGNAL_RE.match(lines[i])
        if match is None:
            continue
        signal = match.group(1).strip()
        if not signal or signal in seen:
            continue
        seen.add(signal)
        cards.append(Card(f"Which pattern fits this signal: {signal}", pattern))

    return cards


def build_card_prompt(
    lesson_text: str,
    questions: Sequence[str],
    sections: Sequence[str],
    concepts: Sequence[tuple[str, str]] = (),
) -> str:
    parts = ["You write Anki flashcards for a self-study lesson."]
    if concepts:
        parts.append(
            "The lesson's Reading section embeds concept notes (lines like ![[...]]); their text follows the lesson below and counts as lesson text."
        )
    if questions:
        parts.extend(
            [
                "Answer each question using only the lesson text below. Keep each answer short: one to four sentences or a short list.",
                'Each such card is {"q": <the question copied exactly>, "a": <your answer>}.',
            ]
        )
    if sections:
        section_source = (
            "a ### heading of the lesson's Reading section, or the title of an embedded concept note"
            if concepts
            else "a ### heading of the lesson's Reading section"
        )
        parts.extend(
            [
                f"For each listed Reading concept ({section_source}), write one to three cards that test that part of the lesson: its core idea, a formula with what each symbol means, or a common trap or relationship to another concept.",
                "Every question must make sense on its own, without the lesson at hand, and must differ from every other question, the Recall questions included.",
                'Each such card is {"q": <your question>, "a": <your answer, using only the lesson text>, "section": <the concept heading copied exactly>}.',
            ]
        )
    parts.append(
        "Format: plain text with inline code in backticks, math in $...$ (inline) or $$...$$ (display), and **bold** for key terms. No headings, no HTML, no other Markdown."
    )
    parts.append(
        "Output only a JSON array: the Recall cards first, in question order, then the Reading cards grouped by concept in the listed order. No text before or after the array."
    )
    parts.append("")
    if questions:
        parts.append("Questions:")
        parts.extend(f"{i}. {q}" for i, q in enumerate(questions, 1))
        parts.append("")
    if sections:
        parts.append("Reading concepts:")
        parts.extend(f"{i}. {h}" for i, h in enumerate(sections, 1))
        parts.append("")
    parts.extend(["Lesson:", lesson_text])
    for label, body in concepts:
        parts.extend(["", f"Concept note: {label}", body])
    return "\n".join(parts)


def parse_cards(raw: str, questions: Sequence[str], sections: Sequence[str]) -> tuple[list[Card], list[str]]:
    first = raw.find("[")
    last = raw.rfind("]")
    if first == -1 or last == -1:
        return [], ["no JSON array found"]

    try:
        parsed = json.loads(raw[first : last + 1])
    except ValueError as exc:
        return [], [f"invalid JSON: {exc}"]

    if not isinstance(parsed, list):
        return [], ["not a JSON array"]

    n = len(questions)
    if len(parsed) < n or (not sections and len(parsed) != n):
        return [], [f"expected {n} cards, got {len(parsed)}"]

    stripped_sections = [s.strip() for s in sections]
    section_counts: dict[str, int] = {}
    for heading in stripped_sections:
        section_counts[heading] = 0

    seen = {q.strip() for q in questions}
    errors: list[str] = []
    cards: list[Card] = []

    for i, element in enumerate(parsed):
        if i < n:
            if not isinstance(element, dict) or not isinstance(element.get("q"), str) or not isinstance(element.get("a"), str):
                errors.append(f"card {i + 1}: needs string q and a")
                continue
            if element["q"].strip() != questions[i].strip():
                errors.append(f"card {i + 1}: question changed")
            if not element["a"].strip():
                errors.append(f"card {i + 1}: empty answer")
            elif len(element["a"].strip()) > MAX_ANSWER_CHARS:
                errors.append(f"card {i + 1}: answer too long")
            cards.append(Card(questions[i], element["a"].strip()))
            continue

        if not isinstance(element, dict) or not isinstance(element.get("q"), str) or not isinstance(element.get("a"), str) or not isinstance(element.get("section"), str):
            errors.append(f"card {i + 1}: needs string q, a and section")
            continue

        section = element["section"].strip()
        if section not in stripped_sections:
            errors.append(f"card {i + 1}: unknown section")
            continue

        q = element["q"].strip()
        if not q:
            errors.append(f"card {i + 1}: empty question")
            continue
        if q in seen:
            errors.append(f"card {i + 1}: duplicate question")
            continue

        a = element["a"].strip()
        if not a:
            errors.append(f"card {i + 1}: empty answer")
        elif len(a) > MAX_ANSWER_CHARS:
            errors.append(f"card {i + 1}: answer too long")

        seen.add(q)
        section_counts[section] += 1
        cards.append(Card(q, a, section))

    for heading in stripped_sections:
        count = section_counts.get(heading, 0)
        if count < 1 or count > MAX_SECTION_CARDS:
            errors.append(f"section {heading!r}: {count} cards, needs 1 to {MAX_SECTION_CARDS}")

    if errors:
        return [], errors
    return cards, []


_TOKEN_RE = re.compile(
    r"(`[^`\n]+`|\$\$.+?\$\$|\$[^$\n]+?\$|\*\*[^*\n]+?\*\*)",
    re.DOTALL,
)


def to_anki_html(text: str) -> str:
    out: list[str] = []
    for i, seg in enumerate(_TOKEN_RE.split(text)):
        if not seg:
            continue
        if i % 2 == 0:
            out.append(html.escape(seg, quote=False).replace("\n", "<br>"))
        elif seg.startswith("`"):
            out.append("<code>" + html.escape(seg[1:-1], quote=False) + "</code>")
        elif seg.startswith("$$"):
            out.append("\\[" + html.escape(seg[2:-2], quote=False) + "\\]")
        elif seg.startswith("$"):
            out.append("\\(" + html.escape(seg[1:-1], quote=False) + "\\)")
        else:
            out.append("<b>" + html.escape(seg[2:-2], quote=False) + "</b>")
    return "".join(out)


def note_guid(path: str, question: str) -> str:
    return "libra-" + hashlib.sha256(f"{path}\n{question}".encode("utf-8")).hexdigest()[:20]


def lesson_tag(path: str) -> str:
    return "lesson::" + PurePosixPath(path).stem.replace(" ", "_")
