# Task: file `src/libra/library.py` only. Exactly ONE SEARCH/REPLACE block.
Add a module constant for the rclone bisync conflict-copy file-name pattern (e.g. `notes.conflict1.md`, `deck.pdf.conflict2`), shared by `catalog` and `commands`. Insert directly after the `OUTDATED_DIR` line: `CONFLICT_GLOB: str = "*.conflict[0-9]*"` preceded by a one-line `#` comment naming what it matches (rclone bisync conflict copies, fnmatch pattern).
SEARCH (verbatim):
```
MATERIAL_DIRS = ("Slides", "Discussion", "Homework", "Textbooks", "Readings")
OUTDATED_DIR: str = "Outdated"
```
REPLACE: those two lines unchanged, then the comment line and the constant line.
