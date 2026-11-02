# 0001 – Pre-problem notes: foundations, not solutions

**Status:** Accepted 2026-11-01; P0 and P1 done 2026-11-01; P2 dropped; P3 conditional

## Status
Proposed 2026-11-01 (Claude, from the owner's 2026-10-31 test-use findings). Accepted: P1 approved (owner, 2026-11-01).
P0 and P1 done 2026-11-01. P2 dropped: "not necessary" (owner, 2026-11-01). P3 stays conditional on the D7 trigger.

## Context
Source: owner note `Current/Libra_test_use_finding.md` (2026-10-31, ECE 158A HW2 audit); content carried into Hivemind `libra/pre-problem-standard.md`, then the note was deleted (owner, 2026-11-01).
Owner (2026-10-31): `pre-problemN.md` gives the background for a problem, theory to practice step by step; it is not a solution.
Owner (2026-10-31): concepts come before relationships; reread section 1 as a newcomer to the subject.
Owner (2026-10-31): word-problem guides go concept, formula, every component, relationships; solutions open with `Given:` and `Find:`.
Owner (2026-11-01): keep the exam reference card section inside pre-problem notes.
Fact (verified 2026-11-01): vault `AGENTS.md` holds an uncommitted 2026-10-31 diff with the pre-problem policy, the solution standard and the embed protocol.
Fact (verified 2026-11-01): skill `academic-study` names `pre-problemN.md` (line 32) but states no structure or checks.
Fact (verified 2026-11-01): Hivemind `libra/homework-workflow.md` has the solution format only; nothing on pre-problem structure.
Fact (verified 2026-11-01): Libra has no note checker; `textbooks.check_copies` checks textbook copies only, not study notes.
Fact (verified 2026-11-01): 8 pre-problem files exist; 0 hold "Test-Ready Solution"; 4 lack the `![[...]]` embed line; 3 contain em dashes.
Files lacking the wikilink line: ECE 108 HW1 `pre-problem3`, ECE 108 HW2 `pre-problem3`, ECE 271A HW2 `pre-problem1` and `pre-problem3`.
Files with em dashes: ECE 108 HW1 `pre-problem3` (1), ECE 271A HW2 `pre-problem1` (1), `pre-problem3` (2).
ECE 108 HW3 uses `pre-ps3.md`, not `pre-problemN.md`; the rule must cover both names.

## Decision
D1, one home per layer, no new doc: behaviour rule in Hivemind `libra/pre-problem-standard.md`; skill points to it; vault keeps format rules.
D2, seam fix: vault "Direct Answering Policy" and "Answer the exact question first" cover questions and solution files, never pre-problem notes; reword both.
D3, seam fix: vault "Do only what is asked: no extra sections" excepts the pre-problem template below, as it already excepts Further reading.
D4: the reference card is a section of the pre-problem, not a standalone cheat sheet; `study-note-style` says so, no contradiction remains.
D5, template for `pre-problemN.md` and `pre-psN.md`, sections in order:
1. Title and course metadata: course, quarter, professor, textbook, link to the solution file.
2. Context: the real-world setting of the problem; architecture figure where the concept starts.
3. Building blocks: every parameter defined in plain language, with units and its basic equation.
4. Relationships and trade-offs: how the blocks interact; theory such as pooling; practical constraints.
5. Problem statement: the homework prompt as posted.
6. Derivations: step by step from first principles.
7. Connection to the problem: walk its structure with no final answers.
8. Exam traps: common errors and misconceptions.
9. Exam reference card: formulas and terms for quick lookup.
10. Further reading: 3 to 5 checked sources (vault note spec).
D6, done-checklist; mechanical items by grep, the rest by agent reread:
- grep: zero "Test-Ready Solution"; zero em dashes; every `![[x.png]]` line followed by exactly one `![...](figures/x.png)` line.
- grep: every word-problem solution file opens each problem with `Given:` and `Find:`.
- Reread: no symbol before its definition; no problem number before its theory; guide order concept, formula, components, relationships.
- Reread: no narrative; no submission templates, dummy screenshots or mock submissions unless the owner asks.
D7, no code now: the checklist lives in the skill as grep commands. Reuse check: no note checker exists to extend; a new one is unjustified yet.
D7 trigger: if a run in `guide-run-log` shows the grep checklist missed a defect twice, phase 3 builds `libra check-note`.

## Phases
P0, done 2026-11-01: Hivemind memory `pre-problem-standard`, pointers in `MEMORY.md` and `homework-workflow`; this ADR; owner note deleted.
P1, done 2026-11-01 (owner approved): skill `academic-study` gains a "Pre-problem notes" block (template pointer, checklist greps); amend `study-note-style` (D4).
P1, vault `AGENTS.md`: owner reviews and commits the pending 2026-10-31 diff, plus the D2 and D3 rewordings, on Fedora.
P2, dropped (owner, 2026-11-01): no backfill of the 4 files above; they stay as written.
P3, conditional (D7 trigger): `libra check-note <path>`, read-only, exit 1 on a failed grep item; TriAPI dispatch, tests first.

## Consequences
Claude and agy load the same skill by symlink, so P1 reaches both agents on Fedora and Mac in one Hivemind push.
Semantic checks (newcomer test, concept order) stay agent judgment; no grep can verify them.
Older pre-problem files stay non-compliant (P2 dropped); the skill tells agents never to copy their structure.

## Self-review (Claude, 2026-11-01)
Checked: no worker, table, daemon or command added; P3 is gated on evidence.
Checked: grep of vault `AGENTS.md`, the skill and Hivemind `libra/` found the three conflicting lines that D2-D4 resolve.
Unverified: whether ECE 158A HW2 `pre-problem4` and `pre-problem5` pass the newcomer test after the 10-31 refactor; no reread planned (P2 dropped).
