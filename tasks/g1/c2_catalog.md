# Task: file `src/libra/catalog.py` only. Exactly TWO SEARCH/REPLACE blocks.
## Background (Libra, Python 3.12, stdlib only)
Feature G1: `libra catalog --newer-than NOTE` shows only course sources whose file changed after a study note, so an agent can see what a note is missing. `cli.py` already registers `args.newer_than: str | None` (default None) next to `args.course: str | None` and `args.json: bool`. `root` is the vault root `Path`. Compare `st_mtime_ns`, never the date-only `modified` field: a note and a newer source often share a date.
Existing helpers you may call: `select_courses(root, course_arg, *, catalog=True) -> dict[str, Path] | None` (prints its own error, returns None on failure; `course_arg` may be an exact folder name), `catalog_course(course, course_dir, root) -> dict` (keys `course`, `transcripts` list, `folders` dict name->list, `root_files` list; every entry dict has `path`, a POSIX path relative to `root`), `_print_catalog_block(course_data)`. Module already imports `argparse, json, sys, datetime, Path, List, Optional`.

## Block 1: new function `filter_newer`, inserted right after `catalog_course`
Contract: `def filter_newer(course_data: dict, root: Path, cutoff_ns: int) -> dict:` with a one-line docstring. Returns a NEW dict (input not mutated) with the same keys; `transcripts`, each `folders` list and `root_files` keep only entries whose `(root / entry["path"]).stat().st_mtime_ns > cutoff_ns`; an entry whose stat raises `OSError` is dropped; a folder left with no entries is removed from `folders`. Order of kept entries unchanged.
SEARCH (verbatim):
```
    result["root_files"] = root_entries

    return result


def _print_catalog_block(course_data: dict) -> None:
```
REPLACE: the same first three lines, then two blank lines, the new function, two blank lines, then `def _print_catalog_block(course_data: dict) -> None:`.

## Block 2: `cmd_catalog` handles `args.newer_than`
Behaviour when `args.newer_than` is None: byte-identical output and exit codes to today.
When set:
1. Resolve the note: `Path(args.newer_than).expanduser()`; if relative, use `root / p` when that exists, else `Path.cwd() / p`. If the result is not a file: print `error: note not found: {args.newer_than}` to stderr, return 2.
2. Course: `args.course` if given. Otherwise the note's top folder: `p.resolve().relative_to(root.resolve())`; if that raises `ValueError`, or the relative path has fewer than 2 parts (note sits at the vault root), print `error: note {args.newer_than} is not inside a course folder; pass --course` to stderr, return 2. Otherwise use `parts[0]` as the course argument to `select_courses`.
3. `cutoff_ns = p.stat().st_mtime_ns`; each course's data goes through `filter_newer` before output.
4. Display path: the note's POSIX path relative to `root.resolve()` when under it, else `str(p)`. Modified stamp: `datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes")`.
5. JSON: the top-level object gains key `"newer_than": {"path": <display>, "modified": <stamp>}` after `"courses"`.
6. Text: before the first course block print `newer than <display> (modified <stamp>):` then one empty line; after a course block whose transcripts, folders and root_files are all empty, print `nothing newer`. The final two footer lines stay unchanged.
Keep it readable: a small private helper `_resolve_note(arg: str, root: Path) -> Path | None` is welcome (insert it directly above `cmd_catalog`, inside this block's REPLACE).
SEARCH (verbatim, whole current function):
```
def cmd_catalog(args: argparse.Namespace, root: Path) -> int:
    """Execute the catalog subcommand."""
    selected = select_courses(root, args.course, catalog=True)
    if selected is None:
        return 2

    course_data_list = []
    for name in sorted(selected):
        course_dir = selected[name]
        course_data = catalog_course(name, course_dir, root)
        course_data_list.append(course_data)

    if args.json:
        json.dump({"courses": course_data_list}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    for i, course_data in enumerate(course_data_list):
        if i > 0:
            print()
        _print_catalog_block(course_data)

    print()
    print(
        "readings and textbook text: Tools/readings/<course>/<path>.md; "
        "search with --in readings or --in textbooks"
    )
    return 0
```
