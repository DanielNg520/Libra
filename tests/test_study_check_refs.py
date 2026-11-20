"""Tests for the C2 pattern and reference kinds (`study/check_refs.py`)."""

from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from libra.study.check_kinds import KINDS, parse_lesson
from libra.study.check_refs import lesson_base

FRONTMATTER = "---\ntags:\n  - topic/probability\n---\n"


def _run(
    kind: str,
    params: Mapping[str, object],
    lines: Sequence[str],
    vault: Path | None,
    rel: str = "Self study/Probability/02 x.md",
) -> list[tuple[int | None, str]]:
    text = FRONTMATTER + "\n".join(lines)
    lesson = parse_lesson(text, rel)
    return KINDS[kind].check(lesson, params, vault)


def _write(vault: Path, rel: str, text: str = "x") -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _validate(kind: str, params: Mapping[str, object]) -> str | None:
    return KINDS[kind].validate(params)


def test_lesson_base():
    assert lesson_base("Self study/Coding Practice/Python/lessons/01 x.md") == PurePosixPath(
        "Self study/Coding Practice/Python"
    )
    assert lesson_base("Self study/Probability/02 x.md") == PurePosixPath(
        "Self study/Probability"
    )


class TestRequirePattern:
    def test_practice_present(self):
        lines = ["## Practice", "**★ P1.**"]
        assert _run("require_pattern", {"pattern": r"^\*\*★", "section": "## Practice"}, lines, None) == []

    def test_practice_missing(self):
        lines = ["## Practice"]
        pattern = r"^\*\*★"
        assert _run(
            "require_pattern", {"pattern": pattern, "section": "## Practice"}, lines, None
        ) == [(lines.index("## Practice") + 5, f"pattern missing: {pattern!r}")]

    def test_custom_message(self):
        lines = ["## Practice"]
        assert _run(
            "require_pattern",
            {"pattern": r"^\*\*★", "section": "## Practice", "message": "exam-level: none"},
            lines,
            None,
        ) == [(lines.index("## Practice") + 5, "exam-level: none")]

    def test_section_scoping(self):
        lines = ["## Reading", "**★ idea**", "## Practice", "x"]
        assert _run("require_pattern", {"pattern": r"^\*\*★", "section": "## Practice"}, lines, None) == [
            (lines.index("## Practice") + 5, "pattern missing: '^\\\\*\\\\*★'")
        ]

    def test_masked_line_ignored_for_match(self):
        lines = ["## Practice", "```", "**★ hidden**", "```"]
        assert _run("require_pattern", {"pattern": r"^\*\*★", "section": "## Practice"}, lines, None) == [
            (lines.index("## Practice") + 5, "pattern missing: '^\\\\*\\\\*★'")
        ]

    def test_section_absent(self):
        lines = ["x"]
        assert _run("require_pattern", {"pattern": r"^\*\*★", "section": "## Practice"}, lines, None) == [
            (None, "pattern missing: '^\\\\*\\\\*★'")
        ]

    def test_min_count(self):
        lines = ["x"]
        assert _run("require_pattern", {"pattern": "x", "min": 2}, lines, None) == [
            (None, "pattern missing: 'x' (found 1, need 2)")
        ]

    def test_validate_min(self):
        assert _validate("require_pattern", {"pattern": "x", "min": 0}) == "min must be at least 1"

    def test_validate_regex(self):
        assert _validate("require_pattern", {"pattern": "("}).startswith("bad regex")


class TestForbidPattern:
    PARAMS = {
        "pattern": r"\(pp?\. ?\d+\)|§ ?\d",
        "skip": r"^\*\*(?!(Idea|Worked example)\b)",
        "skip_sections": ["## Sources"],
        "message": "inline cite",
    }

    def test_idea_not_skipped(self):
        line = "**Idea.** see (p. 12)"
        lines = ["## Reading", line]
        assert _run("forbid_pattern", self.PARAMS, lines, None) == [
            (lines.index(line) + 5, "inline cite: '(p. 12)'")
        ]

    def test_problem_label_skipped(self):
        lines = ["**Check: Ross 2.3 (p. 62).** x"]
        assert _run("forbid_pattern", self.PARAMS, lines, None) == []

    def test_skipped_section(self):
        lines = ["## Sources", "- Ross §2.2"]
        assert _run("forbid_pattern", self.PARAMS, lines, None) == []

    def test_fenced_line_ignored(self):
        lines = ["```", "(p. 3)", "```"]
        assert _run("forbid_pattern", self.PARAMS, lines, None) == []

    def test_two_matches_same_line(self):
        line = "a (p. 1) b §3"
        lines = [line]
        assert _run("forbid_pattern", self.PARAMS, lines, None) == [
            (lines.index(line) + 5, "inline cite: '(p. 1)'"),
            (lines.index(line) + 5, "inline cite: '§3'"),
        ]

    def test_default_prefix(self):
        line = "x"
        lines = [line]
        assert _run("forbid_pattern", {"pattern": "x"}, lines, None) == [
            (lines.index(line) + 5, "forbidden pattern: 'x'")
        ]

    def test_section_scoping(self):
        lines = ["## Reading", "x", "## Practice"]
        assert _run("forbid_pattern", {"pattern": "x", "section": "## Practice"}, lines, None) == []

    def test_validate_skip_regex(self):
        assert _validate("forbid_pattern", {"pattern": "x", "skip": "("}).startswith("bad regex")


class TestFigures:
    REL = "Self study/Probability/02 x.md"

    def test_present(self, tmp_path):
        lines = ["![[figures/a.png]]"]
        _write(tmp_path, "Self study/Probability/figures/a.png")
        assert _run("figures", {"max": 1}, lines, tmp_path, rel=self.REL) == []

    def test_missing(self, tmp_path):
        line = "![[figures/a.png]]"
        lines = [line]
        assert _run("figures", {"max": 1}, lines, tmp_path, rel=self.REL) == [
            (lines.index(line) + 5, "figures: image missing 'figures/a.png'")
        ]

    def test_over_max(self, tmp_path):
        lines = ["![[figures/a.png]]", "![[figures/b.png]]"]
        _write(tmp_path, "Self study/Probability/figures/a.png")
        _write(tmp_path, "Self study/Probability/figures/b.png")
        assert _run("figures", {"max": 1}, lines, tmp_path, rel=self.REL) == [
            (None, "figures: 2 images, max 1")
        ]

    def test_outside_folder(self, tmp_path):
        line = "![[../x.png]]"
        lines = [line]
        assert _run("figures", {"max": 1}, lines, tmp_path, rel=self.REL) == [
            (lines.index(line) + 5, "figures: image outside the lesson folder '../x.png'")
        ]

    def test_concept_note_not_image(self, tmp_path):
        lines = ["![[Self study/Probability/concepts/A|A]]"]
        assert _run("figures", {"max": 1}, lines, tmp_path, rel=self.REL) == []

    def test_markdown_image(self, tmp_path):
        line = "![alt](b.png)"
        lines = [line]
        _write(tmp_path, "Self study/Probability/b.png")
        assert _run("figures", {"max": 1}, lines, tmp_path, rel=self.REL) == []

    def test_markdown_external_skipped(self, tmp_path):
        lines = ["![alt](https://e.com/c.png)"]
        assert _run("figures", {"max": 1}, lines, tmp_path, rel=self.REL) == []

    def test_validate_max(self):
        assert _validate("figures", {"max": -1}) == "max must not be negative"


class TestLinks:
    REL = "Self study/Probability/02 x.md"

    def test_path_qualified_alias(self, tmp_path):
        lines = ["[[Self study/Probability/01 outline|PR outline]]"]
        _write(tmp_path, "Self study/Probability/01 outline.md")
        assert _run("links", {}, lines, tmp_path, rel=self.REL) == []

    def test_not_path_qualified(self, tmp_path):
        line = "[[01 outline|PR outline]]"
        lines = [line]
        _write(tmp_path, "Self study/Probability/01 outline.md")
        assert _run("links", {}, lines, tmp_path, rel=self.REL) == [
            (lines.index(line) + 5, "links: not path-qualified '01 outline'")
        ]

    def test_no_alias(self, tmp_path):
        line = "[[Self study/Probability/01 outline]]"
        lines = [line]
        _write(tmp_path, "Self study/Probability/01 outline.md")
        assert _run("links", {}, lines, tmp_path, rel=self.REL) == [
            (lines.index(line) + 5, "links: no alias 'Self study/Probability/01 outline'")
        ]

    def test_target_missing(self, tmp_path):
        line = "[[Self study/Probability/missing|m]]"
        lines = [line]
        assert _run("links", {}, lines, tmp_path, rel=self.REL) == [
            (lines.index(line) + 5, "links: target missing 'Self study/Probability/missing'")
        ]

    def test_target_outside_vault(self, tmp_path):
        line = "[[Self study/../x|x]]"
        lines = [line]
        assert _run("links", {}, lines, tmp_path, rel=self.REL) == [
            (lines.index(line) + 5, "links: target outside the vault 'Self study/../x'")
        ]

    def test_escaped_table_pipe(self, tmp_path):
        lines = ["| [[Self study/Probability/01 outline\\|PR]] |"]
        _write(tmp_path, "Self study/Probability/01 outline.md")
        assert _run("links", {}, lines, tmp_path, rel=self.REL) == []

    def test_anchor_dropped(self, tmp_path):
        lines = ["[[Self study/Probability/01 outline#Part|p]]"]
        _write(tmp_path, "Self study/Probability/01 outline.md")
        assert _run("links", {}, lines, tmp_path, rel=self.REL) == []

    def test_image_not_link(self, tmp_path):
        lines = ["![[figures/a.png]]"]
        assert _run("links", {}, lines, tmp_path, rel=self.REL) == []

    def test_section_ref_exists(self, tmp_path):
        params = {"section_ref": r"(?<![0-9][a-z] )(?<![0-9] )\b[Ss]ection (\d+)\b"}
        lines = ["## Reading", "### 1. A", "### 2. B", "see section 2"]
        assert _run("links", params, lines, tmp_path, rel=self.REL) == []

    def test_section_ref_missing(self, tmp_path):
        params = {"section_ref": r"(?<![0-9][a-z] )(?<![0-9] )\b[Ss]ection (\d+)\b"}
        line = "see section 3"
        lines = ["## Reading", "### 1. A", "### 2. B", line]
        assert _run("links", params, lines, tmp_path, rel=self.REL) == [
            (lines.index(line) + 5, "links: section 3 does not exist (2 concepts)")
        ]

    def test_section_ref_cross_lesson_skipped(self, tmp_path):
        params = {"section_ref": r"(?<![0-9][a-z] )(?<![0-9] )\b[Ss]ection (\d+)\b"}
        lines = ["### 1. A", "PR 02a section 9"]
        assert _run("links", params, lines, tmp_path, rel=self.REL) == []

    def test_validate_section_ref_group(self):
        assert _validate("links", {"section_ref": r"section \d+"}) == "section_ref needs one group"

    def test_validate_section_ref_regex(self):
        assert _validate("links", {"section_ref": "("}).startswith("bad regex")


class TestVaultLinks:
    REL = "Self study/Coding Practice/Python/lessons/01 x.md"

    def test_outline_row(self, tmp_path):
        lines = []
        _write(
            tmp_path,
            "Self study/Coding Practice/Python/01 outline.md",
            "| [[Self study/Coding Practice/Python/lessons/01 x\\|01 x]] | topic |",
        )
        assert _run("vault_links", {"target": "outline"}, lines, tmp_path, rel=self.REL) == []

    def test_outline_non_table(self, tmp_path):
        lines = []
        _write(
            tmp_path,
            "Self study/Coding Practice/Python/01 outline.md",
            "[[Self study/Coding Practice/Python/lessons/01 x|01 x]]",
        )
        assert _run("vault_links", {"target": "outline"}, lines, tmp_path, rel=self.REL) == [
            (None, "vault_links: no outline row links the lesson")
        ]

    def test_outline_missing(self, tmp_path):
        lines = []
        assert _run("vault_links", {"target": "outline"}, lines, tmp_path, rel=self.REL) == [
            (None, "vault_links: outline missing Self study/Coding Practice/Python/01 outline.md")
        ]

    def test_outline_custom(self, tmp_path):
        lines = []
        _write(
            tmp_path,
            "Self study/Coding Practice/Python/02 plan.md",
            "| [[Self study/Coding Practice/Python/lessons/01 x\\|01 x]] | topic |",
        )
        assert _run(
            "vault_links", {"target": "outline", "outline": "02 plan.md"}, lines, tmp_path, rel=self.REL
        ) == []

    def test_outline_unreadable(self, tmp_path):
        lines = []
        path = _write(tmp_path, "Self study/Coding Practice/Python/01 outline.md")
        path.write_bytes(b"\xff\xfe bad")
        assert _run("vault_links", {"target": "outline"}, lines, tmp_path, rel=self.REL) == [
            (None, "vault_links: cannot read outline Self study/Coding Practice/Python/01 outline.md")
        ]

    def test_plan_unreadable_reported(self, tmp_path):
        lines = []
        path = _write(tmp_path, "Self study/Current.md")
        path.write_bytes(b"\xff\xfe bad")
        assert _run("vault_links", {"target": "plan"}, lines, tmp_path, rel=self.REL) == [
            (None, "vault_links: cannot read plan file Self study/Current.md")
        ]
        _write(
            tmp_path,
            "Self study/Master index.md",
            "- [ ] PY: [[Self study/Coding Practice/Python/lessons/01 x|PY 01]]",
        )
        assert _run("vault_links", {"target": "plan"}, lines, tmp_path, rel=self.REL) == []

    def test_plan_current_row(self, tmp_path):
        lines = []
        _write(
            tmp_path,
            "Self study/Current.md",
            "- [ ] PY: [[Self study/Coding Practice/Python/lessons/01 x|PY 01]]",
        )
        assert _run("vault_links", {"target": "plan"}, lines, tmp_path, rel=self.REL) == []

    def test_plan_master_index_row(self, tmp_path):
        lines = []
        _write(
            tmp_path,
            "Self study/Master index.md",
            "- [ ] PY: [[Self study/Coding Practice/Python/lessons/01 x|PY 01]]",
        )
        assert _run("vault_links", {"target": "plan"}, lines, tmp_path, rel=self.REL) == []

    def test_plan_other_lesson(self, tmp_path):
        lines = []
        _write(
            tmp_path,
            "Self study/Current.md",
            "- [ ] PY: [[Self study/Coding Practice/Python/lessons/01 xy|PY 01]]",
        )
        assert _run("vault_links", {"target": "plan"}, lines, tmp_path, rel=self.REL) == [
            (None, "vault_links: no plan file links the lesson")
        ]

    def test_plan_missing(self, tmp_path):
        lines = []
        assert _run("vault_links", {"target": "plan"}, lines, tmp_path, rel=self.REL) == [
            (None, "vault_links: no plan file links the lesson")
        ]

    def test_plan_custom_files(self, tmp_path):
        lines = []
        _write(
            tmp_path,
            "Plans/now.md",
            "- [ ] PY: [[Self study/Coding Practice/Python/lessons/01 x|PY 01]]",
        )
        assert _run(
            "vault_links",
            {"target": "plan", "files": ["Plans/now.md"]},
            lines,
            tmp_path,
            rel=self.REL,
        ) == []

    def test_validate_target(self):
        assert _validate("vault_links", {"target": "x"}) == "target must be 'outline' or 'plan', not 'x'"
