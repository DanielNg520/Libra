from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, List

from libra import cli, mapview

librarian: Any


class LibrarianMapTests(unittest.TestCase):
    """Tests for the map subcommand and its helpers."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._write_fixture()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_fixture(self) -> None:
        """Create course transcripts and the initial map file."""
        tx_dir = self.root / "ECE 1" / "Transcripts"
        tx_dir.mkdir(parents=True, exist_ok=True)
        (tx_dir / "2026-10-14.json").write_text("[]", encoding="utf-8")
        (tx_dir / "2026-10-15.json").write_text("[]", encoding="utf-8")

        (self.root / "ECE 2" / "Transcripts").mkdir(parents=True, exist_ok=True)

        maps_dir = self.root / "Tools" / "maps"
        maps_dir.mkdir(parents=True, exist_ok=True)

        map_data = {
            "version": 1,
            "course": "ECE 1",
            "inputs": "x",
            "built": "2026-10-25T05:00:00Z",
            "transcripts": [
                {
                    "id": "2026-10-14",
                    "kind": "lecture",
                    "path": "ECE 1/Transcripts/2026-10-14.json",
                    "spans": [
                        {
                            "from_s": 0.0,
                            "to_s": 900.0,
                            "deck": None,
                            "candidate": "ECE 1/Slides/a.pdf",
                            "status": "unmatched",
                            "score": 0.05,
                            "pages": [],
                            "also": [],
                            "terms": [],
                        },
                        {
                            "from_s": 900.0,
                            "to_s": 9000.0,
                            "deck": "ECE 1/Slides/b.pdf",
                            "status": "matched",
                            "score": 0.12,
                            "pages": [3, 9],
                            "also": [],
                            "terms": ["gaussian"],
                        },
                    ],
                },
                {
                    "id": "2026-10-15",
                    "kind": "lecture",
                    "path": "ECE 1/Transcripts/2026-10-15.json",
                    "spans": [
                        {
                            "from_s": 0.0,
                            "to_s": 4000.0,
                            "deck": "ECE 1/Slides/c.pdf",
                            "status": "matched",
                            "score": 0.2,
                            "pages": [1],
                            "also": [],
                            "terms": ["ml"],
                        }
                    ],
                },
            ],
            "decks": [
                {
                    "rel": "ECE 1/Slides/a.pdf",
                    "track": "lecture",
                    "duplicates": ["ECE 1/Slides/a copy.pdf"],
                    "transcripts": [],
                    "chapters": [],
                },
                {
                    "rel": "ECE 1/Slides/b.pdf",
                    "track": "lecture",
                    "duplicates": [],
                    "transcripts": ["2026-10-14"],
                    "chapters": [
                        {
                            "book": "ECE 1/Textbooks/book.pdf",
                            "title": "Bayes",
                            "first": 39,
                            "last": 54,
                            "score": 0.05,
                            "terms": [],
                        }
                    ],
                },
                {
                    "rel": "ECE 1/Slides/c.pdf",
                    "track": "lecture",
                    "duplicates": [],
                    "transcripts": ["2026-10-15"],
                    "chapters": [],
                },
            ],
        }
        (maps_dir / "ECE 1.json").write_text(
            json.dumps(map_data, indent=1, ensure_ascii=False), encoding="utf-8"
        )

    def _run_cli(self, args: List[str]) -> tuple[int, str, str]:
        """Run cli.main with root prepended, returning (code, stdout, stderr)."""
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--root", str(self.root)] + args)
        return code, out.getvalue(), err.getvalue()

    def _map_json(self) -> bytes:
        path = self.root / "Tools" / "maps" / "ECE 1.json"
        return path.read_bytes()

    def test_parse_time(self) -> None:
        """parse_time handles MM:SS, H:MM:SS and plain seconds; rejects bad input."""
        self.assertEqual(2580.0, mapview.parse_time("43:00"))
        self.assertEqual(3723.0, mapview.parse_time("1:02:03"))
        self.assertEqual(12.5, mapview.parse_time("12.5"))
        with self.assertRaises(ValueError):
            mapview.parse_time("a:b")

    def test_merge_map_trims_span(self) -> None:
        """merge_map trims overlapping spans and records deck transcript membership."""
        map_data = mapview.load_map(self.root, "ECE 1")
        original = json.loads(json.dumps(map_data))
        confirmed = [
            {
                "transcript": "2026-10-14",
                "deck": "ECE 1/Slides/a.pdf",
                "from_s": 2580.0,
                "to_s": 5700.0,
            }
        ]

        merged = mapview.merge_map(map_data, confirmed)
        tx = next(t for t in merged["transcripts"] if t["id"] == "2026-10-14")
        spans = sorted(tx["spans"], key=lambda s: s["from_s"])
        bounds = [(s["from_s"], s["to_s"]) for s in spans]
        self.assertEqual(
            [(0.0, 900.0), (900.0, 2580.0), (2580.0, 5700.0), (5700.0, 9000.0)],
            bounds,
        )
        self.assertEqual("confirmed", spans[2]["status"])
        self.assertEqual("ECE 1/Slides/a.pdf", spans[2]["deck"])
        self.assertEqual("ECE 1/Slides/b.pdf", spans[1]["deck"])
        self.assertEqual("ECE 1/Slides/b.pdf", spans[3]["deck"])

        deck_a = next(d for d in merged["decks"] if d["rel"] == "ECE 1/Slides/a.pdf")
        self.assertEqual(["2026-10-14"], deck_a["transcripts"])
        self.assertEqual(map_data, original)

    def test_merge_map_whole_transcript(self) -> None:
        """Whole-transcript confirmation replaces the span and drops old deck membership."""
        map_data = mapview.load_map(self.root, "ECE 1")
        confirmed = [
            {"transcript": "2026-10-15", "deck": "ECE 1/Slides/b.pdf"},
            {"transcript": "unknown-id", "deck": "ECE 1/Slides/a.pdf"},
        ]

        merged = mapview.merge_map(map_data, confirmed)
        tx = next(t for t in merged["transcripts"] if t["id"] == "2026-10-15")
        self.assertEqual(1, len(tx["spans"]))
        span = tx["spans"][0]
        self.assertEqual((0.0, 4000.0), (span["from_s"], span["to_s"]))
        self.assertEqual("ECE 1/Slides/b.pdf", span["deck"])
        self.assertEqual("confirmed", span["status"])

        deck_c = next(d for d in merged["decks"] if d["rel"] == "ECE 1/Slides/c.pdf")
        self.assertEqual([], deck_c["transcripts"])
        self.assertEqual(["2026-10-14", "2026-10-15"], [t["id"] for t in merged["transcripts"]])

    def test_resolve_deck(self) -> None:
        """resolve_deck matches full rel, basename, and duplicate basename."""
        map_data = mapview.load_map(self.root, "ECE 1")
        self.assertEqual(
            "ECE 1/Slides/b.pdf", mapview.resolve_deck(map_data, "ECE 1/Slides/b.pdf")
        )
        self.assertEqual(
            "ECE 1/Slides/b.pdf", mapview.resolve_deck(map_data, "b.pdf")
        )
        self.assertEqual(
            "ECE 1/Slides/a.pdf", mapview.resolve_deck(map_data, "a copy.pdf")
        )
        self.assertIsNone(mapview.resolve_deck(map_data, "nope.pdf"))

    def test_cli_confirm_happy_path(self) -> None:
        """map --confirm writes a confirmed entry and is idempotent."""
        before = self._map_json()
        args = [
            "map",
            "--confirm",
            "--course",
            "ECE 1",
            "--transcript",
            "2026-10-14",
            "--deck",
            "b.pdf",
            "--from",
            "15:00",
            "--to",
            "20:00",
        ]
        code, out, _ = self._run_cli(args)
        self.assertEqual(0, code)
        self.assertTrue(out.startswith("confirmed 2026-10-14"))

        path = self.root / "Tools" / "maps" / "ECE 1.confirmed.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(1, data["version"])
        self.assertEqual(
            [
                {
                    "transcript": "2026-10-14",
                    "deck": "ECE 1/Slides/b.pdf",
                    "from_s": 900.0,
                    "to_s": 1200.0,
                }
            ],
            data["confirmed"],
        )

        code, _, _ = self._run_cli(args)
        self.assertEqual(0, code)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(1, len(data["confirmed"]))
        self.assertEqual(before, self._map_json())

    def test_cli_confirm_errors(self) -> None:
        """map --confirm returns 2 for invalid transcript, deck, time and argument combos."""
        cases: List[List[str]] = [
            [
                "map",
                "--confirm",
                "--course",
                "ECE 1",
                "--transcript",
                "nope",
                "--deck",
                "b.pdf",
            ],
            [
                "map",
                "--confirm",
                "--course",
                "ECE 1",
                "--transcript",
                "2026-10-14",
                "--deck",
                "nope.pdf",
            ],
            [
                "map",
                "--confirm",
                "--course",
                "ECE 1",
                "--transcript",
                "2026-10-14",
                "--deck",
                "b.pdf",
                "--from",
                "xx",
            ],
            [
                "map",
                "--confirm",
                "--course",
                "ECE 1",
                "--transcript",
                "2026-10-14",
                "--deck",
                "b.pdf",
                "--from",
                "20:00",
                "--to",
                "10:00",
            ],
            ["map", "--confirm", "--transcript", "2026-10-14", "--deck", "b.pdf"],
        ]
        for args in cases:
            with self.subTest(args=args):
                code, _, _ = self._run_cli(args)
                self.assertEqual(2, code)

    def test_cli_read(self) -> None:
        """map --course prints span/deck/chapter info; --date filters output."""
        code, out, _ = self._run_cli(["map", "--course", "ECE 1"])
        self.assertEqual(0, code)
        self.assertIn("b.pdf", out)
        self.assertIn("unmatched", out)
        self.assertIn('"Bayes" pp 39-54', out)

        code, out, _ = self._run_cli(
            ["map", "--course", "ECE 1", "--date", "2026-10-15"]
        )
        self.assertEqual(0, code)
        self.assertIn("c.pdf", out)
        self.assertNotIn("Bayes", out)

        code, out, _ = self._run_cli(["map", "--course", "ECE 1", "--json"])
        self.assertEqual(0, code)
        data = json.loads(out)
        self.assertEqual(1, len(data["courses"]))

    def test_cli_no_map_file(self) -> None:
        """map --course for a course with no map returns 1 and warns on stderr."""
        code, _, err = self._run_cli(["map", "--course", "ECE 2"])
        self.assertEqual(1, code)
        self.assertIn("no map yet for ECE 2", err)




if __name__ == "__main__":
    unittest.main()
