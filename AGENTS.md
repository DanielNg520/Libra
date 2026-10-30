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
Owner (2026-10-29): agents never run `login`, `fetch`, `export`, `whisper`, `read --fetch` unasked; enforced in `cli._agent_refusal`; the agent sets `LIBRA_OWNER_OK=1` itself when the owner asks or confirms.
Owner (2026-10-29): agy (Gemini 3.8 Flash) wields Libra too; it loads Hivemind `academic-study` from `~/.gemini/config/skills/` (symlink, Fedora and Mac).
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
Owner (2026-10-29): both queued, textbook `read` route first, then further reading; each plans before code in its own session.

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
Summary 2026-10-30 (FR plan pass, autofire): traced notes; options a and b written as `FR plan` lines; no code; ends in `Ask owner: FR option a or b?`.
FR sync: Libra `a915692` pushed, Mac pulled to `a915692`.
Summary 2026-10-30 (TR, autofire): plan closed all gaps, built, 425 pass; no Gemini spent; owner live check: one `read --chapter ... --fetch` slice (25 pages max).
TR sync: Libra `1240b1a` pushed, Mac pulled to `1240b1a`; Hivemind skill `8ccddee` (`--chapter`, `--printed` line).
Next (owner, 2026-10-29): TR textbook `read` route, then FR further reading (lines "TR", "FR" below); open check: next `libra login` saves without a manual `CourseList.aspx` tab (F15).
Owner (2026-10-29 ~22:05 PDT): TR (plan then build) and FR (plan pass, ends in `Ask owner`) autofire 2026-10-30 03:04 PDT; prompts `~/.cache/semai-autorun/prompt_{tr,fr}.md`.
Pending (irreversible, ask owner first): delete SemAI state files (`ucsd-podcast-state.json`, `lecture_reads/`, `lecture_audio/`) after a clean Libra week, earliest 2026-11-03.
Mac login command: `ssh -t -L 9222:127.0.0.1:9222 dyne@fedora /home/dyne/.local/bin/libra login`; a bare `~` expands on the Mac.
Mac OCR: `ssh -o BatchMode=yes dyne@fedora /home/dyne/.local/bin/libra ocr - --notes < image.png`; the image travels on stdin.
Seam: login looks stuck to the owner; it polls every 15 s, saves, then fetches before printing.
Guard: `fetch` and `export` refuse without `lecture_reads/source_index.json` in the state dir (`commands._cache_ready`); never smoke-test on the real vault.
Kept: vault `Tools/tests/fixtures/ece108_quiz1/` (exam-prep P1 fixture, cited in vault `AGENTS.md`).
Summary 2026-10-29 (F3, F16, F17 closed): 6 dispatches (4 re-prompts: display-indented excerpts, one misleading name), 394 pass, 6 mutants caught.
F16 rule: a failed `book_map` touches `<sha>.failed` beside the cache; `ensure_book_maps` skips it for `FAILED_RETRY_S` (24 h); never name it `.json` (`_books_mtime` globs those).
F17 rule: an ssh-only refusal (no agent var) adds the `ssh -t` hint; `libra --help` names `ssh -t` or `LIBRA_OWNER_OK=1`.
Trap: Claude Code sets `AI_AGENT` as well as `CLAUDECODE`; a live guard test must unset both.
Trap: dispatch excerpts go in fences at real indentation; DeepSeek copies a display indent into SEARCH (4 misses, 2026-10-29).
Summary 2026-10-29 (F13 done, attended): new textbooks get chapter maps nightly; 7 dispatches (4 re-prompts), 390 pass; 6 mutants caught; live build matched cache.
F13 rule: `lecture_map.ensure_book_maps` runs per course before `fingerprint` in `write_maps`; `book_map` builds uncached books only; keys load lazily, once.
F13 why first: a failed build leaves no cache, so the next run retries; a build changes `books` mtime, so the map rebuilds.
F13 units: both services set `Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin`; without it `sops` is missing and keys never load (verified).
F13 live 2026-10-29: scratch rebuild of ECE 158A `978-3-031-79281-6.pdf` via unit env: 1 Gemini call, 16 s; equal to the cached map.
Owner (2026-10-29): keep `expand_books` (no production caller); base for a textbook `read` route.
Owner (2026-10-29): a scanned textbook, once identified, is never retried (no weekly vision call).
Scanned rule: `load_cached_map` retries an empty map weekly only if searchable; a scanned map (`searchable` false) is final; a new copy has a new sha.
Seam: fetch and Whisper can build the same new book at once; double call, last atomic write wins; harmless.
Guard: tests/test_lecture_map.py autouse `_no_real_book_map` fails any test that reaches a real `book_map`.
Trap: dispatch excerpts must mark gaps between non-adjacent code; two SEARCH misses came from excerpts shown as adjacent (2026-10-29).
Summary 2026-10-29 (agent readiness, attended): `--help` text on every flag; agent guard; agy skill link; 5 dispatches (2 re-prompts), 384 pass; mutation-checked.
Agent guard: refuses (exit 2) under `CLAUDECODE`, `ANTIGRAVITY_AGENT`, `AI_AGENT`, or `SSH_CONNECTION` without a TTY; timers and owner `ssh -t` pass (verified live, Mac ssh both ways).
Trap: Claude Code `!libra fetch` runs with `CLAUDECODE` set and is refused; prefix `LIBRA_OWNER_OK=1`.
Seam: the guard stops careless agents, not deliberate ones; an agent can still set `LIBRA_OWNER_OK=1`; agent harnesses beyond Claude Code and agy are unchecked.
F14 fix: `read_pages` runs `reconcile_index` (outside the lock) when cached pages are missing; re-reads only if it adopted.
F7 fix: recitation-retry pages carry `lecture_docs.PARAPHRASE_NOTE` under each `### Page N`; earlier cached reads stay unmarked (no re-read).
Closed 2026-10-29: F8 delete path has no production caller (`expand_books` passes `delete=False`); F9 hashing all 10 textbooks takes 0.07 s.
Owner (2026-10-29): F13 approved, "important, do it optimally and efficiently"; done `85d9b90`.
Owner (2026-10-29): F3 keep repo-relative `.config/`, `.secret/`; editable installs only; `config._read_config_env` warns with the path when `libra.env` is unreadable.
Ask owner: merge `library.EXCLUDED_DIRS` and `sources.NON_COURSE_DIRS`? Contents differ; a union hides `Concepts`, `Archive` from catalog.
Owner (2026-10-29): approved the F12 content-adoption design ("go for it"), replacing options (a) and (b); built as `8c30b71`.
Guard: `test_reconcile_never_runs_under_index_lock` (`tests/test_read.py`) fails if `read_pages` reconciles while holding `index_lock`.
F12 rule: `sources._adopt_moved` re-keys a missing or stale-mtime entry to a same-size, same-sha entry (own or same-course orphan); never takes a listed rel.
F12 callers: `read_sources` (caller holds the lock) and `reading_export.write_readings` via `reconcile_index`, which takes `index_lock` itself.
Trap: `index_lock` (`read.lock`, flock) is not re-entrant; never call `reconcile_index` while holding it (`read_pages` fetch path).
Seam: export, and a plain `read` with missing pages, wait on `index_lock` while a `libra read --fetch` runs (up to 900 s).
Seam: `refresh_exports` builds maps before readings, so a renamed deck reaches `Tools/maps/` one export later.
Seam: default prompt on an image without handwriting gets null content; `ocr` prints `no content (finish_reason stop)`, exit 1, not "returned no text".
Seam: OCR has no OpenRouter cap fallback (SemAI parity); a Gemini cap hit exits 1; `read` alone falls back.
Trap: Fedora's own `known_hosts` lacks `fedora`; `ssh dyne@fedora` from Fedora fails host-key checks; test the ssh path from the Mac.
Trap: Mac non-interactive ssh lacks `/opt/homebrew/bin`; prefix `export PATH=$HOME/.local/bin:/opt/homebrew/bin:$PATH` before `uv`.
Owner (2026-10-28): the homework-precedent rule (Hivemind `libra/homework-workflow.md`) must be built into Libra deterministically, not left to agent memory.
SN done 2026-10-29 (no code): rule in skill, Hivemind `libra/homework-workflow.md`, vault `AGENTS.md`; 19 vault files renamed, 1 duplicate deleted, links verified.
TR done 2026-10-30 (autofire): `libra read --chapter N|TITLE`, `--printed N|A-B`; 7 dispatches (2 fix rounds), 425 pass, 5 mutants caught; live PRML ch 3 = PDF 157-198.
TR plan (Claude, 2026-10-30): `libra read` gains `--printed N|A-B` and `--chapter N|TITLE`, mutually exclusive with `--pages`; additive, `--pages` contract unchanged.
TR plan printed: each end maps via `textbooks.page_labels(pdf_page_texts)` plus `locate`; no vote answers `printed_page_unknown`; live PRML printed 137 to PDF 157, 2 s.
TR plan chapter: cached map only (`load_cached_map`, sha from index or `sha256_file`), never builds, no Gemini; no usable map answers `no_chapter_map`.
TR plan chapter match: parts merge by base title; digits pick the Nth chapter, appendices excluded; else casefold title substring, exact title breaks ties.
TR plan chapter errors: `unknown_chapter` lists all titles, `ambiguous_chapter` the matching ones, in an additive `chapters` key; answers add `chapter` (title, first, last).
TR plan fetch: unchanged `MAX_FETCH_PAGES` 25 on missing pages; a whole-book or long-chapter `--fetch` answers `too_many_pages` (verified by code); fetch in `--pages` slices.
TR plan reuse: `expand_books` not reused (builds maps with Gemini, rewrites the index, runs copy checks); kept per owner 2026-10-29; `find_chapter` lives in `read.py` (`textbooks.py` at 595 lines).
TR plan help: `--pages` says PDF page; `--printed` says book numbering; `--chapter` says map order; `--fetch` names the 25-page cap; module usage line updated.
TR plan dispatches: `read.py`, `commands.py` (`cmd_read` chapter, printed; error `chapters`), `cli.py`, `tests/test_read.py`, `tests/test_commands.py`; fakes only.
Seam (TR): `--printed` fails (`printed_page_unknown`) on about the last 20 printed pages (no labels ahead) and on roman front matter; verified live (PRML 738).
Seam (TR): chapter numbers follow map order; a map opening with a part heading (BDA `Background`) shifts them; the answer names the title read.
Seam (TR): `--printed` runs `pdftotext` over the whole book per call (about 2 s); `_resolve_printed_pages` leaves `int | None` unnarrowed for mypy.
Ask owner: delete `sources.expand_books`, `_is_book_rel`, `textbooks.check_copies` and their tests? TR does not use them; no other caller (verified 2026-10-30).
FR goal: trimmed notes end with further-reading sources (SemAI ADR-0030 decision 7, owner 2026-10-11); no Libra base exists.
FR plan (Claude, 2026-10-30) trace: no rule trims topics or adds further reading; vault `AGENTS.md` note spec governs note shape; skill and Hivemind `libra/` defer to it.
FR plan trace: vault line "Do only what is asked: no extra ... sections" blocks an unasked further-reading section; either option amends that line in the same change.
FR plan trace: decision 7's trim half has no rule either; both options add "trim to what syllabus and lectures cover, then list further reading".
FR plan trace: Libra's only network code is `lecture_fetch.py` and `gemini.py` (httpx, extra `fedora`); core is stdlib, so a Mac client needs `urllib`.
FR plan (a): rule lines in vault note spec, one skill pointer, Hivemind `libra/study-note-style.md`; the agent searches itself (Claude WebSearch, agy Google search).
FR plan (a) reuse: both agents already search the web on both machines; no code, no dependency, no key; size about 4 doc lines in 3 files.
FR plan (a) sources: course textbook chapters first, then other textbooks, review papers (DOI), university course notes; never blogs, forums, AI pages, paywall-only links.
FR plan (a) format: section `Further reading` at the note end, 3 to 5 items (title, authors, year, link, one-line why); each link opened before listing.
FR plan (a) failure modes: invented or dead links (open-before-list rule), agy and Claude drift apart, no test enforces it; owner spots misses in use.
FR plan (b): `libra further <terms> [--json]`, new `scholar.py`; Crossref, arXiv, optional OpenAlex behind one `_send` host allowlist; dedupe by DOI; label peer-reviewed or preprint.
FR plan (b) reuse: port SemAI ADR-0030 Stage 4 `ScholarClient` contract (no code exists to port); CLI and `--json` packet follow `precedents.py`.
FR plan (b) live 2026-10-30: Crossref and arXiv keyless 200 under 1 s; OpenAlex keyless now shares a $0.10 daily per-IP budget; its free key needs an email.
FR plan (b) failure modes: off-topic hits on course terms (SearXNG failed so 2026-10-11), arXiv 1 call per 3 s, API drift; tests on fakes only.
FR plan (b) size: about 250 lines plus tests, 5 to 8 dispatches; the agent still picks and judges items, so (b) needs the (a) rule lines too.
FR plan privacy: either option sends topic terms only, never note text, transcripts or owner data; Google Scholar excluded (decision 7).
FR plan recommendation (Claude): (a) now; build (b) only if (a) lists bad or invented sources in use; (b) is (a) plus a client.
Owner (2026-10-30): FR option (a) now; done 2026-10-30: vault note spec `1f0af3c`, skill and Hivemind `study-note-style.md` `1a51e50`.
Owner (2026-10-30): FR option (b) `libra further` client logged as a polish feature; build only after (a) proves short in use.
SN decisions:
Owner (2026-10-29): agent-written homework solutions end in `solution`: `Problem M solution.md`, `Problem M a solution.md`, `homework N solution.md`; in `Study notes/homework N/`.
Owner (2026-10-29): agent solutions stay separate; never precedents; tier 1 stays posted solutions (`Homework/`).
Owner (2026-10-29): enforcement is a rule line only (skill `academic-study`, Hivemind `libra/homework-workflow.md`, vault `AGENTS.md`); no Libra code.
Owner (2026-10-29): existing solution files renamed to the scheme; no reversal backup wanted; `study_note_cmos_pre_problem3.md` duplicate deleted.
HP plan (Claude, 2026-10-29; approved by owner 2026-10-29): `libra precedents --course C <terms>`, new `precedents.py` on search primitives; stdlib, runs on Mac.
HP tiers, fixed order: 1 solutions (`Homework/` names matching `sol|solution|key|answer`), 2 discussion (`Discussion/` plus `-DI` transcripts), 3 lectures (`Slides/` plus lecture transcripts).
HP output: per tier hits (path, page or `[mm:ss]`, excerpt), "none found" when empty; `--json`; OR terms default, 5 per tier; exit 1 when all empty.
HP why a command, not a `search` flag: tiering, order and the packet format would bend `search`'s output contract.
HP trace (2026-10-29): `Homework/` is exported; only ECE 158A posts solutions (`HW1_sol`); below-50-median-word PDFs and images are never exported.
Owner (2026-10-29): HP enforcement is the `academic-study` skill's mandatory first step only; no hooks.
Owner (2026-10-29): HP lists unexported folder files per tier (agent reads them directly); export rules unchanged.
Owner (2026-10-29): owner's own submissions (`*submission*`) are never precedents; only posted solutions form tier 1.
HP done 2026-10-29: `precedents.py`, `cli.py` wiring, `tests/test_precedents.py`; 10 dispatches (5 re-prompts), 404 pass, 7 mutants caught.
HP same change: `select_courses` now in `library.py`; `catalog.folder_entries`, `search.print_*` and `search.rank_hits` public; skill section "Homework help" added.
HP live 2026-10-29: ECE 158A store-and-forward puts `HW1_sol` first; ECE 108 lists Discussion 4 and three PNGs as unsearched.
Seam: solution names need a `sol|solution|key|answer` token; a solution file named otherwise (e.g. `hw1_ans.pdf`) lands in no tier.
Seam: `precedents.tier_of` repeats the folder names held in `_TIER_TABLE`; derive it from the table when next touched.
Trap: DeepSeek whole-file replies for new modules needed 3 rounds (name slicing, raw course key, JSON header); prefer a skeleton then small edit dispatches.
Seam: `test_fetch_commands_report_missing_extra` child loads real `.config/libra.env`; a bad machine config fails it with the settings message (unverified elsewhere).
Trap: `libra read` paths are vault-relative (`ECE 108/Discussion/x.pdf`), not course-relative; a course-relative path answers `unknown_source`.
Trap: TriAPI `llm_client.is_deepseek_peak_hours` fails to import from a bare `python3 -c`; check the clock (UTC 01-04, 06-10 weekdays) instead.
Trap: never smoke-test fetch-side commands with `LIBRA_VAULT_DIR` on the real vault; use a scratch vault.
Seam: `whisper` and `fetch` take no lock against each other; concurrent vault commits can fail on the git index lock and retry next run.
Seam: `cmd_whisper` counts only successes; a failing job ends the loop early (logged), rest waits for the next night.
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
Last audit: 2026-10-29 wrap-up (audited through `3758aee`; 2 new findings F16, F17).

## Findings
Trap: `LECTURE_NOTES_DIR = "Lecture notes"` is an output dir; a vault folder of that name (any case on the Mac) is never a source.
Owner (2026-10-28): option b, no new source folder: `Lecture Notes/` into `Slides/` root, superseded into `Slides/Outdated/`, duplicates collapsed; `In Class Problems/` into `Homework/`.
Owner (2026-10-28): Libra skips every `Outdated/` child folder; autofire step LN queued for 2026-10-29 03:05 PDT (`~/.cache/semai-autorun/prompt_ln.md`).

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
Mac: search, catalog, map run locally on the Drive vault; `read` over `ssh -o BatchMode=yes dyne@fedora libra ...`; owner-only commands need `ssh -t`.
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
`src/libra/lecture_align.py`, `lecture_map.py` lecture-to-slide maps (`ensure_book_maps` builds new textbook maps); `gemini.py` chat client; `errors.py` `ProviderError`; `courses.py` `canonical_course_code`.
`src/libra/library.py` course discovery (`select_courses`), transcript and page loaders; `search.py`, `catalog.py`, `mapview.py`, `precedents.py` (tiered homework precedents) subcommands; `cli.py` `libra` entry (`--root` or `LIBRA_VAULT_DIR`; `_agent_refusal` owner-only guard).
`src/libra/commands.py` fetch-side handlers incl. `cmd_ocr`, exit codes (3 = login expired, 4 = partial fetch); `ocr.py` OCR; `read.py` `read_pages` (flock `read.lock`, renamed-source adoption, `--chapter`, `--printed`); `login.py` sign-in.
`deploy/` user units: `libra-fetch` 23:30 nightly, `libra-whisper` 01:00 to 06:00; enabled 2026-10-27, installed copies in `~/.config/systemd/user/`.
`src/libra/obsidian_vault.py`: vault git `commit_paths`, `has_uncommitted_changes`. `tests/`: pytest, `test_size_guard.py` (600 lines a file, 100 a function).
