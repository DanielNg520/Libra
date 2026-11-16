# 0002 – Self study moves from SemAI to Libra

**Status:** Accepted; L1 to L4 in code; L4 repointed docs and deleted SemAI card code and the SemAI `anki` dependency (2026-11-16).
- Dry run: `cards.preview_cards` reuses `_done_lessons` and a split-out `_item_sources`; `_item_notes` behaviour unchanged.
- `config._read_sops_secrets(path, keys)` takes a key list; `load_secrets` fills four secrets and skips sops only when all four are set.
- `tests/conftest.py` leaves `_read_config_env` real in `test_config.py`, which tests that reader.
- `tests/test_study_cards.py` keeps the 21 card tests plus `test_week_lock_excludes_others`, and adds `JsonMetaStore` and `preview_cards` tests.
- Seam: `JsonMetaStore` loads before `make_cards` takes `anki.lock`; two concurrent real runs could lose meta writes; runs are owner-only and manual.

## Status
- Proposed 2026-11-16 by Claude in a headless autofire session (step `lib1`); no code, sops, Anki or vault change made.
- Scope fixed by owner decisions in Libra `AGENTS.md` (owner, 2026-11-15 and 2026-11-16); this ADR does not reopen them.
- Each phase L2 to L4 runs in its own new session and ends with a seams-and-gaps audit, docs update, commit.
- Check baseline and trace notes: `~/.cache/spike-20261116/` (agy prompt, baseline output).

## Context
**Owner decisions:**
- Owner (2026-11-15): Libra takes all self-study capacity from SemAI: lesson checker, Anki cards, week-file parser.
- Owner (2026-11-16): lesson generator (`study/lesson.py` generation, `study/figures.py`) stays parked in SemAI; PWA views, page render and nightly scheduler stay parked in SemAI.
- Owner (2026-11-16): after Libra is verified, the SemAI copies of moved modules and tests are deleted.
- Owner (2026-11-16): moved files go in verbatim; the owner runs `dispatch-ledger-hand.sh` on them; only import and glue edits use DeepSeek dispatch.
- Owner (2026-11-16): Claude copies AnkiWeb sops values into Libra sops with `sops set`, never printing them; planned for L3.
- Owner (2026-11-16): checker on Fedora and Mac, its `code_run` kind Fedora only (`bwrap`); cards Fedora only.

**Context facts (verified 2026-11-16):**
- SemAI is on hiatus since 2026-11-15; units stopped; `omll` still runs from the SemAI repo.
- Today the checker runs as `omll study check` (`adapters/cli.py` `cmd_study_check`); cards as `uv run python ~/.cache/spike-20261109/study_steps.py cards` from the SemAI repo.
- `study_steps.py` (28 lines, outside any repo) calls `nightly.make_cards(vault, state_dir, TaskStore, today, claude_runner(vault, [~/Ebooks, ~/Classes]), load_auth())`.
- Baseline `omll study check --all` on the real vault: 29 files, 2 failures, 9 notes, exit 1; saved in `~/.cache/spike-20261116/omll_check_all_baseline.txt`.
- The 2 failures are the two known closed-world gaps the owner left as they are (owner, 2026-11-15).
- SemAI meta table (`.state-semai/semai.sqlite3`) holds 0 `anki_cards:`, 0 `anki_cards_body:`, 0 `anki_gen:` rows and no `anki_unsynced` key; no card was ever made.
- `.state-semai/anki/` holds `collection.anki2` (3.9 MB), `collection.media/`, `collection.media.db2`; 8.2 MB on disk; last written 2026-11-09.
- Card answers for Recall and Reading items are written by `claude -p` through `lesson.claude_runner`; DSA signal cards need no Claude call.
- `anki_sync.load_auth` reads `SEMAI_ANKIWEB_HKEY` and `SEMAI_ANKIWEB_ENDPOINT`; `scripts/anki_login_once.py` reads `SEMAI_ANKIWEB_USER`, `SEMAI_ANKIWEB_PASSWORD` and writes the hkey.
- SemAI `security.secrets.resolve_secret` reads sops at the cwd-relative path `.secret/secrets.json`; that is why `cards` must run from the SemAI repo.
- Libra has no sqlite; state lives in `~/.local/state/libra/`; `config.load_secrets` fills keys listed in `SECRET_KEYS` from Libra sops.
- Libra `Settings` is a plain frozen dataclass; its `gemini_api_key` and `openrouter_api_key` fields show in `repr` (no `repr=False`).
- The Mac has no `bwrap` (checked 2026-11-16); SemAI `check_code` then reports `code_run: sandbox unavailable` as a failure, not a note.
- Libra size guard: 600 lines a file, 100 code lines a function, over `src/libra`; `cli.py` is 401 lines.

## Trace
Import edges under SemAI `src/semai/`:
- `study/checks.py` -> `check_kinds`.
- `study/check_kinds.py` -> `memory.frontmatter`, `check_concepts`, `check_refs`, `check_code`, `check_facts`.
- `study/check_concepts.py` -> `render.scan_blocks`; `check_refs.py` -> `check_concepts`.
- `study/check_code.py` -> `security.sandbox` (`SandboxError`, `run_sandboxed`), `render.scan_blocks`.
- `study/check_facts.py` -> `memory.frontmatter`, `check_concepts.fence_mask`, `render.scan_blocks`; never imports `paths.py`.
- `study/week.py` -> `memory.frontmatter`; `memory/frontmatter.py` and `security/sandbox.py` are stdlib only, except `sandbox` -> `core.errors.SemaiError`.
- `study/render.py` -> `markdown_it`, `mdit_py_plugins.dollarmath`, `memory.frontmatter`; `scan_blocks` parses with the full page parser `_md` (wikilink, callout, fact marker, embed rules).
- `study/paths.py` -> `lesson.LESSON_ROOTS`, `render.IMAGE_SUFFIXES`.
- `study/anki_cards.py` -> `lesson.RECALL_ITEM_RE` (re-export of `check_kinds.RECALL_ITEM_RE`), `render.scan_blocks`.
- `study/anki_sync.py` -> `security.secrets.resolve_secret`, lazy `anki`.
- `study/nightly.py` card path -> `anki_cards`, `anki_sync`, `lesson` (`LESSON_ROOTS`, `LessonError`, `Runner`), `paths` (`make_resolver`, `note_names`), `render.split_frontmatter`, `week` (`Item`, `parse_week`, `week_relpath`).
- Card functions in `nightly.py`: `week_lock`, `_done_lessons`, `_body_key`, `_concept_body_key`, `_lesson_concepts`, `_signal_source`, `_item_notes`, `make_cards`; meta via the `MetaStore` protocol (`meta_get`, `meta_set`).
- Meta keys: `anki_cards:<path>` (done), `anki_cards_body:<sha256>` (concept body), `anki_gen:<date>:<path>` (attempts), `anki_unsynced`.
- Parked SemAI consumers: `lesson.py` -> `check_kinds`, `check_refs.lesson_base`, `checks` (`load_rules`, `check_text`, `RuleSet`), `figures`, `week.Item`.
- Parked SemAI consumers: `views.py` -> `lesson`, `nightly.week_lock`, `paths`, `render`, `week`; `web/study.py` -> `week.StaleItemError`.
- Live SemAI consumers: `adapters/daemon.py` and `web/today.py` -> `nightly` `PLAN_REMINDER_*`; `adapters/cli.py` -> `anki_sync.load_auth`, `checks`, `lesson`, `nightly.run_nightly`.

## Decisions
### D-a, Anki state
- Decision: collection goes to `<Libra state_dir>/anki/collection.anki2` (`anki_sync.collection_path` unchanged); L3 copies `.state-semai/anki/` once with `cp -a`.
- Decision: meta rows go to one JSON file `<state_dir>/anki/meta.json` behind `MetaStore` protocol, atomic replace under existing `anki.lock`.
- Migration: 0 meta rows today; L3 recounts first; nonzero rows get a one-off copy script in `~/.cache/spike-<date>/`.
- Options: JSON meta file; a new sqlite table in Libra; no local meta (GUID dedupe in the collection only).
- Why: JSON reuses `MetaStore` with stdlib only; sqlite adds Libra's first database; GUID-only dedupe re-calls Claude for every ticked lesson.
- Why copy collection: keeps sync state; a fresh empty collection forces a full AnkiWeb download (works, slower); fallback if copy fails.

### D-b, block scanner
- Decision: copy SemAI `study/render.py` verbatim to `src/libra/study/render.py`; one trim dispatch deletes `render_note`, `render_concept` and helpers only they use.
- Decision: `_make_parser` and every rule it registers stay byte-identical, so `scan_blocks` sees what SemAI sees.
- Options: verbatim copy plus trim; dispatch a new extracted `blocks.py`; Libra imports SemAI.
- Why: verbatim plus deletions is auditable by diff; extraction risks parser drift; cross-repo import couples Libra to a parked repo.
- Seam recorded: two copies of the page parser; SemAI's stays frozen while parked.

### D-c, what SemAI keeps
- Fact: parked generator, views and web routes import `checks`, `check_*`, `week`, `paths`, `render`, `frontmatter`, `sandbox`; deleting breaks SemAI `web/app.py`, `adapters/cli.py`, daemon.
- Decision: SemAI keeps those modules and their tests as parked dependencies; they freeze; Libra's copies are the maintained ones.
- Decision: L4 deletes only what no parked code needs: `study/anki_cards.py`, `study/anki_sync.py`, `scripts/anki_login_once.py`, `tests/test_anki_cards.py`, `tests/test_anki_sync.py`.
- Decision: L4 dispatches remove card path from SemAI `study/nightly.py` and `run_nightly`, `cmd_study_check`, `study check` parser, `load_auth` from `adapters/cli.py`, and their tests.
- Options: keep parked dependencies; point SemAI imports at Libra; delete the generator too.
- Why: owner parked generator and views; pointing at Libra edits 5 SemAI files and makes Libra internals a SemAI API.

### D-d, CLI
- Decision: `libra study check [paths] [--all] [--profile P]`, output and exit codes identical to `omll study check` (0 clean, 1 failures, 2 usage).
- Decision: `libra study cards [--date YYYY-MM-DD] [--dry-run]`; handlers live in new `src/libra/study/commands.py` to keep `cli.py` under the size cap.
- Decision: `study cards` without `--dry-run` is owner-only in `cli._agent_refusal` (writes AnkiWeb, spawns `claude -p`); agents pass by the existing owner-ok rule in Libra `AGENTS.md`.
- Decision: `study check` and `study cards --dry-run` are not owner-only; the lesson done rule needs agents to run the checker.
- Decision: `--dry-run` uses an in-memory meta copy, opens no collection, syncs nothing, never calls Claude; prints card GUID, front, and lessons needing Claude.
- Options: owner-only for all of `study`; only `cards`; none.
- Why: only `cards` has outside effects; the guard already special-cases one flag (`read --fetch`).

### D-e, settings and secrets
- Decision: vault is existing `LIBRA_VAULT_DIR` (`Settings.obsidian_academic_vault_dir`), state is `state_dir`, today uses `Settings.tz`; no new path setting.
- Decision: sops keys renamed in Libra: `LIBRA_ANKIWEB_HKEY`, `LIBRA_ANKIWEB_ENDPOINT`, `LIBRA_ANKIWEB_USER`, `LIBRA_ANKIWEB_PASSWORD`; copied from the four `SEMAI_ANKIWEB_*` keys.
- Decision: `SECRET_KEYS` gains hkey and endpoint; `Settings` gains `anki_hkey`, `anki_endpoint` (`repr=False`); `load_secrets` fills them; `anki_sync.load_auth(settings)` builds `AnkiAuth`.
- Decision: the same dispatch sets `repr=False` on existing `gemini_api_key` and `openrouter_api_key` fields.
- Decision: `claude_runner` read dirs `~/Ebooks`, `~/Classes` become a constant in `study/commands.py`, as in `study_steps.py`.
- Options: `Settings` fields via `load_secrets`; port `resolve_secret`; keep `SEMAI_` names.
- Why: reuses Libra's one sops path (absolute, no cwd trap); `SEMAI_` names would leave another repo's prefix in Libra.

### D-f, dependencies
- Decision: new extra `study` = `markdown-it-py>=4.0`, `mdit-py-plugins>=0.6` (every machine); new extra `anki` = `anki>=26.9.4` (Fedora only).
- Decision: install Fedora `uv tool install --editable --force '.[fedora,plot,study,anki]'`, Mac `uv tool install --editable --force '.[plot,study]'`.
- Decision: `libra study cards` without `anki` extra exits 2 with an install hint; `study check` without `study` exits 2 likewise.
- Options: extras per capability; add to core dependencies.
- Why: Libra core stays stdlib only; `anki` is large and Fedora-only by owner decision.

### D-g, tests and fixtures
- Decision: verbatim test copies: `tests/test_study_checks.py`, `test_study_check_code.py`, `test_study_check_concepts.py`, `test_study_check_facts.py`, `test_study_check_refs.py`, `test_study_week.py`, `test_study_render.py`, `test_anki_cards.py`, `test_anki_sync.py`, `test_frontmatter.py`, `test_security_sandbox.py`, `test_study_nightly.py` (as `test_study_cards.py`), `tests/fixtures/lesson_rules.toml`.
- Decision: `test_study_nightly.py` has 39 tests, 21 about cards; Libra copy keeps the 21 and drops the rest by trim dispatch.
- Decision: drop from Libra copies: `lint_lesson` tests (generator), `render_note` tests; `test_anki_cards` `CAT_KIND` test becomes a literal deck-key set.
- Decision: Libra gets `tests/conftest.py` with autouse guard stubbing `config._read_sops_secrets` and `config._read_config_env`, mirroring SemAI `no_real_secrets`.
- Options: `conftest` guard; per-test env only.
- Why: `load_secrets` now runs on the cards path; a test must never decrypt real sops or read `.config/libra.env`.

### D-h, references to repoint at L4 (grep 2026-11-16; change nothing before L4)
- Vault `~/Classes/Current/AGENTS.md:185` (`omll study check`, Mac `ssh` form).
- Vault `~/Classes/Current/Tools/lesson_rules.toml:2` (run comment).
- Vault `~/Classes/Current/Coding Practice/DSA_Notebook_Plan.md:46` (`cards` step).
- Memory `~/.claude/projects/-home-dyne-Documents-Coding-SemAI/memory/feedback_manual_lessons.md:23`, `feedback_lessons_closed_world.md:15`.
- Memory `feedback_pwa_first_telegram_frozen.md:3,13` names `omll-study` as a core example; reword to a neutral example.
- SemAI `AGENTS.md` lines naming `omll study check`, `study_steps.py`, `cards`: START HERE, Lesson checker, Lesson workflow checklist, Carryover, file index.
- Hivemind `~/Developer/Hivemind`: no hit outside agy history transcripts (left as is).
- Mac checker: `libra study check` runs locally on the Drive vault; the `ssh dyne@fedora 'omll study check'` form is retired.

## Phases
### L1 design (this ADR)
- Done when this ADR and Libra `AGENTS.md` START HERE are committed and pushed.

### L2 checker port (Fedora, new session)
**Verbatim (owner runs dispatch-ledger-hand.sh):**
- `src/semai/study/__init__.py` -> `src/libra/study/__init__.py`
- `src/semai/study/checks.py` -> `src/libra/study/checks.py`
- `src/semai/study/check_kinds.py`, `check_concepts.py`, `check_refs.py`, `check_code.py`, `check_facts.py` -> same names in `src/libra/study/`
- `src/semai/study/week.py` -> `src/libra/study/week.py`
- `src/semai/study/paths.py` -> `src/libra/study/paths.py`
- `src/semai/study/render.py` -> `src/libra/study/render.py`
- `src/semai/memory/frontmatter.py` -> `src/libra/study/frontmatter.py`
- `src/semai/security/sandbox.py` -> `src/libra/sandbox.py`
- Tests: `test_study_checks.py`, `test_study_check_code.py`, `test_study_check_concepts.py`, `test_study_check_facts.py`, `test_study_check_refs.py`, `test_study_week.py`, `test_study_render.py`, `test_frontmatter.py`, `test_security_sandbox.py`, `fixtures/lesson_rules.toml`.

**Dispatch (one file per response):**
- SEARCH block counts: `study/checks.py` 1 (import); `check_kinds.py` 5; `check_concepts.py` 2; `check_refs.py` 2; `check_facts.py` 4; `week.py` 1 (imports `semai.` to `libra.study.`).
- `sandbox.py` raises `SandboxUnavailable` (`SandboxError` subclass) when `bwrap` is missing; `check_code.code_run` emits `Note` (`code_run: skipped, bwrap not found (Fedora only)`) and stops; other sandbox errors fail.
- `paths.py` 2 SEARCH blocks: define `LESSON_ROOTS = ("Self study/", "Coding Practice/")` instead of importing `lesson`; import `IMAGE_SUFFIXES` from `libra.study.render`.
- `render.py`: 1 import block plus one deletion block per removed function (`render_note`, `render_concept`, and helpers only they call).
- `frontmatter.py` 2 SEARCH blocks (module docstring, `NoFrontmatterHeader` docstring naming `semai.memory.fact_note`); `sandbox.py` 1 (`SandboxError` subclasses `RuntimeError`, no `SemaiError`).
- `src/libra/study/commands.py`: `cmd_study_check(vault, ...)` and `_vault_rel` ported from SemAI `adapters/cli.py`; takes `libra.cli` vault root (`--root` or `LIBRA_VAULT_DIR`), `LESSON_ROOTS` from `paths`.
- `src/libra/cli.py`: `study` parser with `check` (paths, `--all`, `--profile`); route to `study.commands`; missing `study` extra exits 2 with hint.
- `pyproject.toml`: `study` extra (hand config edit with owner sign-off, or dispatch).
- Tests: import edits per copied test (block counts 9, 5, 2, 3, 3, 1, 5, 1, 2 in verbatim order).
- Tests: `lint_lesson` and `render_note` tests deleted; `cmd_study_check` tests pass vault path; `cli.main` routing test; `SandboxUnavailable` yields skipped note.

**Verify:**
- `uv run pytest -q tests/` all pass; size guard passes.
- `diff <(omll study check --all) <(libra study check --all)` empty on the real Fedora vault; summary `29 files, 2 failures, 9 notes`, exit 1 matches baseline.
- Mac: `libra study check --all` on the Drive vault; same failures; `code_run` lines become skipped notes.

**Owner does:**
- Run `dispatch-ledger-hand.sh` on every verbatim file before the import dispatches land.
- Reinstall Libra with `.[fedora,plot,study]` on Fedora, `.[plot,study]` on the Mac.

### L3 cards, state, sops (Fedora, new session)
**Verbatim (owner runs dispatch-ledger-hand.sh):**
- `src/semai/study/anki_cards.py` -> `src/libra/study/anki_cards.py`
- `src/semai/study/anki_sync.py` -> `src/libra/study/anki_sync.py`
- `src/semai/study/nightly.py` -> `src/libra/study/cards.py`
- `src/semai/study/lesson.py` -> `src/libra/study/runner.py`
- `scripts/anki_login_once.py` -> `scripts/anki_login_once.py`
- Tests: `test_anki_cards.py`, `test_anki_sync.py`, `test_study_nightly.py` -> `tests/test_study_cards.py`

**Dispatch (one file per response):**
- `anki_cards.py` 2: import `RECALL_ITEM_RE` from `check_kinds`, `scan_blocks` from `libra.study.render`.
- `anki_sync.py`: secret constants to `LIBRA_ANKIWEB_*`; `load_auth(settings)` reads `Settings.anki_hkey`, `anki_endpoint`; no `resolve_secret`.
- `cards.py`: delete carry, rollover, generation, `run_nightly`, plan-reminder code; keep card functions listed in Trace; add JSON `MetaStore` (`meta.json`, atomic replace).
- `runner.py`: keep only `LessonError`, `Runner`, `claude_runner`; delete generation, figures, outline and lint code.
- `config.py`: `SECRET_KEYS`, `Settings.anki_hkey`, `anki_endpoint` (`repr=False`), `repr=False` on the two API keys, `load_secrets` fills them.
- `study/commands.py`: `cmd_study_cards` (lock, today from `Settings.tz`, `--dry-run` per D-d); `cli.py`: `cards` parser and `_agent_refusal` case.
- `scripts/anki_login_once.py`: Libra sops path and `LIBRA_ANKIWEB_*` names.
- `pyproject.toml`: `anki` extra; tests: import edits, trim `test_study_cards.py` to the 21 card tests, `tests/conftest.py` guard.

**State and sops (Claude, Fedora):**
- Re-count SemAI `anki_*` meta rows; expect 0.
- `cp -a ~/Documents/Coding/SemAI/.state-semai/anki ~/.local/state/libra/anki`; SemAI copy stays until L4.
- `sops set` the four values into Libra `.secret/secrets.json` under the `LIBRA_ANKIWEB_*` names, piping values, never printing them.

**Verify:**
- `uv run pytest -q tests/` all pass.
- `libra study cards --dry-run` lists expected cards for ticked lessons in yesterday's and today's week files; no file under `~/.local/state/libra/anki/` changes.
- First real run (`libra study cards`) only with the owner, at the next tick (SemAI A3 item).

**Owner does:**
- `dispatch-ledger-hand.sh` on the verbatim files; reinstall Fedora with `.[fedora,plot,study,anki]`.
- Approve the first real AnkiWeb run.

### L4 repoint and delete (new session)
**Docs (Edit or Write only):**
- Repoint every D-h reference to `libra study check` and `libra study cards`.
- SemAI `AGENTS.md`: drop moved-code seams, Anki and `cards` lines, file index rows; keep a pointer to this ADR.
- Libra `AGENTS.md`: study section, index rows, traps.

**Delete in SemAI (dispatch for code edits, `git rm` for whole files):**
- `src/semai/study/anki_cards.py`, `src/semai/study/anki_sync.py`, `scripts/anki_login_once.py`, `tests/test_anki_cards.py`, `tests/test_anki_sync.py`.
- Dispatch `study/nightly.py`: remove card constants and functions, `anki_auth` and the card step from `run_nightly`, `NightlyReport` card fields.
- Dispatch `adapters/cli.py`: remove `cmd_study_check`, `_vault_rel` (its only caller is `cmd_study_check`), the `study check` parser, `load_auth` import and argument.
- Dispatch tests: card tests in `test_study_nightly.py`, `cmd_study_check` tests in `test_study_checks.py`.
- `pyproject.toml` `anki` line and `uv.lock` (owner sign-off).
- `~/.cache/spike-20261109/study_steps.py` retired.

**Verify:**
- SemAI `uv run pytest -q tests/` passes; `uv run python -c "import semai.web.app, semai.adapters.daemon, semai.adapters.cli"` imports clean.
- Grep of D-h paths finds no `omll study` or `study_steps` outside history.

**Owner does:**
- Approve deleting `.state-semai/anki/` after Libra's first real sync.
- Answer the Asks owner items.

## Seams
- Two checker copies: SemAI's frozen with the parked generator; a SemAI generator revival must re-sync or import Libra's.
- Two page-parser copies (`render.py`); Libra trims render functions, keeps the parser identical.
- `DECKS` in Libra no longer checked against SemAI `CAT_KIND`; a new category needs both edited.
- Card GUID prefix stays `semai-` (the GUID is the dedupe key, so SemAI-era notes still match); the card tag `semai` stays verbatim.
- `claude_runner` spawns `claude -p`; under Claude Code it runs nested, as it did from SemAI.
- Libra `cards` keeps SemAI seams F210, F211, F193; it reads Self study `Current.md` and `Master index.md` (owner, 2026-11-16).
- Mac/Fedora `study check` outputs differ by `code_run` notes only; Mac lessons with runnable code get one skipped note, no notes after first runnable block (verified 2026-11-16).

## Owner decisions
- Allow one mechanical `sed` import rewrite (`semai.` to `libra.`), then the owner runs `dispatch-ledger-hand.sh` (owner, 2026-11-16)
- Delete SemAI sops `SEMAI_ANKIWEB_*` keys (HKEY, ENDPOINT, USER, PASSWORD) after L3 verification (owner, 2026-11-16)
- Accept D-c (SemAI keeps checker, week, paths, render as parked dependencies) as the scope for deleting SemAI copies (owner, 2026-11-16)

## Consequences
- Libra gains `src/libra/study/` (checker, week parser, cards) and `src/libra/sandbox.py`; core stays stdlib only.
- SemAI loses Anki code and `omll study check`; its parked generator and views still import.
- Agents on the Mac run the checker locally; cards stay a Fedora owner-approved step.
