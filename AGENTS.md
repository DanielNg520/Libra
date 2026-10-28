# AGENTS.md
Libra: the academic librarian, split out of SemAI (owner, 2026-10-27). Fetches lecture transcripts, serves course material to agents.
Read this file first; it is the only live doc.

## Doc rules
One `AGENTS.md` at repo root; cap 1000 lines; each line at most 30 words; no narrative.
Record each owner decision the turn it is made, dated `(owner, date)`.
Never reference or absorb another repo's content; port what Libra needs, then own it.

## Code policy
Smallest correct diff; reuse before adding; code goes through TriAPI's rebuild pipeline, never hand-written.

## Owner decisions
Owner (2026-10-27): Libra is its own project; every academic piece leaves SemAI for it, transcript fetch and Whisper included.
Owner (2026-10-27): the tutor and librarian tools also live in `~/Classes/Current` and Hivemind.
Owner (2026-10-27): remote `git@github.com:DanielNg520/Libra.git`; Libra runs on every machine (Fedora, Mac), not Fedora-only.
Owner (2026-10-27): Libra is modular; her memory lives in Hivemind, shared by every instance (Hivemind `libra/`, start at `LIBRA.md`).
Owner (2026-10-27): an instance may hold a feature others lack; sharing every feature across instances is the long-run goal.
Owner (2026-10-27): Whisper runs on Fedora only; Fedora makes every Whisper output available to Libra instances on other machines.
Clones: Fedora `~/Documents/Coding/Libra`, Mac `~/Developer/Libra`.
Owner (2026-10-27): course calendar workers (`course_extract`, `course_events`, `course_schedule`, `course_office_hours`, `course_screenshot`, `course_watch`) stay in SemAI.
Owner (2026-10-27): Libra absorbs vault `Tools/librarian.py` (search, catalog, maps, readings); one librarian, not two.
Owner (2026-10-27): start and finish Libra as soon as possible; no wait for the 11-04 and 11-05 midterms.

## Carryover
L5 done 2026-10-27 (autofire LX1-LX4): Libra `b597c6b`; SemAI `f0f50f4`, `6e59220`; Hivemind skill `2fb67a0`; vault `4056b3a` deleted `librarian.py` and its tests.
Kept: vault `Tools/tests/fixtures/ece108_quiz1/` (exam-prep P1 fixture, cited in vault `AGENTS.md`).
Next: L6, SemAI sweep (its M2): delete moved modules (`lecture_fetch`, `lecture_whisper`, `lecture_docs`, `notes/*`), dead Settings, `[all]` deps; trace `web/notes.py` users of `notes/*` first.
Summary 2026-10-27 (lx1, autofire): `_run_command` prints a one-line fedora-extra error, exit 2; `main` bad settings exit 2; 2 dispatches, 0 fix rounds, 325 pass.
Seam: `test_fetch_commands_report_missing_extra` child loads real `.config/libra.env`; a bad machine config fails it with the settings message (unverified elsewhere).
L0 and L1 done 2026-10-27: verbatim port (owner-ledgered), then 7 dispatches (3 fix rounds); 255 pass; `uv run pytest -q`.
L2 done 2026-10-27: `librarian.py` split by script (verbatim blocks, generated imports), tests ported; 13 live commands byte-identical old vs new; 296 pass.
L3 done 2026-10-27: `login` (verbatim port), `fetch`, `whisper`, `read`, `export`, `status`; sops key fallback for `read`; units in `deploy/`; 322 pass.
L4 2026-10-27: F1 fixed (`3dc8808`, 323 pass); installed on Fedora (`.[fedora]`) and Mac (core); state reflink-copied from SemAI; `.config/libra.env` on both.
L4 passed: Fedora `status`, cached `read`, `search`, `catalog`; Mac `search`, `catalog`, `map`, and `read` via `ssh dyne@fedora libra read`.
L4 fetch passed 2026-10-27 20:11 PDT: owner `libra login`, then fetch: ECE 158A 10-27 (vault `ba66115`), map `9dbba8b`; ECE 108 10-27 queued for Whisper.
Mac login command: `ssh -t -L 9222:127.0.0.1:9222 dyne@fedora /home/dyne/.local/bin/libra login`; a bare `~` expands on the Mac.
Seam: login looks stuck to the owner; it polls every 15 s, saves, then fetches before printing; owner reported "doesn't catch" though it saved.
Trap: `libra read` paths are vault-relative (`ECE 108/Discussion/x.pdf`), not course-relative; a course-relative path answers `unknown_source`.
Trap: TriAPI `llm_client.is_deepseek_peak_hours` fails to import from a bare `python3 -c`; check the clock (UTC 01-04, 06-10 weekdays) instead.
Incident (2026-10-27): a smoke `libra fetch` with empty scratch state rewrote vault maps (commit `6ef0f5f`) and readings; reverted (`49486a3`), SemAI re-exported 46 readings.
Guard since then: `fetch` and `export` refuse without `lecture_reads/source_index.json` in the state dir (`commands._cache_ready`).
Trap: never smoke-test fetch-side commands with `LIBRA_VAULT_DIR` on the real vault; use a scratch vault.
Seam: `whisper` and `fetch` take no lock against each other; concurrent vault commits can fail on the git index lock and retry next run.
Seam: `cmd_whisper` counts only successes; a failing job ends the loop early (logged), rest waits for the next night.
Seam: `search.py` and `mapview.py` import private `_select_courses` from `catalog.py`; promote it to `library.py` when next touched.
Seam: `library.EXCLUDED_DIRS` and `sources.NON_COURSE_DIRS` are two lists of non-course folders; merge when next touched.
Owner (2026-10-27): owner uses Gemini for midterm prep; Libra work runs ahead without waiting for exams.
Trap: renaming a ported file breaks cross-test imports (`from test_sources import ...`); grep `^from test_` after any test rename.
Trap: tests must pass `LIBRA_STATE_DIR` to `Settings.load`; the default creates the real `~/.local/state/libra`.
Trap: the Mac has no ledger-check hook and no dispatch setup; Libra code changes happen on Fedora only.
Seam: `lecture_poll.py` name is historical (no polling left); rename when next touched.
Seam: ruff F811 on `tests/test_sources_ranges.py` `fake_chat` is a pytest-fixture false positive, inherited from SemAI.
Seam: `lecture_docs.py` temp dir prefix still reads `semai-lecture-` (cosmetic).
Owner (2026-10-27): Libra alone fetches and runs Whisper from now; SemAI's login is never refreshed; `libra login` is the only sign-in.
Done 2026-10-27 20:20 PDT: Libra timers enabled (fetch 23:30, Whisper 01:00); SemAI's hourly poll logs expired-login warnings until L5 removes it.
Seam: `test_vault_commands_run_without_fedora_extra` child reads real `.config/libra.env`, but `--root` skips `Settings.load`; harmless today (verified).
Last audit: 2026-10-27 wrap-up (audited through `24f3b15`; 0 new findings; LX4 docs only).

## Findings
F6 [low · 1 · 2026-10-27] `cli.py` `_run_command`: any ImportError, even a real `libra.*` bug on Fedora, prints "needs the fedora extra"; re-raise unless third-party (verified by code).
F2 [low · 1 · 2026-10-27] `commands.py` `cmd_fetch`: exit 3 (expired) and 1 (partial errors) mark `libra-fetch.service` failed nightly; `status` shows login age only (verified by code).
F3 [low · 1 · 2026-10-27] `config.py` `_REPO_ROOT`: `.config/libra.env` and `.secret` resolve from `__file__`; a non-editable install silently loses both (suspected).

## Plan: migration from SemAI (Claude, 2026-10-27; approved by owner 2026-10-27)
Goal: Libra owns transcript fetch, Whisper, readings, maps, search and page reads; SemAI and vault `Tools/librarian.py` keep none of it.
Done means: Libra timers fetch on Fedora, `libra search` runs on Fedora and Mac, SemAI academic code and `librarian.py` deleted.

### Source inventory (SemAI, verified 2026-10-27)
Fetch: `workers/lecture_fetch.py` 567, `lecture_whisper.py` 127, `lecture_poll.py` 237, `adapters/cli.py` `cmd_podcast_login`.
Readings: `notes/sources.py` 449, `textbooks.py` 595, `source_pages.py` 105, `reading_export.py` 203, `workers/lecture_docs.py` 383.
Maps: `notes/lecture_align.py` 452, `lecture_map.py` 427. Agent path: `web/study.py` 254, `adapters/study_cli.py` 246.
Vault: `Tools/librarian.py` 1214 (search, catalog, map confirm), `Tools/tests/` (unittest), `Tools/maps`, `Tools/readings`.
Tests to port: SemAI `tests/test_lecture_*`, `test_notes_*`, `test_reading_export`, `test_gemini_provider`, `test_obsidian_vault` (relevant parts).
Settings read: `obsidian_academic_vault_dir`, `state_dir`, `gemini_api_key`, `ocr_model`, `openrouter_api_key`, `db_path` (only for CourseStore and TaskStore meta).
Third-party: `httpx`, `pillow`, `playwright`, `faster-whisper`, `numpy`; tools `pdftotext`, `pdftoppm`, `soffice` (Fedora). Librarian search is stdlib only.

### Design
Package: uv project, `src/libra`, `requires-python >=3.12`; Mac has uv 0.11.2 with Python 3.12 and 3.13 (verified 2026-10-27).
Extras: core is stdlib only (search, catalog, map); extra `fedora` adds fetch, Whisper, Gemini reads, export dependencies.
Install: `uv tool install --editable '.[fedora]'` on Fedora, `uv tool install --editable .` on the Mac; console script `libra`.
CLI: `libra login`, `fetch`, `whisper`, `read`, `export`, `search`, `catalog`, `map`, `status`; one entry point replaces `omll podcast-login` and `omll-study`.
Login then fetch: `libra login` saves state and fetches at once (ADR-0041 P4 option a); the hourly poll goes.
Schedule: user timers on Fedora, `libra-fetch.timer` nightly catch-up, `libra-whisper.timer` 01:00 (drains queue until 06:00, today's `WHISPER_HOURS`).
Dropped by this: SemAI `CourseStore` meetings gating, `TaskStore` meta keys, the daemon tick; fetch already skips existing transcripts.
Wanted courses: vault course folders (`course_dir` rule plus `NON_COURSE_DIRS`); term from config `LIBRA_TERM` (e.g. `FA26`), set once per quarter.
Reads: `libra read` runs the Gemini page fetch in process under a file lock; replaces the socket, `JobRegistry`, and `web/body.py` helpers.
Mac: search, catalog, map run locally on the Drive vault; `read`, `fetch`, `export` go over `ssh -o BatchMode=yes dyne@fedora libra ...`.
Config: `Settings` slim dataclass from env plus gitignored `.config/libra.env`; time zone `LIBRA_TZ` default `America/Los_Angeles` replaces `event_tz`.
State: `~/.local/state/libra/` (btrfs `+C` not needed, no sqlite); holds podcast login state, `lecture_audio/`, `lecture_reads/` cache.
Ports with seams: `canonical_course_code` (from `memory/course_store.py`), `commit_paths` and `has_uncommitted_changes`, Gemini `chat` and its errors.
Librarian absorb: `librarian.py` splits into `libra/search.py`, `catalog.py`, `mapcli.py` under the 600-line file cap; its tests become pytest.
Exam prep: vault plan D1, D2, D7 (inventory, coverage, aliases) become Libra commands; `examprep.py` (D3 to D6) stays vault tutor code.
`examprep.py` imports Libra loaders via PEP 723 `[tool.uv.sources] libra = { path = "/home/dyne/Documents/Coding/Libra" }` (Fedora only, as planned).
Size guard: port SemAI `tests/test_size_guard.py` limits (600 lines a file, 100 code lines a function).

### Port method (owner signed off 2026-10-27)
Proposal: modules move by script (copy plus `semai.` to `libra.` import rewrite, no logic change); seam edits after go through TriAPI dispatch.
Why: retyping 6k verbatim lines through DeepSeek is slow, hits its 8192-token output cap, and adds defects (whole-file regeneration trap).
Gate: Libra gets the same pre-commit ledger hook; ported files enter the ledger through `dispatch-ledger-hand.sh`, which the owner runs.

### Phases (each a new session, ending with audit, docs, commit)
L0 scaffold: `pyproject.toml`, `.gitignore`, `tests/`, size guard, pre-commit hook, `.config/` template; `uv run pytest` green on Fedora and Mac.
L1 port: fetch, Whisper, readings, maps modules plus their tests by script; dispatch seam fixes (Settings, tz, course code, vault git, Gemini).
L2 absorb `librarian.py`: split and port its tests; outputs match the old tool on the live vault (`search`, `catalog`, `map` diff).
L3 glue by dispatch: `libra` CLI, `login` then fetch, `read` with lock, timer units in `deploy/`.
L4 live: copy SemAI state to Libra state; `libra fetch` on real courses, one `read`, `search` on both machines; SemAI still running.
L5 cutover: SemAI dispatch removes the lecture tick, study socket, `omll-study`, `podcast-login`; update Hivemind `academic-study` skill (timers enabled early, 2026-10-27).
L5 also: amend vault `AGENTS.md` tool lines, then delete `Tools/librarian.py` and `Tools/tests/` for it, after L4 checks pass on both machines.
L6 SemAI sweep (its M2): delete the moved modules and tests, dead `Settings` fields, `[all]` deps no other code uses; F39, F136, F142, F147, F148 move here.
Overlap rule (superseded 2026-10-27): Libra alone fetches; SemAI's expired login makes its poll a no-op; both skip existing transcripts if it ever runs.
Irreversible last: SemAI state files (`ucsd-podcast-state.json`, `lecture_reads/`, `lecture_audio/`) are deleted only after Libra runs a week clean.

### Owner answers (2026-10-27)
Owner (2026-10-27): login-expiry push dropped; UCSD login is always manual with the owner; `libra login` reports the result at once.
Owner (2026-10-27): Libra gets its own sops `.secret/secrets.json`; `GEMINI_API_KEY` and `OPENROUTER_API_KEY` share SemAI's key values.
Owner (2026-10-27): port method signed off: script copy with import rewrite, owner runs `dispatch-ledger-hand.sh`, seam edits and new code dispatched.

## File and directory index
`AGENTS.md` this file. `pyproject.toml` (uv; core stdlib, extra `fedora`), `.sops.yaml`, `.secret/secrets.json` (gitignored, Fedora only).
`src/libra/config.py`: `Settings` frozen dataclass, `Settings.load(env)` from env plus `.config/libra.env`; keys `LIBRA_*`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`.
`src/libra/lecture_fetch.py` podcast.ucsd.edu to transcripts; `lecture_whisper.py` Whisper queue; `lecture_poll.py` `wanted_courses`, `run_fetch_job`, `run_whisper_job`.
`src/libra/lecture_docs.py` page render and Gemini read cache; `sources.py`, `textbooks.py`, `source_pages.py`, `reading_export.py` readings and exports.
`src/libra/lecture_align.py`, `lecture_map.py` lecture-to-slide maps; `gemini.py` chat client; `errors.py` `ProviderError`; `courses.py` `canonical_course_code`.
`src/libra/library.py` course discovery, transcript and page loaders; `search.py`, `catalog.py`, `mapview.py` subcommands; `cli.py` `libra` entry (`--root` or `LIBRA_VAULT_DIR`).
`src/libra/commands.py` fetch-side handlers and exit codes (3 = login expired); `read.py` `read_pages` (flock `read.lock`); `login.py` UCSD DevTools sign-in.
`deploy/` user units: `libra-fetch` 23:30 nightly, `libra-whisper` 01:00 to 06:00; enabled 2026-10-27, installed copies in `~/.config/systemd/user/`.
`src/libra/obsidian_vault.py`: vault git `commit_paths`, `has_uncommitted_changes`. `tests/`: pytest, `test_size_guard.py` (600 lines a file, 100 a function).
