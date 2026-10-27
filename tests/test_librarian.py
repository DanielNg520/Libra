from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

from libra import cli, library


class LibrarianTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._build_fixture()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_json(self, rel_path: str, segments: List[Dict[str, Any]]) -> None:
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(segments), encoding="utf-8")

    def _build_fixture(self) -> None:
        # ECE 108 transcripts
        ece108_lecture = [
            {"start": 0.0, "end": 5.0, "text": "welcome to the course"},
            {"start": 5.0, "end": 10.0, "text": "today we cover logic design"},
            {"start": 10.0, "end": 15.0, "text": "for example consider a gate"},
            {"start": 15.0, "end": 20.0, "text": "quartz alone here"},
            {"start": 20.0, "end": 25.0, "text": "filler segment two"},
            {"start": 25.0, "end": 30.0, "text": "filler segment three"},
            {"start": 30.0, "end": 35.0, "text": "filler segment four"},
            {"start": 35.0, "end": 40.0, "text": "filler segment five"},
            {"start": 40.0, "end": 45.0, "text": "filler segment six"},
            {"start": 45.0, "end": 50.0, "text": "the exam is next week"},
            {"start": 50.0, "end": 55.0, "text": "filler segment seven"},
            {"start": 55.0, "end": 60.0, "text": "filler segment eight"},
            {"start": 60.0, "end": 65.0, "text": "filler segment nine"},
            {"start": 65.0, "end": 70.0, "text": "filler segment ten"},
            {"start": 70.0, "end": 75.0, "text": "filler segment eleven"},
            {"start": 75.0, "end": 80.0, "text": "the word midterm appears here"},
        ]
        self._write_json("ECE 108/Transcripts/2026-10-20.json", ece108_lecture)

        ece108_di = [
            {"start": 0.0, "end": 5.0, "text": "discussion welcomes everyone"},
            {"start": 5.0, "end": 10.0, "text": "we review midterms together"},
            {"start": 10.0, "end": 15.0, "text": "filler alpha"},
            {"start": 15.0, "end": 20.0, "text": "filler beta"},
            {"start": 20.0, "end": 25.0, "text": "zephyr alone here"},
            {"start": 25.0, "end": 30.0, "text": "filler delta"},
            {"start": 30.0, "end": 35.0, "text": "filler epsilon"},
            {"start": 35.0, "end": 40.0, "text": "filler zeta"},
            {"start": 40.0, "end": 45.0, "text": "a boundary segment ends with logical"},
        ]
        self._write_json("ECE 108/Transcripts/2026-10-21-DI.json", ece108_di)

        # ECE 158A transcripts
        ece158a_lecture = [
            {"start": 0.0, "end": 5.0, "text": "opening remarks end with logical"},
            {"start": 5.0, "end": 10.0, "text": "effort is required in this class"},
            {"start": 10.0, "end": 15.0, "text": "filler one hundred"},
            {"start": 15.0, "end": 20.0, "text": "filler one oh one"},
            {"start": 20.0, "end": 25.0, "text": "filler one oh two"},
            {"start": 25.0, "end": 30.0, "text": "filler one oh three"},
            {"start": 30.0, "end": 35.0, "text": "filler one oh four"},
            {"start": 35.0, "end": 40.0, "text": "filler one oh five"},
            {"start": 40.0, "end": 45.0, "text": "the midterm covers everything"},
            {"start": 45.0, "end": 50.0, "text": "adjacent merge test first"},
            {"start": 50.0, "end": 55.0, "text": "adjacent merge test second"},
            {"start": 55.0, "end": 60.0, "text": "filler merge spacer one"},
            {"start": 60.0, "end": 65.0, "text": "filler merge spacer two"},
            {"start": 65.0, "end": 70.0, "text": "filler merge spacer three"},
            {"start": 70.0, "end": 75.0, "text": "filler merge spacer four"},
            {"start": 75.0, "end": 80.0, "text": "filler merge spacer five"},
            {"start": 4925.3, "end": 4930.0, "text": "special label segment at eighty two oh five"},
            {"start": 4930.0, "end": 4935.0, "text": "quartz and zephyr together"},
            {"start": 4935.0, "end": 4940.0, "text": "ranking helper segment two"},
        ]
        self._write_json("ECE 158A/Transcripts/2026-10-22.json", ece158a_lecture)

        invalid_json_path = self.root / "ECE 158A/Transcripts/2026-10-23.json"
        invalid_json_path.parent.mkdir(parents=True, exist_ok=True)
        invalid_json_path.write_text('[{"start": 1,', encoding="utf-8")

        notes_path = self.root / "ECE 158A/Transcripts/notes.txt"
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.write_text("these notes should be ignored", encoding="utf-8")

        personal_dir = self.root / "Personal"
        personal_dir.mkdir(parents=True, exist_ok=True)
        (personal_dir / "misc.txt").write_text("not a course", encoding="utf-8")

    def _run(self, *argv: str, root: Path | None = None) -> Tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["--root", str(root or self.root), *argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def _hit_lines(self, stdout: str) -> List[str]:
        return [line for line in stdout.splitlines() if line.startswith("> ")]

    def test_whole_word_search_excludes_substring(self) -> None:
        code, stdout, _ = self._run("search", "exam")
        self.assertEqual(code, 0)
        hit_lines = self._hit_lines(stdout)
        self.assertTrue(any("the exam is" in line for line in hit_lines))
        self.assertFalse(any("for example" in line for line in hit_lines))

    def test_prefix_star_matches_both_singular_and_plural(self) -> None:
        code, stdout, _ = self._run("search", "midterm*")
        self.assertEqual(code, 0)
        hit_lines = self._hit_lines(stdout)
        self.assertTrue(any("midterm appears" in line for line in hit_lines))
        self.assertTrue(any("midterms together" in line for line in hit_lines))

    def test_phrase_across_segment_boundary(self) -> None:
        code, _, _ = self._run("search", '"logical effort"')
        self.assertEqual(code, 0)
        code, stdout, _ = self._run("search", "--json", '"logical effort"')
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(len(data), 1)
        segments = data[0]["segments"]
        self.assertTrue(any(s["hit"] for s in segments if "logical" in s["text"]))
        self.assertTrue(any(s["hit"] for s in segments if "effort is" in s["text"]))

    def test_and_mode_requires_all_terms_in_window(self) -> None:
        code, stdout, stderr = self._run("search", "midterm", "effort")
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("no matches", stderr)

        code, stdout, _ = self._run("search", "--any", "midterm", "effort")
        self.assertEqual(code, 0)
        hits = json.loads(self._run("search", "--any", "--json", "midterm", "effort")[1])
        self.assertGreaterEqual(len(hits), 2)

    def test_adjacent_segments_merge_into_one_hit(self) -> None:
        code, stdout, _ = self._run("search", "--json", "adjacent")
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["occurrences"], 2)

    def test_ranking_by_terms_matched_then_date(self) -> None:
        code, stdout, _ = self._run("search", "--any", "--json", "quartz", "zephyr")
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(
            [(hit["terms_matched"], hit["date"]) for hit in data],
            [(2, "2026-10-22"), (1, "2026-10-21"), (1, "2026-10-20")],
        )

    def test_since_until_kind_filters(self) -> None:
        # --since excludes earlier dates
        code, stdout, _ = self._run("search", "--since", "2026-10-21", "--json", "midterm*")
        self.assertEqual(code, 0)
        dates = [hit["date"] for hit in json.loads(stdout)]
        self.assertTrue(all(d >= "2026-10-21" for d in dates))

        # --until excludes later dates
        code, stdout, _ = self._run("search", "--until", "2026-10-20", "--json", "midterm*")
        self.assertEqual(code, 0)
        dates = [hit["date"] for hit in json.loads(stdout)]
        self.assertTrue(all(d <= "2026-10-20" for d in dates))

        # --kind discussion returns only the -DI file
        code, stdout, _ = self._run("search", "--kind", "discussion", "midterm*")
        self.assertEqual(code, 0)
        self.assertIn("(discussion)", stdout)
        self.assertNotIn("2026-10-20", stdout)

        # --kind lecture excludes the discussion
        code, stdout, _ = self._run("search", "--kind", "lecture", "midterm*")
        self.assertEqual(code, 0)
        self.assertNotIn("(discussion)", stdout)
        self.assertIn("2026-10-20", stdout)

        # --kind discussion in JSON returns only discussion hits
        code, stdout, _ = self._run("search", "--kind", "discussion", "--json", "midterm*")
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertTrue(data)
        for hit in data:
            self.assertEqual(hit["kind"], "discussion")
            self.assertEqual(hit["date"], "2026-10-21")

    def test_course_matching_variants_and_unknown(self) -> None:
        code, stdout, _ = self._run("search", "--course", "ece108", "--json", "midterm*")
        self.assertEqual(code, 0)
        courses = {hit["course"] for hit in json.loads(stdout)}
        self.assertEqual(courses, {"ECE 108"})

        code, stdout, _ = self._run("search", "--course", "ECE 108", "--json", "midterm*")
        self.assertEqual(code, 0)
        courses = {hit["course"] for hit in json.loads(stdout)}
        self.assertEqual(courses, {"ECE 108"})

        code, _, stderr = self._run("search", "--course", "nope", "midterm")
        self.assertEqual(code, 2)
        self.assertIn("ECE 108", stderr)
        self.assertIn("ECE 158A", stderr)
        self.assertNotIn("Personal", stderr)

    def test_invalid_file_warning_and_notes_ignored(self) -> None:
        code, stdout, stderr = self._run("search", "midterm*")
        self.assertEqual(code, 0)
        warning_lines = [line for line in stderr.splitlines() if "warning: skipping" in line]
        self.assertEqual(len(warning_lines), 1)
        self.assertIn("2026-10-23.json", warning_lines[0])
        self.assertNotIn("notes.txt", stderr)
        self.assertTrue(stdout.strip())

    def test_json_output_shape(self) -> None:
        code, stdout, _ = self._run("search", "--json", "midterm*")
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        for hit in data:
            self.assertEqual(
                set(hit.keys()),
                {
                    "course",
                    "date",
                    "kind",
                    "source",
                    "start",
                    "start_label",
                    "terms_matched",
                    "occurrences",
                    "segments",
                },
            )
            for seg in hit["segments"]:
                self.assertEqual(
                    set(seg.keys()),
                    {"start", "label", "text", "hit"},
                )

    def test_format_ts_and_label_in_header(self) -> None:
        self.assertEqual(library.format_ts(4925.3), "82:05")
        self.assertEqual(library.format_ts(7.9), "00:07")

        code, stdout, _ = self._run("search", "special label segment")
        self.assertEqual(code, 0)
        self.assertIn("[82:05]", stdout)

    def test_no_hits_text_and_json(self) -> None:
        code, stdout, stderr = self._run("search", "zzzznonsense")
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("no matches", stderr)

        code, stdout, stderr = self._run("search", "--json", "zzzznonsense")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout), [])
        self.assertIn("no matches", stderr)

    def test_limit_reports_truncation(self) -> None:
        code, stdout, stderr = self._run("search", "--limit", "1", "midterm*")
        self.assertEqual(code, 0)
        headers = [
            line
            for line in stdout.splitlines()
            if line and not line.startswith("> ") and not line.startswith("  ")
        ]
        self.assertEqual(len(headers), 1)
        self.assertRegex(stderr, r"1 of \d+ hits")

    def test_usage_errors(self) -> None:
        code, _, stderr = self._run("search", "--since", "2026-13-01", "midterm")
        self.assertEqual(code, 2)
        self.assertIn("invalid date", stderr)

        code, _, stderr = self._run("search", "midterm", root=self.root / "nonexistent")
        self.assertEqual(code, 2)
        self.assertIn("root not found", stderr)


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.course1 = self.root / "ECE 108"
        self.course2 = self.root / "ECE 271A"
        (self.course1 / "Transcripts").mkdir(parents=True)
        (self.course1 / "Slides").mkdir()
        (self.course1 / "Readings" / "ECE 25").mkdir(parents=True)
        (self.course1 / "Study notes").mkdir()
        (self.course2 / "Homework").mkdir(parents=True)
        (self.root / "Personal" / "Slides").mkdir(parents=True)
        (self.root / "Study notes" / "Slides").mkdir(parents=True)

        (self.course1 / "Transcripts" / "2026-10-20.json").write_text(json.dumps([
            {"start": 0.0, "end": 5.0, "text": "mic check one two"},
            {"start": 30.0, "end": 35.0, "text": "still testing"},
            {"start": 60.0, "end": 90.0, "text": "Today we cover   logical effort"},
            {"start": 3950.0, "end": 4000.0, "text": "goodbye"},
        ]))
        (self.course1 / "Transcripts" / "2026-10-20-DI.json").write_text(json.dumps([
            {"start": 0.0, "end": 10.0, "text": "discussion opener"},
            {"start": 10.0, "end": 20.0, "text": "more discussion"},
        ]))
        (self.course1 / "Transcripts" / "2026-10-13.json").write_text(json.dumps([
            {"start": 0.0, "end": 10.0, "text": "early lecture"},
        ]))
        (self.course1 / "Transcripts" / "2026-10-15.json").write_text("{not valid json")
        (self.course1 / "Transcripts" / "notes.md").write_text("ignored")
        (self.course1 / "Slides" / "lecture1.pdf").write_bytes(b"x" * 2048)
        (self.course1 / "Slides" / ".hidden.pdf").write_text("hidden")
        (self.course1 / "Slides" / "lecture1.conflict1.pdf").write_text("conflict")
        (self.course1 / "Readings" / "ECE 25" / "deck.pdf").write_text("deck")
        (self.course1 / "Study notes" / "lecture 1.md").write_text("private")
        (self.course1 / "syllabus.pdf").write_bytes(b"y")
        (self.course2 / "Homework" / "hw1.pdf").write_text("hw")
        (self.root / "Personal" / "Slides" / "x.pdf").write_text("personal")
        (self.root / "Study notes" / "Slides" / "y.pdf").write_text("private")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *argv: str) -> Tuple[int, str, str]:
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
            code = cli.main(["--root", str(self.root), *argv])
        return code, captured_out.getvalue(), captured_err.getvalue()

    def test_json_shape_and_course_list(self) -> None:
        code, out, _ = self._run("catalog", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(set(data), {"courses"})
        self.assertEqual([c["course"] for c in data["courses"]], ["ECE 108", "ECE 271A"])

    def test_transcripts(self) -> None:
        code, out, err = self._run("catalog", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        ece108 = next(c for c in data["courses"] if c["course"] == "ECE 108")
        kinds = [(t["date"], t["kind"]) for t in ece108["transcripts"]]
        self.assertEqual(kinds, [
            ("2026-10-13", "lecture"),
            ("2026-10-15", "lecture"),
            ("2026-10-20", "lecture"),
            ("2026-10-20", "discussion"),
        ])
        lecture_20 = ece108["transcripts"][2]
        self.assertEqual(lecture_20["duration"], "66:40")
        self.assertEqual(lecture_20["segments"], 4)
        self.assertTrue(lecture_20["opening"].startswith("Today we cover logical effort"))
        self.assertNotIn("mic check", lecture_20["opening"])
        unreadable = ece108["transcripts"][1]
        self.assertEqual(unreadable["status"], "unreadable")
        self.assertIsNone(unreadable["duration"])
        self.assertIsNone(unreadable["segments"])
        self.assertIsNone(unreadable["opening"])
        self.assertIn("warning:", err)
        ece271a = next(c for c in data["courses"] if c["course"] == "ECE 271A")
        self.assertEqual(ece271a["transcripts"], [])

    def test_folder_entries(self) -> None:
        code, out, _ = self._run("catalog", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        ece108 = next(c for c in data["courses"] if c["course"] == "ECE 108")
        self.assertEqual(list(ece108["folders"]), ["Slides", "Readings"])
        slides = ece108["folders"]["Slides"]
        self.assertEqual([f["path"] for f in slides], ["ECE 108/Slides/lecture1.pdf"])
        self.assertEqual(slides[0]["size_kb"], 2)
        self.assertEqual(ece108["folders"]["Readings"][0]["path"], "ECE 108/Readings/ECE 25/deck.pdf")
        self.assertNotIn("hidden", out)
        self.assertNotIn("conflict", out)
        self.assertNotIn("Study notes", out)
        self.assertEqual([f["path"] for f in ece108["root_files"]], ["ECE 108/syllabus.pdf"])
        self.assertEqual(ece108["root_files"][0]["size_kb"], 1)

    def test_text_output(self) -> None:
        code, out, _ = self._run("catalog")
        self.assertEqual(code, 0)
        self.assertIn("## ECE 108", out)
        self.assertIn("## ECE 271A", out)
        ece271a_block = out.split("## ECE 271A", 1)[1]
        self.assertNotIn("Transcripts (", ece271a_block)
        self.assertIn("unreadable", out)
        lines = out.splitlines()
        self.assertEqual(lines[-1], "readings and textbook text: Tools/readings/<course>/<path>.md; search with --in readings or --in textbooks")
        self.assertNotIn("Study notes", out)

    def test_course_filter(self) -> None:
        code, out, _ = self._run("catalog", "--course", "ece108", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data["courses"]), 1)
        self.assertEqual(data["courses"][0]["course"], "ECE 108")
        code, _, err = self._run("catalog", "--course", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown course", err)
        self.assertIn("ECE 108", err)

    def test_search_still_works(self) -> None:
        code, _, _ = self._run("search", "logical")
        self.assertEqual(code, 0)


class ReadingSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        transcript_dir = self.root / "ECE 108" / "Transcripts"
        transcript_dir.mkdir(parents=True)
        (transcript_dir / "2026-10-20.json").write_text(
            json.dumps(
                [
                    {"start": 0.0, "end": 5.0, "text": "flip flop timing matters"},
                    {"start": 5.0, "end": 10.0, "text": "unrelated words"},
                ]
            )
        )
        readings_dir = self.root / "Tools" / "readings" / "ECE 108"
        (readings_dir / "Slides").mkdir(parents=True)
        (readings_dir / "Textbooks").mkdir(parents=True)
        (readings_dir / "Slides" / "lec1.pdf.md").write_text(
            "# ECE 108/Slides/lec1.pdf\n"
            "Kind: reading\n"
            "\n"
            "### Page 1\n"
            "\n"
            "Intro\n"
            "CMOS inverter basics\n"
            "\n"
            "### Page 2\n"
            "\n"
            "Setup time and hold time\n"
            "flip flop timing constraints\n"
        )
        (readings_dir / "Textbooks" / "book.pdf.md").write_text(
            "# ECE 108/Textbooks/book.pdf\n"
            "Kind: textbook\n"
            "\n"
            "### Page 5\n"
            "\n"
            "the inverter delay model\n"
        )
        (readings_dir / "Slides" / "bad.pdf.md").write_text("no header here\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--root", str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def test_default_scope_finds_reading_not_textbook(self) -> None:
        code, stdout, stderr = self._run("search", "inverter")
        self.assertEqual(code, 0)
        self.assertIn("ECE 108 · ECE 108/Slides/lec1.pdf · p.1", stdout)
        self.assertIn("> CMOS inverter basics", stdout)
        self.assertNotIn("(textbook)", stdout)
        self.assertIn(
            "warning: skipping malformed reading Tools/readings/ECE 108/Slides/bad.pdf.md",
            stderr,
        )

    def test_in_textbooks_only(self) -> None:
        code, stdout, _ = self._run("search", "--in", "textbooks", "inverter")
        self.assertEqual(code, 0)
        self.assertIn("ECE 108 · ECE 108/Textbooks/book.pdf · p.5 (textbook)", stdout)
        self.assertNotIn("lec1.pdf", stdout)

    def test_in_all_finds_both(self) -> None:
        code, stdout, _ = self._run("search", "--in", "all", "inverter")
        self.assertEqual(code, 0)
        self.assertIn("ECE 108 · ECE 108/Slides/lec1.pdf · p.1", stdout)
        self.assertIn("ECE 108 · ECE 108/Textbooks/book.pdf · p.5 (textbook)", stdout)

    def test_hit_is_per_page_with_context(self) -> None:
        code, stdout, _ = self._run("search", "-C", "1", "hold")
        self.assertEqual(code, 0)
        self.assertIn("· p.2", stdout)
        self.assertNotIn("· p.1", stdout)
        self.assertIn("> Setup time and hold time", stdout)
        self.assertIn("  flip flop timing constraints", stdout)

    def test_transcript_ranks_before_page_on_tie(self) -> None:
        code, stdout, _ = self._run("search", "flip", "timing")
        self.assertEqual(code, 0)
        lines = stdout.splitlines()
        self.assertTrue(lines[0].startswith("ECE 108 · 2026-10-20"))
        self.assertIn("ECE 108 · ECE 108/Slides/lec1.pdf · p.2", stdout)

    def test_in_transcripts_excludes_pages(self) -> None:
        code, stdout, _ = self._run("search", "--in", "transcripts", "timing")
        self.assertEqual(code, 0)
        self.assertNotIn("lec1.pdf", stdout)

    def test_page_json_shape(self) -> None:
        code, stdout, _ = self._run("search", "--in", "readings", "--json", "inverter")
        self.assertEqual(code, 0)
        data = json.loads(stdout)
        self.assertEqual(len(data), 1)
        hit = data[0]
        self.assertEqual(
            set(hit.keys()),
            {
                "source",
                "course",
                "rel",
                "kind",
                "page",
                "terms_matched",
                "occurrences",
                "lines",
            },
        )
        self.assertEqual(hit["source"], "reading")
        self.assertEqual(hit["page"], 1)
        self.assertEqual(hit["kind"], "reading")
        self.assertTrue(any(line["hit"] for line in hit["lines"]))

    def test_repeatable_in(self) -> None:
        code, stdout, _ = self._run(
            "search", "--in", "readings", "--in", "textbooks", "inverter"
        )
        self.assertEqual(code, 0)
        self.assertIn("ECE 108 · ECE 108/Slides/lec1.pdf · p.1", stdout)
        self.assertIn("ECE 108 · ECE 108/Textbooks/book.pdf · p.5 (textbook)", stdout)


if __name__ == "__main__":
    unittest.main()
