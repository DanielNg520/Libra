# 0002 – Self study in Libra

## Status
Accepted, in code, 2026-11-16

## Context
- Libra provides self-study tools: lesson checker, Anki cards, and study-plan parser (owner, 2026-11-15).
- Checker runs on Fedora and Mac; `code_run` requires Fedora (`bwrap`); cards run on Fedora only (owner, 2026-11-16).
- Anki cards use the `libra-` GUID prefix and a per-lesson tag via `anki_cards.lesson_tag` (owner, 2026-11-16).

## Decisions
### D-a, Anki state
- Libra has no sqlite; state lives under `~/.local/state/libra/` (`state_dir`).
- Collection lives at `<state_dir>/anki/collection.anki2` (`anki_sync.collection_path`), with `collection.media/` and `collection.media.db2`.
- Meta rows live in `<state_dir>/anki/meta.json` behind `MetaStore` (`meta_get`, `meta_set`), implemented by `JsonMetaStore` with atomic replace under `anki.lock`.
- Meta keys: `anki_cards:<path>`, `anki_cards_body:<sha256>`, `anki_gen:<date>:<path>`, `anki_unsynced`.
- `src/libra/study/cards.py` defines `make_cards`, `preview_cards`, `JsonMetaStore`, `week_lock`, `_done_lessons`, `_item_sources`, and `_item_notes`.
- `src/libra/study/anki_cards.py` imports `RECALL_ITEM_RE` from `check_kinds` and `scan_blocks` from `libra.study.render`.
- `src/libra/study/anki_sync.py` wraps lazy `anki` imports and `load_auth(settings)`.
- `src/libra/study/runner.py` defines `LessonError`, `Runner`, and `claude_runner`; Recall and Reading answers call `claude -p`, while DSA signal cards do not.
- JSON meta stays stdlib only and avoids re-calling Claude for completed lessons.

### D-b, block scanner
- `src/libra/study/render.py` runs `_make_parser` (`markdown-it-py`, `mdit_py_plugins.dollarmath`) so `scan_blocks` handles wikilink, callout, fact marker, and embed rules.
- Checker and parser modules in `src/libra/study/`: `__init__.py`, `checks.py`, `check_kinds.py`, `check_concepts.py`, `check_refs.py`, `check_code.py`, `check_facts.py`, `plan.py`, `paths.py`, `frontmatter.py`.
- `paths.py` defines `LESSON_ROOTS = ("Self study/",)` and imports `IMAGE_SUFFIXES` from `libra.study.render`.
- `src/libra/sandbox.py` runs `code_run` via `bwrap`; `SandboxError` subclasses `RuntimeError`, and `SandboxUnavailable` is raised when `bwrap` is missing.
- On `SandboxUnavailable`, `check_code.code_run` emits `Note` (`code_run: skipped, bwrap not found (Fedora only)`) and stops; other sandbox errors fail.

### D-d, CLI
- `libra study check [paths] [--all] [--profile P]` exits `0` when clean, `1` on failures, and `2` on usage or missing `study` extra.
- `libra study cards [--date YYYY-MM-DD] [--dry-run]` exits `2` when the `anki` extra is missing.
- Handlers live in `src/libra/study/commands.py` (`cmd_study_check`, `_vault_rel`, `cmd_study_cards`), keeping `src/libra/cli.py` under the 600-line size guard.
- `study cards` without `--dry-run` is owner-only in `cli._agent_refusal` (writes AnkiWeb, spawns `claude -p`); agents pass under the `AGENTS.md` owner-ok rule.
- `study check` and `study cards --dry-run` are not owner-only.
- `--dry-run` calls `cards.preview_cards` (reusing `_done_lessons` and `_item_sources`), uses an in-memory meta copy, opens no collection, syncs nothing, and skips Claude.
- `--dry-run` prints card GUID, front, and lessons needing Claude.

### D-e, settings and secrets
- Vault uses `LIBRA_VAULT_DIR` (`Settings.obsidian_academic_vault_dir`) or `--root`, state uses `state_dir`, and today uses `Settings.tz`; no extra path setting exists.
- `claude_runner` read dirs `~/Ebooks` and `~/Classes` are a constant in `src/libra/study/commands.py`.
- Sops keys: `LIBRA_ANKIWEB_HKEY`, `LIBRA_ANKIWEB_ENDPOINT`, `LIBRA_ANKIWEB_USER`, `LIBRA_ANKIWEB_PASSWORD`.
- `src/libra/config.py`: `SECRET_KEYS` includes hkey and endpoint; `Settings` (frozen dataclass) defines `anki_hkey`, `anki_endpoint`, `gemini_api_key`, `openrouter_api_key` with `repr=False`.
- `config._read_sops_secrets(path, keys)` takes a key list; `load_secrets` fills four secrets and skips sops only when all four are set.
- `anki_sync.load_auth(settings)` reads `Settings.anki_hkey` and `Settings.anki_endpoint` to build `AnkiAuth`.
- `scripts/anki_login_once.py` reads `LIBRA_ANKIWEB_USER` and `LIBRA_ANKIWEB_PASSWORD` and writes `LIBRA_ANKIWEB_HKEY` to Libra sops.

### D-f, dependencies
- Extra `study` requires `markdown-it-py>=4.0` and `mdit-py-plugins>=0.6` (Fedora and Mac); extra `anki` requires `anki>=26.9.4` (Fedora only).
- Install Fedora: `uv tool install --editable --force '.[fedora,plot,study,anki]'`.
- Install Mac: `uv tool install --editable --force '.[plot,study]'`.
- Missing extras exit `2` with an install hint on `libra study check` and `libra study cards`; Libra core stays stdlib only.

### D-g, tests and fixtures
- Checker and parser tests: `tests/test_study_checks.py`, `test_study_check_code.py`, `test_study_check_concepts.py`, `test_study_check_facts.py`, `test_study_check_refs.py`, `test_study_plan.py`, `test_study_render.py`.
- Supporting and card tests: `test_anki_cards.py`, `test_anki_sync.py`, `test_frontmatter.py`, `test_security_sandbox.py`, `test_study_cards.py`, `test_study_cards_cmd.py`, `tests/fixtures/lesson_rules.toml`.
- `tests/test_study_cards.py` contains 21 card tests, `test_week_lock_excludes_others`, `JsonMetaStore` tests, and `preview_cards` tests.
- `test_anki_cards.py` tests `DECKS` against a literal deck-key set.
- `tests/conftest.py` provides an autouse guard stubbing `config._read_sops_secrets` and `config._read_config_env`, leaving `_read_config_env` real in `test_config.py`.

## Seams
- `JsonMetaStore` loads before `make_cards` takes `anki.lock`; concurrent real runs could lose meta writes, though runs are owner-only and manual.
- `claude_runner` spawns `claude -p`; under Claude Code it runs nested.
- `cards` reads Self study `Current.md` and `Master index.md` (owner, 2026-11-16).
- Mac/Fedora `study check` differs by `code_run` notes only; Mac lessons get one skipped note, none after first runnable block (verified 2026-11-16).

## Consequences
- Libra provides `src/libra/study/` (checker, plan parser, cards) and `src/libra/sandbox.py`, with core remaining stdlib only.
- Agents on Fedora and Mac run `libra study check` and `libra study cards --dry-run` locally.
- Real `libra study cards` runs remain Fedora-only and owner-approved.
