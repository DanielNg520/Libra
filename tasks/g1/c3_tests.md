# Task: file `tests/test_librarian.py` only. Exactly TWO SEARCH/REPLACE blocks.
## Feature under test (G1, already implemented)
`libra catalog --newer-than NOTE [--course X] [--json]` keeps only course sources (transcripts, folder files, root files) whose file `st_mtime_ns` is STRICTLY greater than the note's. NOTE relative resolves against the vault root (`--root`), then cwd; absolute works too. Course defaults to the note's top folder under the root; `--course` overrides. Errors exit 2: missing note -> stderr contains `note not found`; note not inside a course folder and no `--course` -> stderr contains `pass --course`. JSON gains top-level `"newer_than": {"path": <note path relative to root, POSIX>, "modified": <"YYYY-MM-DDTHH:MM">}`; folders left empty are absent from `folders`. Text output starts with the line `newer than <path> (modified <stamp>):`; a course with nothing newer prints a line `nothing newer`. Without the flag, output is unchanged.

## Real JSON shape (verbatim from `catalog_course`; assert against THIS, never invent keys)
`{"courses": [{"course": "ECE 108", "transcripts": [{"date", "kind", "path", "status", "duration", "segments", "opening"}], "folders": {"Slides": [{"path", "size_kb", "modified"}]}, "root_files": [{"path", "size_kb", "modified"}]}], "newer_than": {...}}`.
Transcripts are NOT a folder. Pick a course with `next(c for c in data["courses"] if c["course"] == "ECE 108")`; compare paths via `[e["path"] for e in ...]`; course names via `[c["course"] for c in data["courses"]]`.

## Block 1: imports. SEARCH (verbatim):
```
import json
import tempfile
```
REPLACE:
```
import json
import os
import tempfile
```

## Block 2: new tests at the end of class `CatalogTests`, inserted directly before `def test_search_still_works`.
Use the class fixture below (`self.root`, `self.course1` = `ECE 108`, `self.course2` = `ECE 271A`, `self._run(*argv) -> (code, out, err)`). Add a helper `_age_all(self) -> None` that sets every file under `self.root` (via `rglob("*")`, files only) to `os.utime(path, ns=(T0, T0))` with class constant `T0 = 1_800_000_000_000_000_000`, and a helper `_touch(self, path: Path, ns: int) -> None` doing `os.utime(path, ns=(ns, ns))`. Note path constant: `NOTE = "ECE 108/Study notes/lecture 1.md"`.
Tests (each starts with `self._age_all()`; note set to `T0 + 10**9`):
1. `test_newer_than_lists_only_newer_sources`: touch `ECE 108/Slides/lecture1.pdf` and `ECE 108/Transcripts/2026-10-20.json` to `T0 + 2 * 10**9`; run `catalog --newer-than NOTE --json`; exit 0; course list is exactly `["ECE 108"]`; ECE 108 transcripts paths == `["ECE 108/Transcripts/2026-10-20.json"]`; `folders` == `{"Slides": [...]}` with the one path `ECE 108/Slides/lecture1.pdf`; `root_files == []`; `newer_than["path"] == NOTE` and `newer_than["modified"]` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$` (use `assertRegex`).
2. `test_newer_than_is_strict_and_sub_second`: touch `syllabus.pdf` to note + 1_000_000 ns (1 ms later, same second) and `ECE 108/Slides/lecture1.pdf` to exactly the note's ns; JSON root_files paths == `["ECE 108/syllabus.pdf"]` and `"Slides"` not in folders.
3. `test_newer_than_text_output`: nothing touched newer; run without `--json`; exit 0; first output line == `f"newer than {NOTE} (modified "` prefix (use `startswith`) and ends with `):`; `"nothing newer"` in out; `"## ECE 271A"` not in out; last line still the `readings and textbook text: ...` footer (same as `test_text_output`).
4. `test_newer_than_course_override_and_errors`: write `self.root / "guide.md"`, then `_age_all()`, touch guide.md to `T0 + 10**9` and `ECE 271A/Homework/hw1.pdf` to `T0 + 2 * 10**9`; `catalog --newer-than guide.md` -> exit 2, `pass --course` in err; `catalog --newer-than guide.md --course ece271a --json` -> exit 0, courses == `["ECE 271A"]` (hw1.pdf touched newer first, so `folders["Homework"]` has one entry); `catalog --newer-than "nope.md"` -> exit 2, `note not found` in err.
5. `test_newer_than_absolute_path`: touch `syllabus.pdf` newer; pass `str(self.root / NOTE)`; JSON `newer_than["path"] == NOTE` and root_files has `ECE 108/syllabus.pdf`.
Note: the fixture's `ECE 108/Transcripts/2026-10-15.json` is invalid JSON and `notes.md` is ignored; an unreadable transcript still appears in `transcripts` if newer, so keep it at T0.
SEARCH (verbatim, 4-space indent):
```
    def test_search_still_works(self) -> None:
        code, _, _ = self._run("search", "logical")
        self.assertEqual(code, 0)
```
REPLACE: the new constants (class-level, placed first), helpers and five tests, then the SEARCH lines unchanged.

## Class fixture (verbatim, for reference only; do not edit)
```
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
```
