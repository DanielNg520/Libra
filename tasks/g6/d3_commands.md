# Task: file `src/libra/commands.py` only. Exactly THREE SEARCH/REPLACE blocks.
## Background (Libra, Python 3.12)
Feature G6: Google Drive sync via rclone bisync leaves conflict copies (`notes.conflict1.md`) beside vault notes silently. `libra status` must flag them so the owner or agent diffs and resolves each. `libra.library.CONFLICT_GLOB: str = "*.conflict[0-9]*"` (fnmatch pattern) already exists. `settings.obsidian_academic_vault_dir: Path | None`.

Block 1 (imports). Add `import fnmatch` and `import os` in alphabetical order among the stdlib imports, and `from libra.library import CONFLICT_GLOB` in alphabetical order among the `from libra...` imports (between `libra.lecture_fetch` and `libra.login`). SEARCH (verbatim):
```
import json
import sys
from datetime import datetime
```
and handle the `libra` import in Block 2.
Block 2, SEARCH (verbatim):
```
from libra.lecture_fetch import AUDIO_DIR, state_path
from libra.login import cmd_podcast_login
```
REPLACE inserts `from libra.library import CONFLICT_GLOB` between them.

Block 3: new helper plus `cmd_status` lines.
Helper `def _conflict_copies(vault: Path) -> list[str]:` (one-line docstring), placed directly above `def cmd_status(`: walks `vault` with `os.walk`, pruning in place every directory whose name starts with `.` (e.g. `.git`, `.obsidian`), keeps files whose name matches `CONFLICT_GLOB` via `fnmatch.fnmatch`, returns their POSIX paths relative to `vault`, sorted.
In `cmd_status`, after the `whisper queue` print and before `return EXIT_OK`: when the vault is set and `is_dir()`, compute the copies, print `conflict copies: {n}`, then each path on its own line indented two spaces; when n > 0 print one more line exactly `  diff each against its original, merge or delete (owner rule, 2026-10-30)`. When the vault is unset or missing, print nothing extra.
SEARCH (verbatim):
```
def cmd_status(
    settings: Settings,
    *,
    now: Callable[[ZoneInfo], datetime] = datetime.now,
) -> int:
    vault = str(settings.obsidian_academic_vault_dir) if settings.obsidian_academic_vault_dir else "not set"
    print(f"vault: {vault}")
    print(f"term: {settings.term or 'not set'}")

    state = state_path(settings)
    if state.exists():
        hours = (now(settings.zone).timestamp() - state.stat().st_mtime) / 3600
        print(f"login state: saved {hours:.1f} h ago")
    else:
        print("login state: none (run `libra login`)")

    print(f"whisper queue: {_queued(settings)}")
    return EXIT_OK
```
