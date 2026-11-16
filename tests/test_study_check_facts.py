"""Tests for libra.study.check_facts — fact_ledger and cold_read."""
from __future__ import annotations

import json
from pathlib import Path

from libra.study.check_facts import DEFAULT_MARKERS, cold_read_digest, record_relpath
from libra.study.check_kinds import KINDS, parse_lesson

SECTIONS = [r"^\*\*Formulas?\.", r"^\*\*Relationships\."]
PARAMS = {"sections": SECTIONS, "assumed": ["arithmetic"]}

FM_BASE = "---\ntags:\n  - topic/probability\nprereqs: []\n---\n"


def _write(vault: Path, rel: str, text: str) -> str:
    target = vault / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return text


def _ledger(vault: Path, rel: str, text: str, params: dict | None = None) -> list[tuple[int | None, str]]:
    lesson = parse_lesson(_write(vault, rel, text), rel)
    return KINDS["fact_ledger"].check(lesson, params or PARAMS, vault)


def _concept(fact: str, example_uses: str = "none", answer_uses: str = "> Uses: none.") -> str:
    return (
        "---\ntags:\n  - topic/probability\nprereqs: []\n---\n\n"
        "**Formula.**\n"
        f"- **Rule A:** {fact}\n\n"
        "**Worked example.**\n"
        "Task: use it.\n"
        f"- Uses: {example_uses}.\n\n"
        "> [!success]- Answer\n"
        "> Work.\n"
        f"{answer_uses}\n"
    )


def test_clean_concept_note_no_findings(tmp_path: Path) -> None:
    default_marker = DEFAULT_MARKERS[0]
    text = _concept(
        fact=f"{default_marker} right.",
        example_uses="rule a, arithmetic",
        answer_uses="> Uses: none.",
    )
    findings = _ledger(tmp_path, "S/c/A.md", text)
    assert findings == []


def test_unlabelled_use_reported(tmp_path: Path) -> None:
    text = _concept(
        fact="Proof: right.",
        example_uses="rule a, mystery",
        answer_uses="> Uses: mystery.",
    )
    findings = _ledger(tmp_path, "S/c/A.md", text)
    assert any("used but not taught" in m for _, m in findings)


def test_use_before_label_reported(tmp_path: Path) -> None:
    text = (
        "---\ntags:\n  - topic/probability\nprereqs: []\n---\n\n"
        "**Worked example.**\n"
        "Task: use it.\n"
        "- Uses: rule a.\n\n"
        "**Formula.**\n"
        "- **Rule A:** Proof: right.\n\n"
        "> [!success]- Answer\n"
        "> Work.\n"
        "> Uses: none.\n"
    )
    findings = _ledger(tmp_path, "S/c/A.md", text)
    assert any("used before it is labelled" in m for _, m in findings)


def test_missing_uses_reported(tmp_path: Path) -> None:
    example_missing = (
        "---\ntags:\n  - topic/probability\nprereqs: []\n---\n\n"
        "**Formula.**\n"
        "- **Rule A:** Proof: right.\n\n"
        "**Worked example.**\n"
        "Task: use it.\n"
    )
    answer_missing = (
        "---\ntags:\n  - topic/probability\nprereqs: []\n---\n\n"
        "**Formula.**\n"
        "- **Rule A:** Proof: right.\n\n"
        "**Worked example.**\n"
        "Task: use it.\n"
        "- Uses: none.\n\n"
        "> [!success]- Answer\n"
        "> Work.\n"
    )
    assert any("worked example without a final Uses line" in m for _, m in _ledger(tmp_path, "S/c/A.md", example_missing, PARAMS))
    assert any("answer without a final Uses line" in m for _, m in _ledger(tmp_path, "S/c/B.md", answer_missing, PARAMS))


def test_uses_not_last_reported(tmp_path: Path) -> None:
    text = (
        "---\ntags:\n  - topic/probability\nprereqs: []\n---\n\n"
        "**Formula.**\n"
        "- **Rule A:** Proof: right.\n\n"
        "**Worked example.**\n"
        "Task: use it.\n"
        "- Uses: rule a.\n"
        "- step after uses\n\n"
        "> [!success]- Answer\n"
        "> Work.\n"
        "> Uses: none.\n"
    )
    findings = _ledger(tmp_path, "S/c/A.md", text)
    assert any("worked example without a final Uses line" in m for _, m in findings)


def test_uses_none_with_names_reported(tmp_path: Path) -> None:
    text = _concept(
        fact="Proof: right.",
        example_uses="none, rule a",
        answer_uses="> Uses: none.",
    )
    findings = _ledger(tmp_path, "S/c/A.md", text)
    assert any("mixes none with names" in m for _, m in findings)


def test_fact_marker_and_duplicate_label_reported(tmp_path: Path) -> None:
    no_marker = (
        "---\ntags:\n  - topic/probability\nprereqs: []\n---\n\n"
        "**Formula.**\n"
        "- **Rule A:** is true.\n"
    )
    duplicate = (
        "---\ntags:\n  - topic/probability\nprereqs: []\n---\n\n"
        "**Formula.**\n"
        "- **Rule A:** Proof: right.\n"
        "- **Rule A:** Proof: again.\n"
    )
    assert any("has no justification marker" in m for _, m in _ledger(tmp_path, "S/c/A.md", no_marker, PARAMS))
    assert any("labelled twice" in m for _, m in _ledger(tmp_path, "S/c/B.md", duplicate, PARAMS))


def test_fact_under_non_matching_anchor_ignored(tmp_path: Path) -> None:
    text = (
        "---\ntags:\n  - topic/probability\nprereqs: []\n---\n\n"
        "**Check.**\n"
        "- **Rule A:** Proof: right.\n\n"
        "**Worked example.**\n"
        "Task: use it.\n"
        "- Uses: rule a.\n"
    )
    findings = _ledger(tmp_path, "S/c/A.md", text)
    assert any("used but not taught earlier" in m for _, m in findings)


def test_prereq_closure_direct_and_transitive(tmp_path: Path) -> None:
    a = _concept(fact="Proof: alpha.", example_uses="none", answer_uses="> Uses: none.")
    b = (
        "---\ntags:\n  - topic/probability\nprereqs:\n  - \"[[S/c/A|A]]\"\n---\n\n"
        "**Worked example.**\n"
        "Task: use it.\n"
        "- Uses: rule a.\n"
    )
    c = (
        "---\ntags:\n  - topic/probability\nprereqs:\n  - \"[[S/c/B|B]]\"\n---\n\n"
        "**Worked example.**\n"
        "Task: use it.\n"
        "- Uses: rule a.\n\n"
        "> [!success]- Answer\n"
        "> Work.\n"
        "> Uses: none.\n"
    )
    _write(tmp_path, "S/c/A.md", a)
    assert _ledger(tmp_path, "S/c/B.md", b, PARAMS) == []
    _write(tmp_path, "S/c/B.md", b)
    assert _ledger(tmp_path, "S/c/C.md", c, PARAMS) == []


def test_prereq_cycle_terminates_and_resolves(tmp_path: Path) -> None:
    a = (
        "---\ntags:\n  - topic/probability\nprereqs:\n  - \"[[S/c/B|B]]\"\n---\n\n"
        "**Formula.**\n"
        "- **Rule A:** Proof: alpha.\n"
    )
    b = (
        "---\ntags:\n  - topic/probability\nprereqs:\n  - \"[[S/c/A|A]]\"\n---\n\n"
        "**Worked example.**\n"
        "Task: use it.\n"
        "- Uses: rule a.\n"
    )
    _write(tmp_path, "S/c/A.md", a)
    assert _ledger(tmp_path, "S/c/B.md", b, PARAMS) == []


def test_case_insensitive_names(tmp_path: Path) -> None:
    text = _concept(
        fact="Proof: right.",
        example_uses="RULE A",
        answer_uses="> Uses: none.",
    )
    assert _ledger(tmp_path, "S/c/A.md", text) == []


def _lesson(embeds_text: str, prereqs: str = "prereqs: []\n") -> str:
    return (
        "---\ntags:\n  - topic/probability\n"
        f"{prereqs}"
        "---\n\n"
        f"{embeds_text}\n"
        "**Worked example.**\n"
        "Task: use it.\n"
        "- Uses: rule a.\n"
    )


def test_lesson_embed_order(tmp_path: Path) -> None:
    b = (
        "---\ntags:\n  - topic/probability\nprereqs:\n  - \"[[S/c/A|A]]\"\n---\n\n"
        "**Formula.**\n"
        "- **Rule B:** Proof: beta.\n"
    )
    _write(tmp_path, "S/c/B.md", b)
    a = _concept(fact="Proof: alpha.", example_uses="none", answer_uses="> Uses: none.")
    _write(tmp_path, "S/c/A.md", a)
    lesson_b_a = _lesson("![[S/c/B|B]]\n\n![[S/c/A|A]]\n")
    assert any("needs S/c/A.md, not embedded earlier" in m for _, m in _ledger(tmp_path, "Study/L.md", lesson_b_a, PARAMS))
    lesson_a_b = _lesson("![[S/c/A|A]]\n\n![[S/c/B|B]]\n")
    assert all("needs S/c/A.md, not embedded earlier" not in m for _, m in _ledger(tmp_path, "Study/L.md", lesson_a_b, PARAMS))
    lesson_b_only = _lesson(
        "![[S/c/B|B]]\n",
        prereqs='prereqs:\n  - "[[S/c/A|A]]"\n',
    )
    assert all("needs S/c/A.md, not embedded earlier" not in m for _, m in _ledger(tmp_path, "Study/L.md", lesson_b_only, PARAMS))


def test_lesson_answer_resolves_embedded_fact(tmp_path: Path) -> None:
    a = _concept(fact="Proof: alpha.", example_uses="none", answer_uses="> Uses: none.")
    _write(tmp_path, "S/c/A.md", a)
    lesson = _lesson("![[S/c/A|A]]\n")
    assert _ledger(tmp_path, "Study/L.md", lesson, PARAMS) == []


def test_unreadable_dependency_reported(tmp_path: Path) -> None:
    bad = "no frontmatter\njust text\n"
    _write(tmp_path, "S/c/A.md", bad)
    b = (
        "---\ntags:\n  - topic/probability\nprereqs:\n  - \"[[S/c/A|A]]\"\n---\n\n"
        "**Formula.**\n"
        "- **Rule B:** Proof: beta.\n"
    )
    findings = _ledger(tmp_path, "S/c/B.md", b, PARAMS)
    assert any("cannot read" in m for _, m in findings)


def test_validate_params(tmp_path: Path) -> None:
    assert "sections must be a non-empty list" in KINDS["fact_ledger"].validate({})
    assert "bad regex" in KINDS["fact_ledger"].validate({"sections": ["["]})
    assert KINDS["fact_ledger"].validate({"sections": SECTIONS, "markers": []}) is not None
    assert KINDS["fact_ledger"].validate({"sections": SECTIONS}) is None


def test_bold_step_and_quote_inside_example_ok(tmp_path: Path) -> None:
    text = (
        FM_BASE
        + "\n**Formula.**\n"
        + "- **Rule A:** Proof: right.\n"
        + "\n**Worked example.**\n"
        + "**Step 1.** set up.\n"
        + "> a quoted line\n"
        + "**Step 2.** finish.\n"
        + "- Uses: rule a.\n"
    )
    assert _ledger(tmp_path, "ok.md", text) == []


def test_example_stops_at_answer_callout(tmp_path: Path) -> None:
    text = (
        FM_BASE
        + "\n**Formula.**\n"
        + "- **Rule A:** Proof: right.\n"
        + "\n**Worked example.**\n"
        + "Task.\n"
        + "\n> [!success]- Answer\n"
        + "> Work.\n"
        + "> Uses: none.\n"
    )
    findings = _ledger(tmp_path, "callout.md", text)
    messages = [msg for _, msg in findings]
    assert sum("worked example without a final Uses line" in m for m in messages) == 1
    assert all("answer without" not in m for m in messages)


def test_example_stops_at_next_example_and_heading(tmp_path: Path) -> None:
    text = (
        FM_BASE
        + "\n**Worked example.**\n"
        + "Task.\n"
        + "\n**Worked example 2.**\n"
        + "Task.\n"
        + "- Uses: none.\n"
        + "\n## Practice\n"
        + "\n**Worked example 3.**\n"
        + "Task.\n"
        + "\n## Recall\n"
    )
    findings = _ledger(tmp_path, "multi.md", text)
    messages = [msg for _, msg in findings]
    assert sum("worked example without a final Uses line" in m for m in messages) == 2


def test_min_sites_default_and_set(tmp_path: Path) -> None:
    text = (
        FM_BASE
        + "\n**Formula.**\n"
        + "- **Rule A:** Proof: right.\n"
    )
    findings = _ledger(tmp_path, "default.md", text)
    assert all("needs at least" not in msg for _, msg in findings)

    findings = _ledger(tmp_path, "set.md", text, {**PARAMS, "min_sites": 1})
    assert (None, "fact_ledger: 0 worked examples or answers with a Uses line, needs at least 1") in findings

    text_done = (
        FM_BASE
        + "\n**Worked example.**\n"
        + "Task.\n"
        + "- Uses: none.\n"
    )
    findings = _ledger(tmp_path, "done.md", text_done, {**PARAMS, "min_sites": 1})
    assert all("needs at least" not in msg for _, msg in findings)


def test_min_sites_counts_broken_sites(tmp_path: Path) -> None:
    text = (
        FM_BASE
        + "\n**Worked example.**\n"
        + "Task.\n"
    )
    findings = _ledger(tmp_path, "broken.md", text, {**PARAMS, "min_sites": 1})
    messages = [msg for _, msg in findings]
    assert any("worked example without a final Uses line" in m for m in messages)
    assert all("needs at least" not in m for m in messages)


def test_min_sites_in_kind_spec() -> None:
    assert KINDS["fact_ledger"].optional["min_sites"] == "int"


def test_example_does_not_claim_uses_after_callout(tmp_path: Path) -> None:
    text = FM_BASE
    text += "\n**Worked example.**\n"
    text += "Task.\n"
    text += "\n> [!success]- Answer\n"
    text += "> Work.\n"
    text += "> Uses: none.\n"
    text += "\n- Uses: none.\n"
    findings = _ledger(tmp_path, "after.md", text)
    assert any("worked example without a final Uses line" in msg for _, msg in findings)


def test_record_relpath_encoding() -> None:
    assert record_relpath("Tools/cold_reads/", "Self study/P/02a x.md") == "Tools/cold_reads/Self study__P__02a x.json"


def _cold(vault: Path, rel: str, params: dict, text: str = "---\ntags: []\n---\nbody\n") -> list[tuple[int | None, str]]:
    lesson = parse_lesson(_write(vault, rel, text), rel)
    return KINDS["cold_read"].check(lesson, params, vault)


def _params() -> dict:
    return {"dir": "Tools/cold_reads"}


def test_cold_read_missing_record(tmp_path: Path) -> None:
    findings = _cold(tmp_path, "S/c/A.md", _params())
    assert any("no record" in m for _, m in findings)


def test_cold_read_invalid_record_json(tmp_path: Path) -> None:
    rel = "S/c/A.md"
    base = _params()["dir"]
    record = tmp_path / base / "S__c__A.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text("not json", encoding="utf-8")
    assert any("unreadable record" in m for _, m in _cold(tmp_path, rel, _params()))


def test_cold_read_record_not_dict(tmp_path: Path) -> None:
    rel = "S/c/A.md"
    base = _params()["dir"]
    record = tmp_path / base / "S__c__A.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    assert any("unreadable record" in m for _, m in _cold(tmp_path, rel, _params()))


def test_cold_read_wrong_lesson_and_fail(tmp_path: Path) -> None:
    base = _params()["dir"]
    record = tmp_path / base / "S__c__A.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"lesson": "Other.md", "verdict": "pass", "sha256": "x"}), encoding="utf-8")
    assert any("is for another lesson" in m for _, m in _cold(tmp_path, "S/c/A.md", _params()))
    record.write_text(json.dumps({"lesson": "S/c/A.md", "verdict": "fail", "sha256": "x"}), encoding="utf-8")
    assert any("not pass" in m for _, m in _cold(tmp_path, "S/c/A.md", _params()))


def test_cold_read_pass_then_stale_embedded_and_prereq(tmp_path: Path) -> None:
    rel = "S/c/L.md"
    concept = _concept(fact="Proof: alpha.", example_uses="none", answer_uses="> Uses: none.")
    _write(tmp_path, "S/c/A.md", concept)
    prereq = _concept(fact="Proof: beta.", example_uses="none", answer_uses="> Uses: none.")
    _write(tmp_path, "S/c/P.md", prereq)
    lesson_text = (
        "---\ntags:\n  - topic/probability\nprereqs:\n  - \"[[S/c/P|P]]\"\n---\n\n"
        "![[S/c/A|A]]\n\n"
        "**Worked example.**\n"
        "Task: use it.\n"
        "- Uses: rule a.\n"
    )
    lesson = parse_lesson(_write(tmp_path, rel, lesson_text), rel)
    digest = cold_read_digest(tmp_path, rel, lesson_text, lesson.frontmatter)
    base = _params()["dir"]
    record = tmp_path / base / "S__c__L.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"lesson": rel, "verdict": "pass", "sha256": digest}), encoding="utf-8")
    assert _cold(tmp_path, rel, _params(), lesson_text) == []
    _write(tmp_path, "S/c/A.md", concept + "change\n")
    assert any("stale record" in m for _, m in _cold(tmp_path, rel, _params(), lesson_text))
    _write(tmp_path, "S/c/A.md", concept)
    _write(tmp_path, "S/c/P.md", prereq + "change\n")
    assert any("stale record" in m for _, m in _cold(tmp_path, rel, _params(), lesson_text))


def test_cold_read_pass_unrelated_edit_ok(tmp_path: Path) -> None:
    rel = "S/c/L.md"
    lesson_text = "---\ntags: []\n---\nbody\n"
    lesson = parse_lesson(_write(tmp_path, rel, lesson_text), rel)
    digest = cold_read_digest(tmp_path, rel, lesson_text, lesson.frontmatter)
    base = _params()["dir"]
    record = tmp_path / base / "S__c__L.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"lesson": rel, "verdict": "pass", "sha256": digest}), encoding="utf-8")
    _write(tmp_path, "S/other.md", "unrelated\n")
    assert _cold(tmp_path, rel, _params(), lesson_text) == []


def test_cold_read_validate(tmp_path: Path) -> None:
    assert KINDS["cold_read"].validate({"dir": "/abs"}) is not None
    assert KINDS["cold_read"].validate({"dir": "a/../b"}) is not None
    assert KINDS["cold_read"].validate({"dir": "Tools/cold_reads"}) is None
