"""Tests for the C2 concept and section kinds (`study/check_concepts.py`) and the C2 changes in `study/check_kinds.py`."""

from pathlib import Path

import pytest

from libra.study.check_concepts import (
    concept_units,
    count_concepts,
    fence_mask,
    section_bounds,
    words_outside_code,
)
from libra.study.check_kinds import KINDS, parse_lesson

FRONTMATTER = """---
tags:
  - topic/probability
---
"""


def _body(*lines: str) -> str:
    return "\n".join(lines)


def _lesson(body: str, rel: str = "Self study/Probability/02 x.md"):
    return parse_lesson(FRONTMATTER + body, rel)


def _run_lesson(
    kind: str,
    params: dict,
    body: str,
    rel: str = "Self study/Probability/02 x.md",
    vault: Path = Path("/nonexistent"),
) -> list[tuple[int | None, str]]:
    text = FRONTMATTER + body
    lesson = parse_lesson(text, rel)
    return KINDS[kind].check(lesson, params, vault)


class TestFenceMask:
    def test_plain(self) -> None:
        lines = ["a", "b", "c"]
        assert fence_mask(lines) == [False, False, False]

    def test_closed_fence(self) -> None:
        lines = ["a", "```py", "x", "```", "b"]
        assert fence_mask(lines) == [False, True, True, True, False]

    def test_open_fence(self) -> None:
        lines = ["a", "```py", "x", "y"]
        assert fence_mask(lines) == [False, True, True, True]

    def test_lstrip(self) -> None:
        lines = ["a", "   ```py", "x", "```", "b"]
        assert fence_mask(lines) == [False, True, True, True, False]

    def test_tilde_fence(self) -> None:
        lines = ["a", "~~~", "```", "~~~", "b"]
        assert fence_mask(lines) == [False, True, True, True, False]

    def test_long_fence_with_inner_marker(self) -> None:
        lines = ["````md", "```", "x", "```", "````", "b"]
        assert fence_mask(lines) == [True, True, True, True, True, False]

    def test_indented_code(self) -> None:
        lines = ["a", "", "    code", "", "b"]
        assert fence_mask(lines) == [False, False, True, False, False]


class TestSectionBounds:
    def test_found(self) -> None:
        lines = ["a", "## Reading", "x", "## Practice", "y"]
        mask = fence_mask(lines)
        assert section_bounds(lines, "## Reading", mask) == (1, 3)

    def test_ends_at_end(self) -> None:
        lines = ["a", "## Reading", "x", "y"]
        mask = fence_mask(lines)
        assert section_bounds(lines, "## Reading", mask) == (1, 4)

    def test_masked_heading_ignored(self) -> None:
        lines = ["a", "## Reading", "```", "## Practice", "```", "x"]
        mask = fence_mask(lines)
        assert section_bounds(lines, "## Reading", mask) == (1, 6)

    def test_absent(self) -> None:
        lines = ["a", "b"]
        mask = fence_mask(lines)
        assert section_bounds(lines, "## Reading", mask) is None

    def test_heading_inside_fence_not_found(self) -> None:
        lines = ["```", "## Reading", "```", "x"]
        mask = fence_mask(lines)
        assert section_bounds(lines, "## Reading", mask) is None


class TestConceptUnits:
    def test_heading(self) -> None:
        lines = [
            "## Reading",
            "### 1. Alpha",
            "x",
            "### Python build",
            "y",
            "### 2. Beta",
            "z",
            "## Sources",
        ]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        assert concept_units(lesson, "heading", "## Reading", mask) == [
            (1, 3, "1. Alpha"),
            (5, 7, "2. Beta"),
        ]

    def test_heading_only_in_section(self) -> None:
        lines = ["## Other", "### 1. Alpha", "x", "## Reading", "y"]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        assert concept_units(lesson, "heading", "## Reading", mask) == []

    def test_file(self) -> None:
        lines = ["a", "b", "## Sources", "c"]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        assert concept_units(lesson, "file", "## Reading", mask) == [
            (0, 2, "concept note")
        ]

    def test_other_unit(self) -> None:
        lines = ["a"]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        with pytest.raises(ValueError):
            concept_units(lesson, "x", "## Reading", mask)


class TestCountConcepts:
    def test_headings_only(self) -> None:
        lines = ["## Reading", "### 1. A", "x", "### 2. B", "y", "## Sources"]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        assert count_concepts(lesson, "## Reading", mask) == 2

    def test_embeds(self) -> None:
        lines = [
            "## Reading",
            "![[Self study/P/concepts/A|A]]",
            "![[Self study/P/concepts/B|B]]",
            "## Sources",
        ]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        assert count_concepts(lesson, "## Reading", mask) == 2

    def test_image_embeds_not_counted(self) -> None:
        lines = ["## Reading", "![[figures/a.png]]", "## Sources"]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        assert count_concepts(lesson, "## Reading", mask) == 0

    def test_fenced_content_not_counted(self) -> None:
        lines = ["## Reading", "```", "### 1. A", "```", "## Sources"]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        assert count_concepts(lesson, "## Reading", mask) == 0


class TestWordsOutsideCode:
    def test_basic(self) -> None:
        lines = ["one two", "```", "fenced words", "```", "three", "## Sources", "ignored words"]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        assert words_outside_code(lesson, mask) == 3

    def test_blank_lines(self) -> None:
        lines = ["", "a b", "", "## Sources", "c d"]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        assert words_outside_code(lesson, mask) == 2

    def test_unmasked_fence_blocks_all(self) -> None:
        lines = ["x y", "```", "fenced"]
        lesson = _lesson(_body(*lines))
        mask = fence_mask(lines)
        assert words_outside_code(lesson, mask) == 2


class TestPerConcept:
    CHECK_LABEL = r"^\*\*Check\b"

    def _concept_body(self, with_check2: bool = True, check2_count: int = 1) -> tuple[str, list[str]]:
        lines = ["## Reading", "### 1. Alpha", "**Check.** one", "body", "### 2. Beta"]
        if with_check2:
            lines.extend(["**Check.** two"] * check2_count)
        lines.extend(["body2", "## Sources"])
        return _body(*lines), lines

    def test_pass_two_concepts(self) -> None:
        body, _ = self._concept_body()
        params = {"unit": "heading", "label": self.CHECK_LABEL, "min": 1, "max": 2}
        assert _run_lesson("per_concept", params, body) == []

    def test_missing_second(self) -> None:
        body, lines = self._concept_body(with_check2=False)
        params = {"unit": "heading", "label": self.CHECK_LABEL, "min": 1, "max": 2}
        findings = _run_lesson("per_concept", params, body)
        heading_line = lines.index("### 2. Beta") + 5
        assert findings == [
            (heading_line, "2. Beta: expected 1-2 checks, found 0")
        ]

    def test_three_checks(self) -> None:
        body, _ = self._concept_body(check2_count=3)
        params = {"unit": "heading", "label": self.CHECK_LABEL, "min": 1, "max": 2}
        findings = _run_lesson("per_concept", params, body)
        assert len(findings) == 1
        assert findings[0][1].endswith("found 3")

    def test_check_in_fence_not_counted(self) -> None:
        lines = [
            "## Reading",
            "### 1. Alpha",
            "```",
            "**Check.** fenced",
            "```",
            "### 2. Beta",
            "**Check.** real",
            "## Sources",
        ]
        body = _body(*lines)
        params = {"unit": "heading", "label": self.CHECK_LABEL, "min": 1, "max": 2}
        findings = _run_lesson("per_concept", params, body)
        heading_line = lines.index("### 1. Alpha") + 5
        assert findings == [
            (heading_line, "1. Alpha: expected 1-2 checks, found 0")
        ]

    def test_file_pass(self) -> None:
        body = _body("intro", "**Check.** one", "## Sources")
        params = {"unit": "file", "label": self.CHECK_LABEL, "min": 1, "max": 2}
        assert _run_lesson("per_concept", params, body) == []

    def test_file_missing(self) -> None:
        body = _body("intro", "## Sources")
        params = {"unit": "file", "label": self.CHECK_LABEL, "min": 1, "max": 2}
        findings = _run_lesson("per_concept", params, body)
        assert len(findings) == 1
        assert findings[0][1].startswith("concept note: expected 1-2 checks")

    def test_file_check_after_sources_not_counted(self) -> None:
        body = _body("intro", "## Sources", "**Check.** after")
        params = {"unit": "file", "label": self.CHECK_LABEL, "min": 1, "max": 2}
        findings = _run_lesson("per_concept", params, body)
        assert len(findings) == 1
        assert findings[0][1].startswith("concept note: expected 1-2 checks")

    def test_require_both_present(self) -> None:
        lines = [
            "## Reading",
            "### 1. Alpha",
            "**Idea.** x",
            "**Worked example**",
            "### 2. Beta",
            "**Idea.** y",
            "**Worked example**",
            "## Sources",
        ]
        body = _body(*lines)
        params = {
            "unit": "heading",
            "require": [r"^\*\*Idea\.\*\*", r"^\*\*Worked example"],
        }
        assert _run_lesson("per_concept", params, body) == []

    def test_require_missing(self) -> None:
        lines = [
            "## Reading",
            "### 1. Alpha",
            "**Worked example**",
            "### 2. Beta",
            "**Idea.** y",
            "**Worked example**",
            "## Sources",
        ]
        body = _body(*lines)
        pattern = r"^\*\*Idea\.\*\*"
        params = {"unit": "heading", "require": [pattern, r"^\*\*Worked example"]}
        findings = _run_lesson("per_concept", params, body)
        heading_line = lines.index("### 1. Alpha") + 5
        assert findings == [
            (heading_line, f"1. Alpha: missing {pattern!r}")
        ]

    def test_require_in_code_pass(self) -> None:
        lines = [
            "## Reading",
            "### 1. Alpha",
            "```",
            "broken code",
            "```",
            "## Sources",
        ]
        body = _body(*lines)
        params = {"unit": "heading", "require_in_code": [r"broken"]}
        assert _run_lesson("per_concept", params, body) == []

    def test_require_in_code_missing(self) -> None:
        lines = [
            "## Reading",
            "### 1. Alpha",
            "broken prose",
            "## Sources",
        ]
        body = _body(*lines)
        pattern = r"broken"
        params = {"unit": "heading", "require_in_code": [pattern]}
        findings = _run_lesson("per_concept", params, body)
        heading_line = lines.index("### 1. Alpha") + 5
        assert findings == [
            (heading_line, f"1. Alpha: code lacks {pattern!r}")
        ]

    def test_max_prose_lines_pass(self) -> None:
        lines = [
            "## Reading",
            "### 1. Alpha",
            "first prose",
            "second prose",
            "Broken: ignored",
            "Fixed: ignored",
            "**Check.** ignored",
            "> callout",
            "```",
            "fenced",
            "```",
            "![[figures/a.png]]",
            "",
            "## Sources",
        ]
        body = _body(*lines)
        params = {
            "unit": "heading",
            "max_prose_lines": 2,
            "prose_skip": r"^(\*\*Check\b|Broken\b|Fixed\b)",
        }
        assert _run_lesson("per_concept", params, body) == []

    def test_max_prose_lines_exceeded(self) -> None:
        lines = [
            "## Reading",
            "### 1. Alpha",
            "first prose",
            "second prose",
            "third prose",
            "**Check.** ignored",
            "## Sources",
        ]
        body = _body(*lines)
        params = {
            "unit": "heading",
            "max_prose_lines": 2,
            "prose_skip": r"^(\*\*Check\b|Broken\b|Fixed\b)",
        }
        findings = _run_lesson("per_concept", params, body)
        heading_line = lines.index("### 1. Alpha") + 5
        assert findings == [(heading_line, "1. Alpha: 3 prose lines, max 2")]

    def test_max_prose_lines_no_skip_fails(self) -> None:
        lines = [
            "## Reading",
            "### 1. Alpha",
            "first prose",
            "second prose",
            "**Check.** x",
            "```",
            "fenced",
            "```",
            "## Sources",
        ]
        body = _body(*lines)
        params = {"unit": "heading", "max_prose_lines": 2}
        assert _run_lesson("per_concept", params, body) != []

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"unit": "x"}, "unit must be 'heading' or 'file', not 'x'"),
            (
                {"unit": "heading", "label": "a"},
                "label, min and max go together",
            ),
            (
                {"unit": "heading", "label": "a", "min": 3, "max": 1},
                "min must not exceed max",
            ),
            (
                {"unit": "heading", "max_prose_lines": -1},
                "max_prose_lines must not be negative",
            ),
            (
                {"unit": "heading", "require": ["("]},
                "bad regex '('",
            ),
            (
                {"unit": "heading", "prose_skip": "["},
                "bad regex '['",
            ),
        ],
    )
    def test_validate(self, params: dict, expected: str) -> None:
        result = KINDS["per_concept"].validate(params)
        assert result is not None
        assert result.startswith(expected)

    def test_validate_pass(self) -> None:
        assert KINDS["per_concept"].validate({"unit": "heading"}) is None


class TestSectionShape:
    ORDER = [
        r"^### (Python (build|check)|Build check)$",
        r"^### (Master[- ]class|Application)\b",
    ]
    LABEL = r"^\*\*"

    def _params(self, **overrides: object) -> dict:
        params: dict = {
            "section": "## Practice",
            "order": self.ORDER,
            "label": self.LABEL,
            "min_items": 1,
            "max_items": 2,
        }
        params.update(overrides)
        return params

    def _practice(self, body_extra: tuple[str, ...] = ()) -> tuple[str, list[str]]:
        lines = [
            "## Practice",
            "**P1.** one",
            "**P2.** two",
            *body_extra,
            "### Python build",
            "### Master class: x",
            "## Sources",
        ]
        return _body(*lines), lines

    def test_pass(self) -> None:
        body, _ = self._practice()
        assert _run_lesson("section_shape", self._params(), body) == []

    def test_disallowed_heading(self) -> None:
        lines = [
            "## Practice",
            "**P1.** one",
            "### Drills",
            "### Python build",
            "### Master class: x",
            "## Sources",
        ]
        body = _body(*lines)
        findings = _run_lesson("section_shape", self._params(allowed=self.ORDER), body)
        line = lines.index("### Drills") + 5
        assert findings == [(line, "## Practice: heading not allowed: ### Drills")]

    def test_master_before_build(self) -> None:
        lines = [
            "## Practice",
            "**P1.** one",
            "### Master class: x",
            "### Python build",
            "## Sources",
        ]
        body = _body(*lines)
        findings = _run_lesson("section_shape", self._params(), body)
        assert len(findings) == 1
        assert findings[0][1].endswith("part out of order: ### Master class: x")

    def test_build_missing(self) -> None:
        lines = [
            "## Practice",
            "**P1.** one",
            "### Master class: x",
            "## Sources",
        ]
        body = _body(*lines)
        findings = _run_lesson("section_shape", self._params(), body)
        assert len(findings) == 1
        assert findings[0][1].startswith("## Practice: missing part")

    def test_three_problems(self) -> None:
        lines = [
            "## Practice",
            "**P1.** one",
            "**P2.** two",
            "**P3.** three",
            "### Python build",
            "### Master class: x",
            "## Sources",
        ]
        body = _body(*lines)
        findings = _run_lesson("section_shape", self._params(), body)
        line = lines.index("## Practice") + 5
        assert findings == [
            (line, "## Practice: opening set has 3 problems, expected 1-2")
        ]

    def test_zero_problems(self) -> None:
        lines = [
            "## Practice",
            "### Python build",
            "### Master class: x",
            "## Sources",
        ]
        body = _body(*lines)
        findings = _run_lesson("section_shape", self._params(), body)
        line = lines.index("## Practice") + 5
        assert findings == [
            (line, "## Practice: opening set has 0 problems, expected 1-2")
        ]

    def test_after_build_not_in_opening(self) -> None:
        lines = [
            "## Practice",
            "**P1.** one",
            "### Python build",
            "**P3.** after",
            "### Master class: x",
            "## Sources",
        ]
        body = _body(*lines)
        params = self._params(max_items=1)
        assert _run_lesson("section_shape", params, body) == []

    def test_section_absent(self) -> None:
        body = _body("## Reading", "x", "## Sources")
        assert _run_lesson("section_shape", self._params(), body) == []

    def test_validate_items_need_label(self) -> None:
        params = {"section": "## Practice", "max_items": 3}
        result = KINDS["section_shape"].validate(params)
        assert result is not None
        assert result.startswith("min_items and max_items need label")

    def test_validate_min_max(self) -> None:
        params = {
            "section": "## Practice",
            "label": self.LABEL,
            "min_items": 3,
            "max_items": 1,
        }
        result = KINDS["section_shape"].validate(params)
        assert result == "min_items must not exceed max_items"

    def test_validate_bad_regex(self) -> None:
        params = {
            "section": "## Practice",
            "order": ["("],
        }
        result = KINDS["section_shape"].validate(params)
        assert result is not None
        assert result.startswith("bad regex")


class TestSize:
    def test_concepts_pass(self) -> None:
        body = _body("## Reading", "### 1. A", "x", "### 2. B", "y", "## Sources")
        params = {"measure": "concepts", "max": 2}
        assert _run_lesson("size", params, body) == []

    def test_concepts_exceeded(self) -> None:
        body = _body(
            "## Reading",
            "### 1. A",
            "x",
            "### 2. B",
            "y",
            "![[Self study/P/concepts/C|C]]",
            "## Sources",
        )
        params = {"measure": "concepts", "max": 2}
        assert _run_lesson("size", params, body) == [
            (None, "size: 3 concepts, max 2")
        ]

    def test_image_not_counted(self) -> None:
        body = _body(
            "## Reading",
            "### 1. A",
            "x",
            "### 2. B",
            "y",
            "![[figures/a.png]]",
            "## Sources",
        )
        params = {"measure": "concepts", "max": 2}
        assert _run_lesson("size", params, body) == []

    def test_words_pass(self) -> None:
        body = _body(
            "one two three four five",
            "```",
            "fenced words ignored here too many",
            "```",
            "## Sources",
            "after sources words",
        )
        params = {"measure": "words", "max": 5}
        assert _run_lesson("size", params, body) == []

    def test_words_exceeded(self) -> None:
        body = _body("one two three four five six", "## Sources")
        params = {"measure": "words", "max": 5}
        assert _run_lesson("size", params, body) == [
            (None, "size: 6 words, max 5")
        ]

    def test_validate_measure(self) -> None:
        result = KINDS["size"].validate({"measure": "lines", "max": 1})
        assert result == "measure must be 'concepts' or 'words', not 'lines'"

    def test_validate_negative_max(self) -> None:
        result = KINDS["size"].validate({"measure": "words", "max": -1})
        assert result == "max must not be negative"


class TestHeadingOrder:
    def test_last_ok(self) -> None:
        body = _body("## Reading", "x", "## Sources")
        params = {"headings": ["## Reading"], "last": "## Sources"}
        assert _run_lesson("heading_order", params, body) == []

    def test_not_last(self) -> None:
        body = _body("## Reading", "x", "## Sources", "## Extra", "y")
        params = {"headings": ["## Reading"], "last": "## Sources"}
        assert _run_lesson("heading_order", params, body) == [
            (None, "heading not last: ## Sources")
        ]

    def test_fenced_heading_ignored(self) -> None:
        body = _body(
            "## Reading",
            "x",
            "## Sources",
            "```",
            "## Extra",
            "```",
        )
        params = {"headings": ["## Reading"], "last": "## Sources"}
        assert _run_lesson("heading_order", params, body) == []

    def test_no_other_headings(self) -> None:
        body = _body("## Reading", "x")
        params = {"headings": ["## Reading"], "last": "## Sources"}
        assert _run_lesson("heading_order", params, body) == [
            (None, "heading not last: ## Sources")
        ]


class TestFrontmatterTags:
    def _frontmatter(self, body: str, rel: str) -> str:
        return f"---\n{body}\n---\nContent\n"

    def _run(
        self,
        params: dict,
        frontmatter_body: str,
        rel: str = "Self study/Probability/02 x.md",
    ) -> list[tuple[int | None, str]]:
        text = self._frontmatter(frontmatter_body, rel)
        lesson = parse_lesson(text, rel)
        return KINDS["frontmatter"].check(lesson, params, Path("/nonexistent"))

    def _params(self) -> dict:
        return {
            "field": "tags",
            "allowed": ["topic/probability", "topic/dsp"],
            "required_by_glob": {"Self study/Probability/*": "topic/probability"},
            "max": 1,
        }

    def test_one_tag(self) -> None:
        assert self._run(self._params(), "tags:\n  - topic/probability") == []

    def test_two_tags(self) -> None:
        findings = self._run(
            self._params(), "tags:\n  - topic/probability\n  - topic/dsp"
        )
        assert findings == [(None, "tags: at most 1 tags, found 2")]

    def test_no_required_match(self) -> None:
        findings = self._run(
            self._params(),
            "tags:\n  - topic/probability",
            rel="Self study/New topic/02 x.md",
        )
        assert findings == [(None, "tags: no required tag for this path")]


class TestAnswers:
    def _params(self, label: str | None = None) -> dict:
        params: dict = {"prefix": "> [!success]-"}
        if label is not None:
            params["label"] = label
        return params

    def _passing_body(self) -> tuple[str, list[str]]:
        lines = [
            "## Reading",
            "**Check.** one",
            "x",
            "```",
            "code",
            "```",
            "",
            "> [!success]- Answer",
            "**Check.** two",
            "y",
            "```",
            "code",
            "```",
            "",
            "> [!success]- Answer",
            "## Sources",
        ]
        return _body(*lines), lines

    def test_pass(self) -> None:
        body, _ = self._passing_body()
        params = self._params(label=r"^\*\*(?!(Idea|Worked example)\b)")
        assert _run_lesson("answers", params, body) == []

    def test_missing_second(self) -> None:
        lines = [
            "## Reading",
            "**Check.** one",
            "x",
            "```",
            "code",
            "```",
            "",
            "> [!success]- Answer",
            "**Check.** two",
            "y",
            "### 2. Next",
            "> [!success]- Answer",
            "## Sources",
        ]
        body = _body(*lines)
        params = self._params(label=r"^\*\*(?!(Idea|Worked example)\b)")
        findings = _run_lesson("answers", params, body)
        line = lines.index("**Check.** two") + 5
        assert len(findings) == 1
        assert findings[0][0] == line
        assert findings[0][1].startswith("answers: no folded answer after '**Check.")

    def test_idea_not_requiring_answer(self) -> None:
        lines = [
            "## Reading",
            "**Idea.** x",
            "body",
            "## Sources",
        ]
        body = _body(*lines)
        params = self._params(label=r"^\*\*(?!(Idea|Worked example)\b)")
        assert _run_lesson("answers", params, body) == []

    def test_callout_inside_fence_counts(self) -> None:
        lines = [
            "## Reading",
            "**Check.** one",
            "```",
            "> [!success]- Answer",
            "```",
            "## Sources",
        ]
        body = _body(*lines)
        params = self._params(label=r"^\*\*(?!(Idea|Worked example)\b)")
        assert _run_lesson("answers", params, body) == []

    def test_old_behaviour_without_label(self) -> None:
        body = _body("## Reading", "x", "## Sources")
        params = self._params()
        assert _run_lesson("answers", params, body) == [
            (None, "missing folded answer callout")
        ]

    def test_validate_bad_regex(self) -> None:
        result = KINDS["answers"].validate({"prefix": "> x", "label": "("})
        assert result is not None
        assert result.startswith("bad regex")


class TestKindRegistry:
    def test_optional_prose_skip(self) -> None:
        assert "prose_skip" in KINDS["per_concept"].optional

    def test_new_kinds_present(self) -> None:
        expected = {
            "per_concept",
            "section_shape",
            "size",
            "require_pattern",
            "forbid_pattern",
            "figures",
            "links",
            "vault_links",
        }
        assert expected <= set(KINDS)
