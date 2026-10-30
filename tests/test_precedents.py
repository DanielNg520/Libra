import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from libra import cli, precedents

VAULT = "vault"
COURSE = "ECE 108"


def _write_reading(vault: Path, rel: str, kind: str = "reading", pages: int = 1, text: str = "word") -> None:
    """Write an exported reading file at Tools/readings/<rel>.md."""
    src = Path(rel)
    out = vault / "Tools" / "readings" / f"{src}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {rel}", f"Kind: {kind}", ""]
    for n in range(1, pages + 1):
        lines += [f"### Page {n}", "", text, ""]
    out.write_text("\n".join(lines))


def _write_transcript(vault: Path, rel: str, segments: list[dict]) -> None:
    out = vault / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(segments))


class PrecedentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name) / VAULT
        (self.vault / COURSE / "Transcripts").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _cli(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--root", str(self.vault), "precedents", *args])
        return code, out.getvalue(), err.getvalue()

    def _course_arg(self, course: str = COURSE) -> list[str]:
        return ["--course", course]

    def _make_reading(self, rel: str, text: str = "alpha", pages: int = 1, kind: str = "reading") -> None:
        _write_reading(self.vault, rel, kind=kind, pages=pages, text=text)

    def _make_source(self, rel: str) -> None:
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")

    def _make_transcript(self, filename: str, text: str = "alpha") -> None:
        _write_transcript(
            self.vault,
            f"{COURSE}/Transcripts/{filename}",
            [{"start": 0.0, "end": 2.0, "text": text}],
        )

    # --- public helpers -------------------------------------------------

    def test_is_solution_name(self) -> None:
        self.assertTrue(precedents.is_solution_name("ECE_158A_HW1_sol.pdf"))
        self.assertTrue(precedents.is_solution_name("Solutions.pdf"))
        self.assertTrue(precedents.is_solution_name("hw2-key.pdf"))
        self.assertTrue(precedents.is_solution_name("HW3 Answers.pdf"))
        self.assertFalse(precedents.is_solution_name("PS2_submission.pdf"))
        self.assertFalse(precedents.is_solution_name("hw1.pdf"))
        self.assertFalse(precedents.is_solution_name("keyboard.pdf"))
        self.assertFalse(precedents.is_solution_name("Solver.pdf"))

    def test_tier_of(self) -> None:
        self.assertEqual(precedents.tier_of("C/Homework/HW1_sol.pdf"), "solutions")
        self.assertIsNone(precedents.tier_of("C/Homework/HW1.pdf"))
        self.assertEqual(precedents.tier_of("C/Discussion/d.pdf"), "discussion")
        self.assertEqual(precedents.tier_of("C/Slides/l.pdf"), "lectures")
        self.assertIsNone(precedents.tier_of("C/Textbooks/b.pdf"))
        self.assertIsNone(precedents.tier_of("C/Readings/p.pdf"))
        self.assertIsNone(precedents.tier_of("C"))

    # --- text-mode integration ------------------------------------------

    def test_tier_order_and_membership(self) -> None:
        c = COURSE
        self._make_reading(f"{c}/Homework/HW1_sol.pdf", "alpha")
        self._make_reading(f"{c}/Homework/PS1.pdf", "alpha")
        self._make_reading(f"{c}/Homework/PS2_submission.pdf", "alpha")
        self._make_reading(f"{c}/Discussion/week1.pdf", "alpha")
        self._make_reading(f"{c}/Slides/lecture1.pdf", "alpha")
        self._make_reading(f"{c}/Textbooks/book.pdf", "alpha", kind="textbook")
        self._make_reading(f"{c}/Readings/paper.pdf", "alpha")
        self._make_transcript("2024-01-01.json", "alpha")
        self._make_transcript("2024-01-02-DI.json", "alpha")

        code, out, err = self._cli(*self._course_arg(), "alpha")
        self.assertEqual(code, 0, err)

        h1 = out.index("## 1 Solutions")
        h2 = out.index("## 2 Discussion")
        h3 = out.index("## 3 Lectures")
        self.assertLess(h1, h2)
        self.assertLess(h2, h3)

        self.assertIn(f"{c} · {c}/Homework/HW1_sol.pdf · p.1", out[h1:h2])
        self.assertIn(f"{c} · {c}/Discussion/week1.pdf · p.1", out[h2:h3])
        self.assertIn(f"{c} · 2024-01-02 (discussion) · [00:00]", out[h2:h3])
        self.assertIn(f"{c} · {c}/Slides/lecture1.pdf · p.1", out[h3:])
        self.assertIn(f"{c} · 2024-01-01 · [00:00]", out[h3:])

        self.assertNotIn("PS1.pdf", out)
        self.assertNotIn("PS2_submission.pdf", out)
        self.assertNotIn("Textbooks/book.pdf", out)
        self.assertNotIn("Readings/paper.pdf", out)

    def test_unsearched_sources(self) -> None:
        c = COURSE
        self._make_source(f"{c}/Homework/HW2_sol.pdf")
        self._make_source(f"{c}/Discussion/image.png")
        self._make_source(f"{c}/Homework/PS1.pdf")
        self._make_source(f"{c}/Slides/Outdated/old.pdf")
        self._make_source(f"{c}/Homework/HW1_sol.pdf")
        self._make_source(f"{c}/Slides/current.pdf")
        self._make_reading(f"{c}/Homework/HW1_sol.pdf", "alpha")
        self._make_reading(f"{c}/Slides/current.pdf", "alpha")

        code, out, err = self._cli(*self._course_arg(), "alpha")
        self.assertEqual(code, 0, err)
        self.assertIn(f"unsearched, read directly: {c}/Homework/HW2_sol.pdf", out)
        self.assertIn(f"unsearched, read directly: {c}/Discussion/image.png", out)

        self.assertNotIn(f"unsearched, read directly: {c}/Homework/PS1.pdf", out)
        self.assertNotIn(f"unsearched, read directly: {c}/Slides/Outdated/old.pdf", out)
        self.assertNotIn(f"unsearched, read directly: {c}/Homework/HW1_sol.pdf", out)
        self.assertNotIn(f"unsearched, read directly: {c}/Slides/current.pdf", out)

    def test_empty_packet(self) -> None:
        self._make_reading(f"{COURSE}/Homework/HW1_sol.pdf", "alpha")

        code, out, err = self._cli(*self._course_arg(), "zzz")
        self.assertEqual(code, 1)
        self.assertIn("no precedent found", err)
        self.assertEqual(out.count("none found"), 3)

    def test_any_vs_all(self) -> None:
        self._make_reading(f"{COURSE}/Homework/HW1_sol.pdf", "alpha")
        self._make_transcript("2024-01-01.json", "alpha")

        code_any, out_any, _ = self._cli(*self._course_arg(), "alpha", "beta")
        self.assertEqual(code_any, 0)
        self.assertIn("HW1_sol.pdf", out_any)
        self.assertIn("· [00:00]", out_any)

        code_all, out_all, err_all = self._cli(*self._course_arg(), "--all", "alpha", "beta")
        self.assertEqual(code_all, 1)
        self.assertIn("no precedent found", err_all)
        self.assertNotIn("HW1_sol.pdf", out_all)
        self.assertNotIn("· [00:00]", out_all)

    def test_limit_header_and_output(self) -> None:
        self._make_reading(f"{COURSE}/Homework/HW1_sol.pdf", "alpha")
        self._make_reading(f"{COURSE}/Homework/HW2_sol.pdf", "alpha")

        code, out, err = self._cli(*self._course_arg(), "--limit", "1", "alpha")
        self.assertEqual(code, 0, err)
        self.assertIn("(1 of 2)", out)
        self.assertIn("HW1_sol.pdf", out)
        self.assertNotIn("HW2_sol.pdf", out)

    # --- json mode -------------------------------------------------------

    def test_json_mode(self) -> None:
        c = COURSE
        self._make_reading(f"{c}/Homework/HW1_sol.pdf", "alpha")
        self._make_source(f"{c}/Discussion/image.png")
        self._make_transcript("2024-01-01.json", "alpha")

        code, out, err = self._cli(*self._course_arg("ece108"), "--json", "alpha")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["course"], c)
        self.assertEqual(data["terms"], ["alpha"])

        tiers = data["tiers"]
        self.assertEqual([t["rank"] for t in tiers], [1, 2, 3])
        self.assertEqual([t["tier"] for t in tiers], ["solutions", "discussion", "lectures"])

        self.assertEqual(tiers[0]["total"], 1)
        self.assertEqual(len(tiers[0]["hits"]), 1)
        self.assertEqual(tiers[0]["unsearched"], [])

        self.assertEqual(tiers[1]["total"], 0)
        self.assertEqual(len(tiers[1]["hits"]), 0)
        self.assertEqual(tiers[1]["unsearched"], [f"{c}/Discussion/image.png"])

        self.assertEqual(tiers[2]["total"], 1)
        self.assertEqual(len(tiers[2]["hits"]), 1)
        self.assertEqual(tiers[2]["unsearched"], [])

    # --- error paths -----------------------------------------------------

    def test_unknown_course(self) -> None:
        code, _, err = self._cli("--course", "NOPE 900", "alpha")
        self.assertEqual(code, 2)
        self.assertIn("unknown course", err)

    def test_empty_query_star(self) -> None:
        code, _, err = self._cli(*self._course_arg(), "*")
        self.assertEqual(code, 2)
        self.assertIn("error: empty query", err)
