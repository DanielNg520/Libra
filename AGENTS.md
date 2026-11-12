# AGENTS.md
Libra: the academic librarian, split out of SemAI (owner, 2026-10-27). Fetches lecture transcripts, serves course material to agents.
Read this file first; it is the only live doc.

## Doc rules
One `AGENTS.md` at repo root; cap 1000 lines; each line at most 30 words; no narrative.
Record each owner decision the turn it is made, dated `(owner, date)`.
Never reference or absorb another repo's content; port what Libra needs, then own it.
Agent behaviour rules (notetaker, homework, study notes, exam sheets) live in Hivemind `libra/` and vault `AGENTS.md`; never here.

## Code policy
Smallest correct diff; reuse before adding; code goes through TriAPI's rebuild pipeline, never hand-written.

## Owner decisions
Owner (2026-11-11): ECE 271A dropped (no podcast access); folder moved to `~/Classes/ECE 271A`, so fetch skips it.
Seam (271A): vault `Tools/readings/ECE 271A/`, `Tools/maps/ECE 271A.json` stay as leftovers; export prunes only current courses (unverified).
Owner (2026-11-01): fetches run manually with the owner (`libra login`, then fetch); `libra-fetch.timer` disabled 2026-11-01; `libra-whisper.timer` stays; `libra-export.timer` 23:30 enabled 2026-11-01.
Owner (2026-10-29): agents never run `login`, `fetch`, `export`, `whisper`, `read --fetch` unasked; enforced in `cli._agent_refusal`; the agent sets `LIBRA_OWNER_OK=1` itself when the owner asks or confirms.
Owner (2026-10-29): agy (Gemini 3.8 Flash) wields Libra too; it loads Hivemind `academic-study` from `~/.gemini/config/skills/` (symlink, Fedora and Mac).
Owner (2026-10-28): a partial fetch exits 4 (`EXIT_PARTIAL`); `libra-fetch.service` `SuccessExitStatus=4`; crash (1) and expired login (3) still fail the unit.
Owner (2026-10-27): Libra is its own project; every academic piece left SemAI for it, transcript fetch and Whisper included (done; SemAI keeps only ADR-0041).
Owner (2026-10-27): the tutor and librarian tools also live in `~/Classes/Current` and Hivemind.
Owner (2026-10-27): remote `git@github.com:DanielNg520/Libra.git`; Libra runs on every machine (Fedora, Mac), not Fedora-only.
Owner (2026-10-27): Libra is modular; her memory lives in Hivemind, shared by every instance (Hivemind `libra/`, start at `LIBRA.md`).
Owner (2026-10-27): an instance may hold a feature others lack; sharing every feature across instances is the long-run goal.
Owner (2026-10-27): Whisper runs on Fedora only; Fedora makes every Whisper output available to Libra instances on other machines.
Owner (2026-10-27): Libra alone fetches and runs Whisper; `libra login` is the only sign-in; UCSD login is always manual with the owner.
Owner (2026-10-27): Libra has its own sops `.secret/secrets.json`; `GEMINI_API_KEY` and `OPENROUTER_API_KEY` share SemAI's key values.
Owner (2026-10-27): Libra absorbed vault `Tools/librarian.py` (search, catalog, maps, readings); one librarian, not two.
Owner (2026-10-27): owner uses Gemini for midterm prep; Libra work runs ahead without waiting for exams.
Owner (2026-10-28): Libra's agents are agy and Claude Code; model APIs only Gemini (reads, OCR), plus the OpenRouter cap fallback.
Owner (2026-10-28): a light local model will later run on the Mac; revisit a local cleaner then, build nothing for it now.
Owner (2026-10-28): the homework-precedent rule (Hivemind `libra/homework-workflow.md`) must be built into Libra deterministically, not left to agent memory.
Superseded (owner, 2026-10-28): course calendar workers do not stay in SemAI; they went with the transition, never ported here.
Clones: Fedora `~/Documents/Coding/Libra`, Mac `~/Developer/Libra`.
Vault: Fedora `~/Classes/Current` (git); Mac `~/Library/CloudStorage/GoogleDrive-danielnguyen520@gmail.com/My Drive/Classes/Current` (Drive, no git) (owner, 2026-11-01).

## Vault and sources
Owner (2026-10-24): decks in `<course>/Slides/`, sources in `<course>/Textbooks/` and `<course>/Readings/`; ECE 25 decks in `ECE 108/Readings/ECE 25/`.
Owner (2026-10-19): non-academic files go in `Current/Personal/`, a non-course folder.
Readings scope (owner, 2026-10-11): Discussion decks and `271.pdf` count; handouts and reference sheets excluded.
Owner (2026-10-11): page reads use Gemini until the $10 cap, then OpenRouter; only public material goes to Gemini (owner, 2026-10-12).
Owner (2026-10-26): readings export to vault `Tools/readings/`; maps live in `Tools/maps/`, rebuilt after each fetch or Whisper transcript, or `libra export`; agents confirm pairs.
Owner (2026-10-28): no new source folder: `Lecture Notes/` went into `Slides/`, superseded into `Slides/Outdated/`; `In Class Problems/` into `Homework/`.
Owner (2026-10-28): Libra skips every `Outdated/` child folder.
Course info (Claude, 2026-10-28): one vault note per course, `<course>/Course info.md`; no table, no Libra code.
Kept: vault `Tools/tests/fixtures/ece108_quiz1/` (exam-prep P1 fixture, cited in vault `AGENTS.md`).
Trap: `LECTURE_NOTES_DIR = "Lecture notes"` is an output dir; a vault folder of that name (any case on the Mac) is never a source.
Trap: vault `Tools/` has no hooks; set `PYTHONDONTWRITEBYTECODE=1` when testing there, or `__pycache__` syncs to Drive.
Trap: `libra read` paths are vault-relative (`ECE 108/Discussion/x.pdf`), not course-relative; a course-relative path answers `unknown_source`.
Cleanup 2026-10-24: 174 writer files trashed (vault `d3fe20d`); restore from Fedora `~/.local/share/Trash`; manifest `~/.cache/spike-20261024/cleanup-manifest.txt`.
Seam: Study notes are untracked in vault git (owner, 2026-10-29); vault-wide note edits have no git undo; Drive keeps 30-day versions.

## Architecture
Package: uv project, `src/libra`, `requires-python >=3.12`; Mac has uv 0.11.2 with Python 3.12 and 3.13 (verified 2026-10-27).
Extras: core is stdlib only (search, catalog, map, precedents); `fedora` adds fetch, Whisper, Gemini reads, export; `plot` adds `matplotlib`, `schemdraw`.
Install: `uv tool install --editable '.[fedora,plot]'` on Fedora, `uv tool install --editable '.[plot]'` on the Mac; console script `libra`.
CLI: `login`, `fetch`, `whisper`, `read`, `export`, `search`, `catalog`, `map`, `status`, `ocr`, `precedents`; one entry point.
Login then fetch: `libra login` saves state and fetches at once (ADR-0041 P4 option a).
Schedule: Fedora user timers `libra-export.timer` 23:30 (maps, readings), `libra-whisper.timer` 01:00 (drains queue until 06:00, `WHISPER_HOURS`); fetch timer disabled.
Wanted courses: vault course folders (`course_dir` rule plus `library.NON_COURSE_DIRS`, the one list); term from config `LIBRA_TERM` (e.g. `FA26`), set once per quarter.
Reads: `libra read` runs the Gemini page fetch in process under a file lock (`index_lock`).
Mac: search, catalog, map run locally on the Drive vault; `read`, `ocr` over `ssh -o BatchMode=yes dyne@fedora libra ...`; owner-only commands need `ssh -t`.
Config: `Settings` slim dataclass from env plus gitignored `.config/libra.env`; time zone `LIBRA_TZ` default `America/Los_Angeles`.
Owner (2026-10-29): keep repo-relative `.config/`, `.secret/`; editable installs only; `config._read_config_env` warns with the path when `libra.env` is unreadable.
State: `~/.local/state/libra/` (no sqlite); holds podcast login state, `lecture_audio/`, `lecture_reads/` cache.
Exam prep: vault ADR-0001 D1, D2, D7 (inventory, coverage, aliases) become Libra commands; `examprep.py` (D3 to D6) stays vault tutor code.
`examprep.py` imports Libra loaders via PEP 723 `[tool.uv.sources] libra = { path = "/home/dyne/Documents/Coding/Libra" }` (Fedora only, as planned).
Size guard: `tests/test_size_guard.py` (600 lines a file, 100 code lines a function).
Gate: Libra has the TriAPI pre-commit ledger hook; hand changes enter the ledger only through `dispatch-ledger-hand.sh`, which the owner runs.

### Command rules
OCR: `ocr.transcribe_image` on `gemini.chat` (handwriting and `--notes` prompts); no Canvas or flyer prompt; no OpenRouter fallback, a Gemini cap hit exits 1.
Precedents (owner-approved 2026-10-29): `libra precedents --course C <terms>`, tiers in fixed order, `--json`, OR terms, 5 per tier; exit 1 when all empty.
Precedent tiers: 1 solutions (`Homework/` names matching `sol|solution|key|answer`), 2 discussion (`Discussion/` plus `-DI` transcripts), 3 lectures (`Slides/` plus lecture transcripts).
Why a command, not a `search` flag: tiering, order and the packet format would bend `search`'s output contract.
Owner (2026-10-29): owner's own submissions (`*submission*`) and agent solutions are never precedents; only posted solutions form tier 1.
Owner (2026-10-29): precedents enforcement is the `academic-study` skill's mandatory first step only; no hooks; unexported folder files are listed per tier.
Owner (2026-10-29): agent-written solutions end in `solution` (`Problem M solution.md`, `homework N solution.md`) in `Study notes/homework N/`; rule lines only, no Libra code.
`catalog --newer-than NOTE` (`catalog.filter_newer`): errors exit 2 (`note not found`, `pass --course`); `catalog._note_course(note, root) -> str | None`.
`status` prints `conflict copies: N`, paths, owner-rule hint; `library.CONFLICT_GLOB` shared with `catalog._file_entry`; dot dirs skipped.
`read --chapter N|TITLE` uses cached maps only, never builds; `--printed N|A-B` maps via `textbooks.page_labels`; both exclusive with `--pages`.
`read --fetch` caps at `MAX_FETCH_PAGES` 25; a whole-book or long-chapter fetch answers `too_many_pages`; fetch in `--pages` slices.
Agent guard: refuses (exit 2) under `CLAUDECODE`, `ANTIGRAVITY_AGENT`, `AI_AGENT`, or `SSH_CONNECTION` without a TTY; timers and owner `ssh -t` pass.
F17 rule: an ssh-only refusal (no agent var) adds the `ssh -t` hint; `libra --help` names `ssh -t` or `LIBRA_OWNER_OK=1`.
Guard: `fetch` and `export` refuse without `lecture_reads/source_index.json` in the state dir (`commands._cache_ready`); never smoke-test on the real vault.
Mac login command: `ssh -t -L 9222:127.0.0.1:9222 dyne@fedora /home/dyne/.local/bin/libra login`; a bare `~` expands on the Mac.
Mac OCR: `ssh -o BatchMode=yes dyne@fedora /home/dyne/.local/bin/libra ocr - --notes < image.png`; the image travels on stdin.

### Maps and copy check
F13 rule: `lecture_map.ensure_book_maps` runs per course before `fingerprint` in `write_maps`; `book_map` builds uncached books only; keys load lazily, once.
F13 why first: a failed build leaves no cache, so the next run retries; a build changes `books` mtime, so the map rebuilds.
F13 units: both services set `Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin`; without it `sops` is missing and keys never load (verified).
F16 rule: a failed `book_map` touches `<sha>.failed` beside the cache; `ensure_book_maps` skips it for `FAILED_RETRY_S` (24 h); never name it `.json`.
Owner (2026-10-29): a scanned textbook, once identified, is never retried (no weekly vision call).
Scanned rule: `load_cached_map` retries an empty map weekly only if searchable; a scanned map (`searchable` false) is final; a new copy has a new sha.
F18 rule: `lecture_map._link_targets` scans links (angle, balanced parens, newline ends a target), strips a trailing quoted title.
F19 rule: `write_maps` passes a `functools.cache` getter `linked`; `ensure_book_maps(..., linked=)` scans the vault at most once per run, lazily.
Owner (2026-10-30): `check_copies` is needed (SemAI ADR-0038 P2); `ensure_book_maps` runs it per course over cached maps, `delete=False`; lines go to the journal.
CC guard: `lecture_map.linked_pdf_names` collects PDF names from vault note links (Markdown, `<...>`, wikilinks, `file:///`); skips `Tools/` and dot dirs.
CC rule: `linked` matches by file name, not path, because notes keep stale relative and Mac `file:///` links; report-only lines say `report only, linked`.
Owner (2026-10-30): deletion stays off (`delete=False`) until the owner arms it; first raise Hivemind `libra/copy-check-deletion-arm.md`.
To arm: owner changes `delete=False` to `True` in `lecture_map.ensure_book_maps`.
Seam (CC): a note citing a book only in prose (no link) is not in `linked`; owner (2026-10-30): record only, no protection.
Seam: `refresh_exports` builds maps before readings, so a renamed deck reaches `Tools/maps/` one export later.
Seam: fetch and Whisper can build the same new book at once; double call, last atomic write wins; harmless.

### Read cache and index
F12 rule: `sources._adopt_moved` re-keys a missing or stale-mtime entry to a same-size, same-sha entry (own or same-course orphan); never takes a listed rel.
F12 callers: `read_sources` (caller holds the lock) and `reading_export.write_readings` via `reconcile_index`, which takes `index_lock` itself.
F14 rule: `read_pages` runs `reconcile_index` (outside the lock) when cached pages are missing; re-reads only if it adopted.
F7 rule: recitation-retry pages carry `lecture_docs.PARAPHRASE_NOTE` under each `### Page N`; earlier cached reads stay unmarked (no re-read).
Trap: `index_lock` (`read.lock`, flock) is not re-entrant; never call `reconcile_index` while holding it (`read_pages` fetch path).
Guard: `test_reconcile_never_runs_under_index_lock` (`tests/test_read.py`) fails if `read_pages` reconciles while holding `index_lock`.
Seam: export, and a plain `read` with missing pages, wait on `index_lock` while a `libra read --fetch` runs (up to 900 s).
Closed 2026-10-29: F8 delete path has no production caller (CC passes `delete=False`); F9 hashing all 10 textbooks takes 0.07 s.

## Findings
F23 [low · 1 · 2026-11-03] deploy/libra-export.service: no `After=network-online.target`; Persistent catch-up at boot may fail a new-book Gemini map, `.failed` blocks retry 24 h (suspected).
Fix proposal: add `After=`/`Wants=network-online.target` as in `libra-fetch.service`.
Closed 2026-11-03: F21 timer matches installed copy and live schedule; F22 `_note_course` behaviour identical, tests cover outside-root and root (verified).

## Polish queue (owner-approved ideas, each plans before code in its own session)
Owner (2026-10-29): vector search could port SemAI `memory/indexer.py` (heading chunks, hash diff) and `retriever.py` `hybrid_search` (BM25 plus local vectors).
Owner (2026-10-30): further reading runs as rule lines (agents search themselves); a `libra further` client is built only if that proves short in use.
`libra further` facts (2026-10-30): Crossref and arXiv keyless under 1 s; OpenAlex keyless shares a $0.10 daily per-IP budget; free key needs an email.
`libra further` limits: topic terms only, never note text, transcripts or owner data; Google Scholar excluded (SemAI ADR-0030 decision 7).
ADR-0001 P3 `libra check-note` builds only on its D7 trigger.

## Carryover
Last audit: 2026-11-03 wrap-up (audited through `8b7deba`; F21, F22 verified closed; F23 added).
Next session: fetch with the owner when asked (none after 10-28); open owner item: deletion arming.
Open check (F15): the 10-29 login failed by 23:30; next `libra login` should save without a manual `CourseList.aspx` tab.
Seam: login looks stuck to the owner; it polls every 15 s, saves, then fetches before printing.
Seam (G1): mtime means rewritten on disk; the 2026-10-19 vault move made every ECE 108 transcript "newer"; lists too much, never too little.
Seam (G6): `status` walks the whole vault each call (`os.walk`, dot dirs pruned); fine at today's size.
Seam (F21): export takes `index_lock` and waits on a running `read --fetch` (up to 900 s); a quiet export takes 1 to 3 s, no Gemini.
F22 trace: `_conflict_copies` walk is not duplication; catalog skips copies per course, status lists them vault-wide; no change.
Seam (TR): `--printed` fails (`printed_page_unknown`) on about the last 20 printed pages and on roman front matter; verified live (PRML 738).
Seam (TR): chapter numbers follow map order; a map opening with a part heading (BDA `Background`) shifts them; the answer names the title read.
Seam (TR): `--printed` runs `pdftotext` over the whole book per call (about 2 s); `_resolve_printed_pages` leaves `int | None` unnarrowed for mypy.
Seam: solution names need a `sol|solution|key|answer` token; a solution file named otherwise (e.g. `hw1_ans.pdf`) lands in no tier.
Seam: default prompt on an image without handwriting gets null content; `ocr` prints `no content (finish_reason stop)`, exit 1.
Seam: the agent guard stops careless agents, not deliberate ones; an agent can set `LIBRA_OWNER_OK=1`; other harnesses are unchecked.
Seam: `whisper` and `fetch` take no lock against each other; concurrent vault commits can fail on the git index lock and retry next run.
Seam: `cmd_whisper` counts only successes; a failing job ends the loop early (logged), rest waits for the next night.
Seam: `test_fetch_commands_report_missing_extra` child loads real `.config/libra.env`; a bad machine config fails it with the settings message (unverified elsewhere).
Seam: `test_vault_commands_run_without_fedora_extra` child reads real `.config/libra.env`, but `--root` skips `Settings.load`; harmless today (verified).
Seam: ruff F811 on `tests/test_sources_ranges.py` `fake_chat` is a pytest-fixture false positive, inherited from SemAI.
Guard: tests/test_lecture_map.py autouse `_no_real_book_map` fails any test that reaches a real `book_map`.
Trap: Claude Code sets `AI_AGENT` as well as `CLAUDECODE`; a live guard test must unset both.
Trap: Claude Code `!libra fetch` runs with `CLAUDECODE` set and is refused; prefix `LIBRA_OWNER_OK=1`.
Trap: dispatch excerpts go in fences at real indentation; DeepSeek copies a display indent into SEARCH (4 misses, 2026-10-29).
Trap: dispatch excerpts must mark gaps between non-adjacent code; two SEARCH misses came from excerpts shown as adjacent (2026-10-29).
Trap: DeepSeek whole-file replies for new modules needed 3 rounds; prefer a skeleton then small edit dispatches.
Trap: TriAPI `llm_client.is_deepseek_peak_hours` fails to import from a bare `python3 -c`; check the clock (UTC 01-04, 06-10 weekdays) instead.
Trap: never smoke-test fetch-side commands with `LIBRA_VAULT_DIR` on the real vault; use a scratch vault.
Trap: renaming a ported file breaks cross-test imports (`from test_sources import ...`); grep `^from test_` after any test rename.
Trap: tests must pass `LIBRA_STATE_DIR` to `Settings.load`; the default creates the real `~/.local/state/libra`.
Trap: the Mac has no ledger-check hook and no dispatch setup; Libra code changes happen on Fedora only.
Trap: Fedora's own `known_hosts` lacks `fedora`; `ssh dyne@fedora` from Fedora fails host-key checks; test the ssh path from the Mac.
Trap: Mac non-interactive ssh lacks `/opt/homebrew/bin`; prefix `export PATH=$HOME/.local/bin:/opt/homebrew/bin:$PATH` before `uv`.

## File and directory index
`AGENTS.md` this file. `docs/decisions/` ADRs (`0001` pre-problem note standard). `pyproject.toml` (uv; core stdlib, extras `fedora`, `plot`), `.sops.yaml`, `.secret/secrets.json` (gitignored, Fedora only).
`src/libra/config.py`: `Settings` frozen dataclass, `Settings.load(env)` from env plus `.config/libra.env`; keys `LIBRA_*`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`.
`src/libra/lecture_fetch.py` podcast.ucsd.edu to transcripts; `lecture_whisper.py` Whisper queue; `jobs.py` `wanted_courses`, `run_fetch_job`, `run_whisper_job`, `refresh_exports`.
`src/libra/lecture_docs.py` page render and Gemini read cache; `sources.py` (also `index_lock`, `reconcile_index`), `textbooks.py`, `source_pages.py`, `reading_export.py` readings and exports.
`src/libra/lecture_align.py`, `lecture_map.py` lecture-to-slide maps (`ensure_book_maps` builds new textbook maps, runs the copy check; `linked_pdf_names`); `gemini.py` chat client; `errors.py` `ProviderError`; `courses.py` `canonical_course_code`.
`src/libra/library.py` course discovery (`select_courses`, `NON_COURSE_DIRS`), transcript and page loaders; `search.py`, `catalog.py` (`--newer-than`), `mapview.py`, `precedents.py` (tiered homework precedents) subcommands; `cli.py` `libra` entry (`--root` or `LIBRA_VAULT_DIR`; `_agent_refusal` owner-only guard).
`src/libra/commands.py` fetch-side handlers incl. `cmd_ocr`, `cmd_status` (conflict copies), exit codes (3 = login expired, 4 = partial fetch); `ocr.py` OCR; `read.py` `read_pages` (flock `read.lock`, renamed-source adoption, `--chapter`, `--printed`); `login.py` sign-in.
`deploy/` user units: `libra-fetch` 23:30 (timer disabled 2026-11-01, owner), `libra-export` 23:30 (enabled 2026-11-01), `libra-whisper` 01:00 to 06:00; installed copies in `~/.config/systemd/user/`.
`src/libra/obsidian_vault.py`: vault git `commit_paths`, `has_uncommitted_changes`. `tests/`: pytest, `test_size_guard.py` (600 lines a file, 100 a function).
