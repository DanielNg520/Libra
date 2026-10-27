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
Owner (2026-10-27): Libra is modular; her memory lives in Hivemind, shared by every instance (Hivemind `docs/libra.md`).
Owner (2026-10-27): an instance may hold a feature others lack; sharing every feature across instances is the long-run goal.
Owner (2026-10-27): Whisper runs on Fedora only; Fedora makes every Whisper output available to Libra instances on other machines.
Clones: Fedora `~/Documents/Coding/Libra`, Mac `~/Developer/Libra`.

## Carryover
State 2026-10-27: no code ported yet; remote set, Fedora and Mac clones exist.
Next: migration plan (which SemAI modules port, cutover order); SemAI keeps fetching transcripts until Libra is live.
Open: how Whisper output reaches other instances; today transcripts land in vault `<course>/Transcripts/`, which Drive syncs to the Mac.
Open: where in Hivemind her memory lives and its format; decide in the migration plan.

## File and directory index
`AGENTS.md` this file.
