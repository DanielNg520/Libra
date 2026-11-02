# Task: file `tests/test_commands.py` only. Exactly ONE SEARCH/REPLACE block.
## Feature under test (G6, already implemented)
`commands.cmd_status(settings)` now also prints, when `settings.obsidian_academic_vault_dir` exists as a directory: a line `conflict copies: N`, then each conflict copy's POSIX path relative to the vault on its own line indented two spaces (sorted), then, only when N > 0, the line `  diff each against its original, merge or delete (owner rule, 2026-10-30)`. Conflict copies are files matching fnmatch `*.conflict[0-9]*`; directories whose name starts with `.` are never searched. When the vault dir does not exist, no `conflict copies` line is printed.
The vault path attribute is `settings.obsidian_academic_vault_dir` (there is NO `vault_dir`); the fixture does NOT create the vault directory: each test must `mkdir(parents=True)` it before writing files.
## Fixture (verbatim, already in the file)
```
@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "LIBRA_VAULT_DIR": str(tmp_path / "vault"),
            "LIBRA_TERM": "FA26",
        }
    )
```
Existing `test_status` patches `commands.state_path` with `monkeypatch.setattr(commands, "state_path", lambda s: s.state_dir / "ucsd-podcast-state.json")`; do the same in the new tests. Module already imports `os`, `datetime`, `timedelta`, `Path`, `pytest`, `commands`, `Settings`.
Add two tests directly after `test_status` (insert before `def test_status(` is NOT allowed; append after the SEARCH anchor below, which is the end of `test_status`):
1. `test_status_lists_conflict_copies(settings, monkeypatch, capsys)`: create in the vault `ECE 108/Study notes/lecture 1.md`, `ECE 108/Study notes/lecture 1.conflict1.md`, `ECE 108/Slides/deck.pdf.conflict2`, `notes.conflict.md` (no digit, not a copy), `.obsidian/workspace.conflict1.json` (hidden dir, skipped). Run `cmd_status` (returns 0); assert the exact block of lines `conflict copies: 2`, `  ECE 108/Slides/deck.pdf.conflict2`, `  ECE 108/Study notes/lecture 1.conflict1.md`, the hint line, appear consecutively in output (compare a slice of `out.splitlines()` starting at the `conflict copies` line); assert `.obsidian` and `notes.conflict.md` not in out.
2. `test_status_no_conflict_copies(settings, monkeypatch, capsys)`: vault dir exists with one plain note; output contains line `conflict copies: 0` and not `diff each`. Also: with the vault dir absent (use a fresh `Settings.load` whose `LIBRA_VAULT_DIR` points to a missing `tmp_path / "missing"`; take `tmp_path` as a fixture arg), output has no `conflict copies` text.
SEARCH (verbatim, 4-space indent; the last lines of `test_status`):
```
    assert commands.cmd_status(settings, now=lambda zone: later) == 0
    out = capsys.readouterr().out
    assert "login state: saved 2.0 h ago" in out
```
REPLACE: those three lines unchanged, then two blank lines, then the two new test functions (fully typed like `test_status`).
