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

## Carryover
State 2026-10-27: empty repo; `git init` and `codegraph init` only; no code ported yet.
Next: migration plan (which SemAI modules port, cutover order); SemAI keeps fetching transcripts until Libra is live.
Ask owner: GitHub remote, and is Libra Fedora-only like SemAI (Whisper, Playwright login state live there)?

## File and directory index
`AGENTS.md` this file.
