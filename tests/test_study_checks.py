"""Tests for libra.study.checks, libra.study.check_kinds and `libra study check`."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from libra import cli
from libra.study.commands import cmd_study_check
from libra.study.check_kinds import KINDS, param_ok
from libra.study.checks import (
    RULES_RELPATH,
    Failure,
    RuleFileError,
    check_text,
    lesson_paths,
    load_rules,
    parse_rules,
)

FIXTURE = Path(__file__).parent / "fixtures" / "lesson_rules.toml"

VALID = """---
tags:
  - topic/probability
prereqs:
  - "[[Self study/Probability/01 outline|PR outline]]"
---

## Reading
Bayes rule.
> [!success]- Answer
> P(A|B) = P(B|A)P(A)/P(B)

## Practice
Ross ch. 3 problem 1.

## Recall
1. State Bayes rule.
2. Define independence.
3. What is the chain rule?

## Sources
- Ross, A First Course in Probability, §3.3
"""

MINI = """exclude = ["*/skip.md"]

[[select]]
glob = "a/*.md"
profile = "child"

[[select]]
glob = "*.md"
profile = "base"

[profiles.base]

[profiles.mid]
extends = "base"

[profiles.mid.overrides.count]
max = 4

[profiles.child]
extends = "mid"

[profiles.child.overrides.count]
max = 6

[rules.count]
text = "Count rule."
kind = "list_count"
profiles = ["base"]
section = "## Recall"
min = 1
max = 2

[rules.head]
text = "Head rule."
kind = "heading_order"
profiles = ["child"]
headings = ["## Reading"]

[rules.off]
text = "Off rule."
kind = "heading_order"
profiles = ["base"]
headings = ["## X"]
enabled = false

[rules.note]
text = "Note rule."
kind = "manual"
profiles = ["base"]
planned_kind = "size"
"""


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / RULES_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE, vault / RULES_RELPATH)
    _write(vault, "Self study/Probability/01 outline.md", "# outline\n")
    return vault


def _write(vault: Path, rel: str, text: str) -> Path:
    target = vault / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


def test_fixture_parses() -> None:
    ruleset = parse_rules(FIXTURE.read_text())
    assert len(ruleset.rules) == 32
    expected_profiles = {
        "lesson",
        "topic",
        "code",
        "code_c",
        "code_python",
        "concept",
        "concept_topic",
        "concept_code",
    }
    assert set(ruleset.profiles) == expected_profiles
    for rule in ruleset.rules:
        assert rule.kind in KINDS


def test_fixture_profile_for() -> None:
    ruleset = parse_rules(FIXTURE.read_text())
    cases = {
        "Self study/Probability/02a events and axioms.md": "topic",
        "Self study/Probability/concepts/De Morgan's laws.md": "concept_topic",
        "Coding Practice/Python/concepts/Lists.md": "concept_code",
        "Coding Practice/Bare Metal C/lessons/01 macros.md": "code_c",
        "Coding Practice/Python/lessons/01 types.md": "code_python",
        "Self study/Probability/00 source map.md": None,
        "Self study/Probability/01 outline.md": None,
        "Self study/Weekly/2026/2026-11-09.md": None,
        "Self study/00 index.md": None,
    }
    for rel, expected in cases.items():
        assert ruleset.profile_for(rel) == expected


def test_fixture_rules_by_profile() -> None:
    ruleset = parse_rules(FIXTURE.read_text())
    assert "code-pairs" in {r.id for r in ruleset.rules_for("code_c")}
    assert "code-pairs" not in {r.id for r in ruleset.rules_for("topic")}
    assert "exam-level" in {r.id for r in ruleset.rules_for("topic")}
    assert "exam-level" not in {r.id for r in ruleset.rules_for("code_python")}
    assert "headings" not in {r.id for r in ruleset.rules_for("concept_topic")}
    assert "concept-sources" in {r.id for r in ruleset.rules_for("concept_topic")}


def test_mini_engine() -> None:
    ruleset = parse_rules(MINI)
    child_count = next(r for r in ruleset.rules_for("child") if r.id == "count")
    mid_count = next(r for r in ruleset.rules_for("mid") if r.id == "count")
    base_count = next(r for r in ruleset.rules_for("base") if r.id == "count")
    assert child_count.params["max"] == 6
    assert mid_count.params["max"] == 4
    assert base_count.params["max"] == 2
    child_ids = {r.id for r in ruleset.rules_for("child")}
    mid_ids = {r.id for r in ruleset.rules_for("mid")}
    base_ids = {r.id for r in ruleset.rules_for("base")}
    assert "head" in child_ids
    assert "head" not in mid_ids
    assert "head" not in base_ids
    assert "off" not in child_ids | mid_ids | base_ids
    manual = ruleset.manual_rules("base")
    assert [r.id for r in manual] == ["note"]
    assert manual[0].planned_kind == "size"
    assert ruleset.profile_for("a/skip.md") is None
    assert ruleset.profile_for("a/x.md") == "child"
    assert ruleset.profile_for("b.md") == "base"
    with pytest.raises(RuleFileError):
        ruleset.rules_for("nope")


@pytest.mark.parametrize(
    "bad_text",
    [
        pytest.param(MINI.replace('kind = "list_count"', 'kind = "lst_count"'), id="unknown-kind"),
        pytest.param(
            MINI.replace('section = "## Recall"\nmin = 1', 'section = "## Recall"\nextra = 1\nmin = 1'),
            id="unknown-param",
        ),
        pytest.param(MINI.replace("min = 1", 'min = "1"'), id="wrong-type"),
        pytest.param(MINI.replace("min = 1", "min = 9"), id="min-gt-max"),
        pytest.param(MINI.replace('headings = ["## Reading"]', 'headings = ["## Reading"]\nplanned_kind = "size"'), id="planned-kind-on-non-manual"),
        pytest.param(MINI.replace('profiles = ["base"]', 'profiles = ["ghost"]'), id="profile-undefined"),
        pytest.param(MINI.replace('extends = "mid"', 'extends = "child"'), id="extends-cycle"),
        pytest.param('nope = 1\n' + MINI, id="unknown-top-key"),
        pytest.param(MINI.replace("[profiles.mid.overrides.count]", "[profiles.mid.overrides.ghost]"), id="override-unknown-rule"),
        pytest.param(MINI.replace("[profiles.mid.overrides.count]\nmax = 4", "[profiles.mid.overrides.count]\nextra = 4"), id="override-unknown-param"),
        pytest.param(MINI + "\n[[rules\n", id="invalid-toml"),
        pytest.param(MINI.replace('profile = "child"', 'profile = "ghost"'), id="select-profile-undefined"),
        pytest.param(MINI.replace('profiles = ["base"]', "profiles = []"), id="empty-profiles"),
    ],
)
def test_parse_rules_raises(bad_text: str) -> None:
    with pytest.raises(RuleFileError):
        parse_rules(bad_text)


def test_load_rules_missing_file(tmp_path: Path) -> None:
    vault = tmp_path / "empty_vault"
    vault.mkdir()
    with pytest.raises(RuleFileError, match="rule file missing"):
        load_rules(vault)


def test_valid_lesson_passes(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    ruleset = load_rules(vault)
    _write(vault, "Self study/Probability/02 events.md", VALID)
    failures = check_text(VALID, "Self study/Probability/02 events.md", vault, ruleset.rules_for("topic"))
    assert failures == []


@pytest.mark.parametrize(
    ("mutate", "rule_id", "message_fragment"),
    [
        pytest.param(lambda t: t.replace("## Practice\n", ""), "headings", "heading missing: ## Practice", id="missing-practice"),
        pytest.param(lambda t: t.replace("- topic/probability", "- topic/probability\n  - topic/xyz"), "tags", "unknown tag", id="unknown-tag"),
        pytest.param(lambda t: t.replace("- topic/probability", "- topic/dsp"), "tags", "missing required tag topic/probability", id="missing-required-tag"),
        pytest.param(lambda t: t.replace("01 outline", "99 missing"), "prereqs", "target missing", id="bad-prereq-target"),
        pytest.param(lambda t: t.replace("> [!success]- Answer\n> P(A|B) = P(B|A)P(A)/P(B)\n", ""), "answers-folded", "missing folded answer callout", id="missing-callout"),
        pytest.param(lambda t: t.replace("3. What is the chain rule?\n", ""), "recall-count", "found 2", id="recall-too-short"),
        pytest.param(lambda t: t.replace("- Ross, A First Course in Probability, §3.3\n", ""), "sources", "empty list", id="sources-empty"),
        pytest.param(lambda t: t.replace("- Ross, A First Course in Probability, §3.3", "- Ross, A First Course in Probability"), "sources", "lacks a citation", id="sources-no-cite"),
        pytest.param(lambda t: t.replace("\n## Sources\n- Ross, A First Course in Probability, §3.3\n", "").replace("## Recall\n", "## Sources\n- Ross §3.3\n\n## Recall\n"), "sources", "heading missing: ## Sources", id="sources-before-recall"),
    ],
)
def test_valid_mutations(tmp_path: Path, mutate: Callable[[str], str], rule_id: str, message_fragment: str) -> None:
    vault = _vault(tmp_path)
    ruleset = load_rules(vault)
    text = mutate(VALID)
    _write(vault, "Self study/Probability/02 events.md", text)
    failures = check_text(text, "Self study/Probability/02 events.md", vault, ruleset.rules_for("topic"))
    matching = [f for f in failures if f.rule == rule_id]
    assert matching
    assert message_fragment in matching[0].message


def test_line_numbers(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    ruleset = load_rules(vault)
    text = VALID.replace("3. What is the chain rule?\n", "")
    _write(vault, "Self study/Probability/02 events.md", text)
    failures = check_text(text, "Self study/Probability/02 events.md", vault, ruleset.rules_for("topic"))
    recall_fail = next(f for f in failures if f.rule == "recall-count")
    recall_line = next(i for i, line in enumerate(text.splitlines(), 1) if line.strip() == "## Recall")
    assert recall_fail.line == recall_line

    text = VALID.replace("- Ross, A First Course in Probability, §3.3", "- Ross, A First Course in Probability")
    _write(vault, "Self study/Probability/02 events.md", text)
    failures = check_text(text, "Self study/Probability/02 events.md", vault, ruleset.rules_for("topic"))
    cite_fail = next(f for f in failures if f.rule == "sources")
    entry_line = next(i for i, line in enumerate(text.splitlines(), 1) if line == "- Ross, A First Course in Probability")
    assert cite_fail.line == entry_line


def test_missing_frontmatter(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    ruleset = load_rules(vault)
    text = VALID.split("---", 2)[-1]
    _write(vault, "Self study/Probability/02 events.md", text)
    failures = check_text(text, "Self study/Probability/02 events.md", vault, ruleset.rules_for("topic"))
    assert len(failures) == 1
    assert failures[0].rule == "parse"
    assert failures[0].message.startswith("frontmatter:")


def test_failure_format() -> None:
    assert Failure("recall-count", "a/b.md", 42, "found 2").format() == "recall-count a/b.md:42 found 2"
    assert Failure("parse", "a/b.md", None, "frontmatter: bad").format() == "parse a/b.md frontmatter: bad"


def test_param_ok() -> None:
    assert param_ok("hello", "str")
    assert not param_ok(42, "str")
    assert param_ok(42, "int")
    assert not param_ok(True, "int")
    assert param_ok(["a", "b"], "list[str]")
    assert not param_ok(["a", 1], "list[str]")
    assert param_ok({"a": "b"}, "dict[str,str]")
    assert not param_ok({"a": 1}, "dict[str,str]")


def test_lesson_paths(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    ruleset = load_rules(vault)
    _write(vault, "Self study/Probability/02 events.md", VALID)
    _write(vault, "Self study/Probability/concepts/Bayes.md", VALID)
    paths = lesson_paths(vault, ruleset, ["Self study/Probability"])
    assert paths == [
        "Self study/Probability/02 events.md",
        "Self study/Probability/concepts/Bayes.md",
    ]


def test_cli_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    _write(vault, "Self study/Probability/02 events.md", VALID)
    rc = cmd_study_check(vault, ["Self study/Probability/02 events.md"], False, None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "manual checklist (topic):" in out
    assert "- one-day:" in out
    assert "(planned: size)" in out
    assert "study check: 1 files, 0 failures" in out


def test_cli_main_routes_study_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    rel = "Self study/Probability/02 events.md"
    _write(vault, rel, VALID)
    rc = cli.main(["--root", str(vault), "study", "check", rel])
    assert rc == 0
    assert "study check: 1 files, 0 failures" in capsys.readouterr().out


def test_cli_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    text = VALID.replace("3. What is the chain rule?\n", "")
    _write(vault, "Self study/Probability/02 events.md", text)
    rc = cmd_study_check(vault, ["Self study/Probability/02 events.md"], False, None)
    out = capsys.readouterr().out
    assert rc == 1
    assert "recall-count Self study/Probability/02 events.md:" in out


def test_cli_absolute_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    _write(vault, "Self study/Probability/02 events.md", VALID)
    absolute = str(vault / "Self study/Probability/02 events.md")
    rc = cmd_study_check(vault, [absolute], False, None)
    assert rc == 0


def test_cli_all(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    _write(vault, "Self study/Probability/02 events.md", VALID)
    _write(vault, "Self study/Probability/03 more.md", VALID)
    rc = cmd_study_check(vault, [], True, None)
    out = capsys.readouterr().out
    assert rc == 0
    assert "study check: 2 files, 0 failures" in out


def test_cli_unreadable_lesson(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    _write(vault, "Self study/Probability/02 events.md", VALID)
    bad = _write(vault, "Self study/Probability/03 bad.md", "x")
    bad.write_bytes(b"\xff\xfe bad")
    rc = cmd_study_check(
        vault,
        ["Self study/Probability/03 bad.md", "Self study/Probability/02 events.md"],
        False,
        None,
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "study check: cannot read Self study/Probability/03 bad.md:" in captured.err
    assert "study check: 1 files, 0 failures" in captured.out


def test_cli_usage_rule_file_deleted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    (vault / RULES_RELPATH).unlink()
    rc = cmd_study_check(vault, ["Self study/Probability/01 outline.md"], False, None)
    err = capsys.readouterr().err
    assert rc == 2
    assert "study check:" in err


def test_cli_usage_unknown_profile(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    rc = cmd_study_check(vault, ["Self study/Probability/01 outline.md"], False, "nope")
    assert rc == 2


def test_cli_usage_path_outside(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    (tmp_path / "x.md").write_text(VALID)
    rc = cmd_study_check(vault, ["../x.md"], False, None)
    captured = capsys.readouterr()
    assert rc == 2
    assert "outside the vault" in captured.err


def test_cli_usage_no_profile_match(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    _write(vault, "Self study/00 index.md", VALID)
    rc = cmd_study_check(vault, ["Self study/00 index.md"], False, None)
    assert rc == 2


def test_cli_usage_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    rc = cmd_study_check(vault, ["Self study/Probability/03 none.md"], False, None)
    assert rc == 2


def test_cli_usage_no_targets(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    vault = _vault(tmp_path)
    rc = cmd_study_check(vault, [], False, None)
    assert rc == 2


def test_cli_explicit_profile_on_unmapped_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    _write(vault, "Self study/00 index.md", VALID)
    rc = cmd_study_check(vault, ["Self study/00 index.md"], False, "topic")
    assert rc == 1
    assert "tags: no required tag for this path" in capsys.readouterr().out


def test_cli_notes_do_not_fail(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    rel = "Self study/Probability/02 events.md"
    _write(vault, rel, VALID)
    monkeypatch.setattr(
        "libra.study.commands.check_text",
        lambda *args, **kwargs: [
            Failure(
                "code-runs",
                rel,
                7,
                "code_run: skipped C fragment without main",
                note=True,
            )
        ],
    )
    rc = cmd_study_check(vault, [rel], False, None)
    assert rc == 0
    out = capsys.readouterr().out
    assert (
        "note code-runs Self study/Probability/02 events.md:7 "
        "code_run: skipped C fragment without main" in out
    )
    assert "study check: 1 files, 0 failures, 1 notes" in out



