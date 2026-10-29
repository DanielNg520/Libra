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
Owner (2026-10-28): a partial fetch exits 4 (`EXIT_PARTIAL`); `libra-fetch.service` `SuccessExitStatus=4`; crash (1) and expired login (3) still fail the unit.
Owner (2026-10-27): Libra is its own project; every academic piece leaves SemAI for it, transcript fetch and Whisper included.
Owner (2026-10-27): the tutor and librarian tools also live in `~/Classes/Current` and Hivemind.
Owner (2026-10-27): remote `git@github.com:DanielNg520/Libra.git`; Libra runs on every machine (Fedora, Mac), not Fedora-only.
Owner (2026-10-27): Libra is modular; her memory lives in Hivemind, shared by every instance (Hivemind `libra/`, start at `LIBRA.md`).
Owner (2026-10-27): an instance may hold a feature others lack; sharing every feature across instances is the long-run goal.
Owner (2026-10-27): Whisper runs on Fedora only; Fedora makes every Whisper output available to Libra instances on other machines.
Clones: Fedora `~/Documents/Coding/Libra`, Mac `~/Developer/Libra`.
Superseded (owner, 2026-10-28): course calendar workers do not stay in SemAI; they go off with the transition, never ported here.
Owner (2026-10-27): Libra absorbs vault `Tools/librarian.py` (search, catalog, maps, readings); one librarian, not two.
Owner (2026-10-27): start and finish Libra as soon as possible; no wait for the 11-04 and 11-05 midterms.
Owner (2026-10-28): SemAI academic memory moved out; behaviour memory to Hivemind `libra/`, code and vault facts here.

## Vault and sources (moved from SemAI, 2026-10-28)
Agent behaviour memory (notetaker, homework, study notes, exam prep, term state) lives in Hivemind `libra/`; never here.
Owner (2026-10-24): decks in `<course>/Slides/`, sources in `<course>/Textbooks/` and `<course>/Readings/`; ECE 25 decks in `ECE 108/Readings/ECE 25/`.
Owner (2026-10-19): non-academic files go in `Current/Personal/`, a non-course folder.
Readings scope (owner, 2026-10-11): Discussion decks and `271.pdf` count; handouts and reference sheets excluded.
Owner (2026-10-11): page reads use Gemini until the $10 cap, then OpenRouter; only public material goes to Gemini (owner, 2026-10-12).
Owner (2026-10-26): readings export to vault `Tools/readings/`; maps live in `Tools/maps/`, rebuilt after each fetch; agents confirm pairs.
Trap: vault `Tools/` has no hooks; set `PYTHONDONTWRITEBYTECODE=1` when testing there, or `__pycache__` syncs to Drive.
Cleanup 2026-10-24: 174 writer files trashed (vault `d3fe20d`); restore from Fedora `~/.local/share/Trash`; manifest `~/.cache/spike-20261024/cleanup-manifest.txt`.
Idea: vector search could port SemAI `memory/indexer.py` (heading chunks, hash diff) and `retriever.py` `hybrid_search` (BM25 plus local vectors).
Next step is the owner's pick: further reading (owner, 2026-10-16) or a textbook `read` route.

### Incoming from SemAI (owner, 2026-10-28; plan before code)
Owner (2026-10-28): OCR comes to Libra: SemAI `adapters/ocr.py` `transcribe_image`, its prompts, `ocr_model`; reuse Libra `gemini.py` and `ocr_model`.
Owner (2026-10-28): `matplotlib`, `schemdraw` move from SemAI `[all]` to Libra; they draw study-note schematics and plots.
Owner (2026-10-28): `academic_writer`, `note_draft` (note drafts from text, photo, PDF) and the `courses` table also come here.
Owner (2026-10-28): order is Libra LM phases, then SemAI M2b, then SemAI M1 S3.
Trace (2026-10-28): SemAI `adapters/ocr.py` 46 lines; `academic_writer.py` 129, `note_draft.py` 201; `courses` table 4 rows (code, name, instructor, office hours, TAs, description, resources, term).
Trace: Libra `gemini.chat` already takes `reasoning_effort`; `ocr_model` exists (`LIBRA_READ_MODEL`); Mac has no Ollama (verified 2026-10-28).
Trace: `note_draft` needs Ollama, SemAI approvals and web search; `academic_writer` needs ghostwriter, SearXNG search, Notion; none exist in Libra.
LM1 OCR: `src/libra/ocr.py` (`transcribe_image`, handwriting and notes prompts) on `gemini.chat`; `libra ocr <image> [--notes]` prints text; extra `fedora`; Mac via ssh.
LM1 skips `CANVAS_OCR_PROMPT` (course workers go off) and the flyer prompt (mail goes off).
LM2 plot deps: new extra `plot` (`matplotlib`, `schemdraw`); install `.[fedora,plot]` on Fedora, `.[plot]` on the Mac; agents run it with the tool interpreter.
LM3 courses (Claude, 2026-10-28): rows become one vault note per course, `<course>/Course info.md`, by a one-off export; no table, no Libra code.
Owner (2026-10-28): `note_draft` and `academic_writer` fold into the agent notetaker: cleaning rules move to Hivemind `libra/`, workers deleted in M2b.
Owner (2026-10-28): Libra's agents are agy and Claude Code; model APIs only Gemini (reads, OCR), plus the OpenRouter cap fallback (kept, owner 2026-10-28).
Owner (2026-10-28): a light local model will later run on the Mac; revisit a local cleaner then, build nothing for it now.
LM4 (docs only): copy `note_draft` `_SYSTEM_PROMPT` rules (keep every line, `[?]`, separate additions section) into the Hivemind notetaker memory.
SemAI M2b done 2026-10-28 (one session, owner): OCR, plot deps, writers, course workers gone; SemAI `courses` tables dropped 2026-10-28 (owner).

## Carryover
Next session: HP plan (below), or F13 once the owner answers; open check: next `libra login` saves without a manual `CourseList.aspx` tab (F15).
Summary 2026-10-29 (findings sweep, attended): F7, F14 fixed; F8, F9 closed by measurement; 7 dispatches (4 re-prompts), 358 pass; mutation-checked.
F14 fix: `read_pages` runs `reconcile_index` (outside the lock) when cached pages are missing; re-reads only if it adopted.
F7 fix: recitation-retry pages carry `lecture_docs.PARAPHRASE_NOTE` under each `### Page N`; earlier cached reads stay unmarked (no re-read).
Closed 2026-10-29: F8 delete path has no production caller (`expand_books` passes `delete=False`); F9 hashing all 10 textbooks takes 0.07 s.
Closed 2026-10-29: F14 duplicates and re-hash parts; reads are content-keyed, so a duplicate costs a render, never a Gemini call.
Ask owner: F13 wiring loads sops keys in `fetch`, `export`, `whisper` (today only `read --fetch`, `ocr`); approve the secrets change?
Ask owner: F3 config home: keep repo-relative `.config/` (editable installs only) or move to `~/.config/libra/`?
Ask owner: merge `library.EXCLUDED_DIRS` and `sources.NON_COURSE_DIRS`? Contents differ; a union hides `Concepts`, `Archive` from catalog.
Summary 2026-10-29 (F15 fixed, attended): login sign-in check reads every frame (`page.frames`); 2 dispatches (1 re-prompt), 353 pass; new tests fail on old code.
F10 closed 2026-10-29: ECE 108 Lecture 09-24 is gone from podcast.ucsd.edu (probe, fresh login); cause of its `JSONDecodeError` unrecoverable.
Done 2026-10-29 09:43 PDT: owner login via Xubuntu; saved only after Claude navigated the tab to `CourseList.aspx` (F15); fetch added 2 transcripts (vault `1074c8d`).
Owner (2026-10-29): approved the F12 content-adoption design ("go for it"), replacing options (a) and (b); built as `8c30b71`.
Mac check passed 2026-10-29 09:47 PDT: `libra search "CIDR" --course "ECE 158A"` returns `Lec7-IP-Addressing.pdf` pp. 22, 23, 28.
Guard: `test_reconcile_never_runs_under_index_lock` (`tests/test_read.py`) fails if `read_pages` reconciles while holding `index_lock`.
Summary 2026-10-29 (F12 done, attended): content-matched index adoption; 7 dispatches (3 fixes), 351 pass; live export adopted 8 entries (158A decks, 271A HW2).
F12 rule: `sources._adopt_moved` re-keys a missing or stale-mtime entry to a same-size, same-sha entry (own or same-course orphan); never takes a listed rel.
F12 callers: `read_sources` (caller holds the lock) and `reading_export.write_readings` via `reconcile_index`, which takes `index_lock` itself.
Trap: `index_lock` (`read.lock`, flock) is not re-entrant; never call `reconcile_index` while holding it (`read_pages` fetch path).
Seam: export, and a plain `read` with missing pages, wait on `index_lock` while a `libra read --fetch` runs (up to 900 s).
Seam: `refresh_exports` builds maps before readings, so a renamed deck reaches `Tools/maps/` one export later.
Summary 2026-10-29 (LN done, attended): script after-check fixed, 0 of 27 missing; links rewritten (6), export, Drive, docs verified; F11 closed.
Summary 2026-10-28 (F2, F6, attended off-peak): fetch exit 4 on partial errors; `_run_command` re-raises `libra.*` ImportErrors; 5 dispatches (1 fix round), 339 pass; unit reloaded.
L5 done 2026-10-27 (autofire LX1-LX4): Libra `b597c6b`; SemAI `f0f50f4`, `6e59220`; Hivemind skill `2fb67a0`; vault `4056b3a` deleted `librarian.py` and its tests.
Kept: vault `Tools/tests/fixtures/ece108_quiz1/` (exam-prep P1 fixture, cited in vault `AGENTS.md`).
L6 done 2026-10-27 (autofire): SemAI deleted lecture workers, `notes/`, `whisper_model`, `faster-whisper`, `numpy`; F39, F136, F148 moved here.
LM1 done 2026-10-28: `libra ocr IMAGE|- [--notes] [--mime T]`; 4 dispatches plus 2 fixes, 338 pass; live on Fedora path, Fedora stdin, Mac via ssh stdin.
Mac OCR: `ssh -o BatchMode=yes dyne@fedora /home/dyne/.local/bin/libra ocr - --notes < image.png`; the image travels on stdin.
Seam: default prompt on an image without handwriting gets null content; `ocr` prints `no content (finish_reason stop)`, exit 1, not "returned no text".
Seam: OCR has no OpenRouter cap fallback (SemAI parity); a Gemini cap hit exits 1; `read` alone falls back.
Trap: Fedora's own `known_hosts` lacks `fedora`; `ssh dyne@fedora` from Fedora fails host-key checks; test the ssh path from the Mac.
LM2 done 2026-10-28 (`7b5b1bc`): extra `plot`; Fedora `.[fedora,plot]`, Mac `.[plot]`; both import matplotlib 3.11.2, schemdraw 0.23.
Trap: Mac non-interactive ssh lacks `/opt/homebrew/bin`; prefix `export PATH=$HOME/.local/bin:/opt/homebrew/bin:$PATH` before `uv`.
LM3 done 2026-10-28: `Course info.md` in `Current/ECE 108`, `158A`, `271A` (vault `8d77089`) and `~/Classes/ECE 253/` (no git).
LM4 done 2026-10-28: Hivemind `libra/jotting-cleanup.md` (`250c013`). SemAI M2b done 2026-10-28: SemAI holds no academic feature.
Owner (2026-10-28): the homework-precedent rule (Hivemind `libra/homework-workflow.md`) must be built into Libra deterministically, not left to agent memory.
Next (new session): HP plan, then dispatch: Libra returns course precedents for a problem before any agent explains it.
HP reuse: `libra search` already scopes `--kind lecture|discussion` and `--in transcripts|readings|textbooks`; extend it, no new index unless homework solutions are unindexed.
HP open: are posted homework solutions in `<course>/Homework/` covered by `readings` export? Trace first.
HP open: fixed order (solutions, discussion, lecture examples), output a precedent packet (source path, excerpt, notation); empty packet says so.
HP open: enforcement: Hivemind `academic-study` skill makes the call a mandatory first step; check whether a hook can gate it.
State-file deletion waits a clean week.
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
Owner (2026-10-27): Libra alone fetches and runs Whisper from now; SemAI's login is never refreshed; `libra login` is the only sign-in.
Done 2026-10-27 20:20 PDT: Libra timers enabled (fetch 23:30, Whisper 01:00); SemAI's hourly poll logs expired-login warnings until L5 removes it.
Seam: `test_vault_commands_run_without_fedora_extra` child reads real `.config/libra.env`, but `--root` skips `Settings.load`; harmless today (verified).
Last audit: 2026-10-29 wrap-up (audited through `8c30b71`; LM1, LM2, F2, F6, LN, F12; 2 new findings F13, F14).

## Findings
Trap: `LECTURE_NOTES_DIR = "Lecture notes"` is an output dir; a vault folder of that name (any case on the Mac) is never a source.
Owner (2026-10-28): option b, no new source folder: `Lecture Notes/` into `Slides/` root, superseded into `Slides/Outdated/`, duplicates collapsed; `In Class Problems/` into `Homework/`.
Owner (2026-10-28): Libra skips every `Outdated/` child folder; autofire step LN queued for 2026-10-29 03:05 PDT (`~/.cache/semai-autorun/prompt_ln.md`).
F13 [medium · 2 · 2026-10-29] `sources.py` `expand_books`: only builder of textbook chapter maps, no production caller; new textbooks never reach lecture maps; skips `index_lock` (verified).
F13 plan: call `expand_books` per course before `write_maps` in `lecture_poll._refresh_maps`, lock inside it; maps of all 10 current books are cached.
F3 [low · 2 · 2026-10-27→2026-10-29] `config.py` `_REPO_ROOT`: `.config/libra.env` and `.secret` resolve from `__file__`; a non-editable install silently loses both (verified by code trace).

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
`src/libra/lecture_docs.py` page render and Gemini read cache; `sources.py` (also `index_lock`, `reconcile_index`), `textbooks.py`, `source_pages.py`, `reading_export.py` readings and exports.
`src/libra/lecture_align.py`, `lecture_map.py` lecture-to-slide maps; `gemini.py` chat client; `errors.py` `ProviderError`; `courses.py` `canonical_course_code`.
`src/libra/library.py` course discovery, transcript and page loaders; `search.py`, `catalog.py`, `mapview.py` subcommands; `cli.py` `libra` entry (`--root` or `LIBRA_VAULT_DIR`).
`src/libra/commands.py` fetch-side handlers incl. `cmd_ocr`, exit codes (3 = login expired, 4 = partial fetch); `ocr.py` OCR; `read.py` `read_pages` (flock `read.lock`, adopts renamed sources); `login.py` sign-in (every frame).
`deploy/` user units: `libra-fetch` 23:30 nightly, `libra-whisper` 01:00 to 06:00; enabled 2026-10-27, installed copies in `~/.config/systemd/user/`.
`src/libra/obsidian_vault.py`: vault git `commit_paths`, `has_uncommitted_changes`. `tests/`: pytest, `test_size_guard.py` (600 lines a file, 100 a function).
