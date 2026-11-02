# Task: file `src/libra/cli.py` only. Exactly TWO SEARCH/REPLACE blocks; a reply with only one block is rejected.
Feature G1: `libra catalog --newer-than NOTE` lists only course sources modified after a study note. This task only registers the flag; `catalog.cmd_catalog` reads `args.newer_than` (str or None).

Block 1 (module docstring usage line). SEARCH is exactly this one line:
```
       libra catalog [--course X] [--json]
```
REPLACE with exactly:
```
       libra catalog [--course X] [--newer-than NOTE] [--json]   (NOTE: sources changed since a study note)
```

Block 2 (catalog parser in `_add_vault_parsers`). Add one `catalog_parser.add_argument("--newer-than", ...)` call between the existing `--course` and `--json` arguments: `dest` defaults to `newer_than`, `default=None`, `metavar="NOTE"`, help text exactly `only sources modified after this note (path relative to the vault root, or absolute)`. Match the surrounding call style. SEARCH (verbatim, 4-space indent):
```
    catalog_parser.add_argument("--course", default=None, help="one course, default all")
    catalog_parser.add_argument(
        "--json", action="store_true", default=False, help="structured output"
    )
```
Keep both existing calls byte-identical in REPLACE; only insert the new call between them.
