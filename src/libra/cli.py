"""The `libra` command: search transcripts and readings, catalog course material, view lecture maps.

Usage: libra search [--in transcripts|readings|textbooks|all] [options] <terms...>
       libra catalog [--course X] [--json]
       libra map [--course X] [--date D] [--json]
       libra map --confirm --course X --transcript ID --deck DECK [--from T] [--to T]
       libra login [--timeout S]   (sign in to podcast.ucsd.edu, then fetch)
       libra fetch | libra whisper [--until H] | libra export | libra status
       libra read --course X PATH [--pages A-B] [--fetch]
       libra ocr IMAGE|- [--notes] [--mime TYPE]   (Gemini transcription; - reads stdin)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, List, Optional

from libra.catalog import cmd_catalog
from libra.config import Settings, SettingsError
from libra.mapview import cmd_map
from libra.search import _validate_date, cmd_search

VAULT_COMMANDS = frozenset({"search", "catalog", "map"})

AGENT_VARS = ("CLAUDECODE", "ANTIGRAVITY_AGENT", "AI_AGENT")
OWNER_ONLY_COMMANDS = frozenset({"login", "fetch", "export", "whisper"})
OWNER_OK_VAR = "LIBRA_OWNER_OK"


def _add_search_parser(subparsers: Any) -> None:
    """Register the search subcommand."""
    search_parser = subparsers.add_parser(
        "search",
        help="find terms in lecture transcripts and readings; exit 1 means no match, 2 a usage or path error",
    )
    search_parser.add_argument(
        "terms",
        nargs="+",
        help="all must match unless --any; quote a phrase; a trailing * is a prefix match and must be quoted",
    )
    search_parser.add_argument(
        "--course",
        default=None,
        help="course folder name such as 'ECE 108'; default every course",
    )
    search_parser.add_argument(
        "--since", type=_validate_date, default=None,
        help="YYYY-MM-DD start bound; filters transcripts only, never readings",
    )
    search_parser.add_argument(
        "--until", type=_validate_date, default=None,
        help="YYYY-MM-DD end bound; filters transcripts only, never readings",
    )
    search_parser.add_argument(
        "--kind", choices=["lecture", "discussion", "all"], default="all",
        help="lecture or discussion transcripts; filters transcripts only",
    )
    search_parser.add_argument(
        "--any", dest="any_mode", action="store_true", default=False,
        help="match any term instead of all",
    )
    search_parser.add_argument(
        "--window", type=int, default=4,
        help="consecutive transcript lines searched together, so terms can match across lines",
    )
    search_parser.add_argument(
        "-C", "--context", type=int, default=1,
        help="context lines printed around each hit",
    )
    search_parser.add_argument("--limit", type=int, default=20, help="maximum hits printed")
    search_parser.add_argument(
        "--in",
        dest="scope",
        action="append",
        choices=["transcripts", "readings", "textbooks", "all"],
        default=None,
        help="where to search, repeatable; default transcripts plus readings; textbooks only when asked",
    )
    search_parser.add_argument(
        "--json", action="store_true", default=False, help="structured hits instead of text"
    )


def _add_vault_parsers(subparsers: Any) -> None:
    """Register the catalog and map subcommands."""
    catalog_parser = subparsers.add_parser(
        "catalog",
        help="list transcripts by date (duration, opening line) and every course file",
    )
    catalog_parser.add_argument("--course", default=None, help="one course, default all")
    catalog_parser.add_argument(
        "--json", action="store_true", default=False, help="structured output"
    )
    map_parser = subparsers.add_parser(
        "map",
        help="lecture-to-slide map per transcript (spans, deck, pages, score)",
    )
    map_parser.add_argument("--course", default=None, help="course folder name")
    map_parser.add_argument(
        "--date", type=_validate_date, help="YYYY-MM-DD, one lecture"
    )
    map_parser.add_argument(
        "--json", action="store_true", default=False, help="structured output"
    )
    map_parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help=(
            "record a verified transcript-to-deck pairing (needs --course, "
            "--transcript, --deck); confirmations override the automatic match"
        ),
    )
    map_parser.add_argument("--transcript", default=None, help="transcript id as shown by map")
    map_parser.add_argument("--deck", default=None, help="deck name")
    map_parser.add_argument(
        "--from", dest="from_t", default=None, help="MM:SS start of the pairing"
    )
    map_parser.add_argument(
        "--to", dest="to_t", default=None, help="MM:SS end of the pairing"
    )


def _add_fedora_parsers(subparsers: Any) -> None:
    """Register the Fedora-only subcommands."""
    login_parser = subparsers.add_parser(
        "login",
        help="owner only; interactive UCSD podcast sign-in, then a fetch",
    )
    login_parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="seconds to wait for sign-in",
    )
    subparsers.add_parser(
        "fetch",
        help="owner or nightly timer only; download new lecture transcripts, rebuild maps and readings",
    )
    subparsers.add_parser("export", help="owner or timer only; rebuild vault readings and maps")
    subparsers.add_parser("status", help="login age and Whisper queue size")

    whisper_parser = subparsers.add_parser(
        "whisper",
        help="owner or nightly timer only; transcribe queued lecture audio",
    )
    whisper_parser.add_argument(
        "--until",
        dest="until_hour",
        type=int,
        default=6,
        help="stop starting new jobs at this local hour",
    )

    read_parser = subparsers.add_parser(
        "read", help="print the cached page text of a deck, reading or textbook"
    )
    read_parser.add_argument(
        "path",
        help="vault-relative path such as 'ECE 108/Slides/x.pdf', not course-relative",
    )
    read_parser.add_argument("--course", required=True, help="course folder name")
    read_parser.add_argument("--pages", default=None, help="N or A-B")
    read_parser.add_argument(
        "--fetch",
        action="store_true",
        default=False,
        help="read uncached pages with Gemini (costs money; owner only)",
    )
    ocr_parser = subparsers.add_parser(
        "ocr", help="transcribe an image with Gemini"
    )
    ocr_parser.add_argument("image", help="image path, or - for stdin")
    ocr_parser.add_argument(
        "--notes",
        action="store_true",
        default=False,
        help="notes prompt: printed text too, math as LaTeX",
    )
    ocr_parser.add_argument("--mime", default=None, help="MIME type (default: guessed from the name, else image/jpeg)")


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="libra",
        description=(
            "course librarian over the vault; search/catalog/map run on any "
            "machine, the other commands are Fedora-only; owner-only commands "
            "over ssh need ssh -t or LIBRA_OWNER_OK=1"
        ),
    )
    parser.add_argument("--root", type=Path, default=None, help="vault root (default: LIBRA_VAULT_DIR)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_search_parser(subparsers)
    _add_vault_parsers(subparsers)
    _add_fedora_parsers(subparsers)
    return parser


def _settings() -> Optional[Settings]:
    """Load settings for the vault-side commands; print why and return None on bad config."""
    try:
        return Settings.load()
    except SettingsError as exc:
        print(f"libra: {exc}", file=sys.stderr)
        return None


def _run_command(args: argparse.Namespace, settings: Settings) -> int:
    """Dispatch the fetch-side subcommands."""
    try:
        from libra import commands
    except ImportError as exc:
        if exc.name == "libra" or (exc.name or "").startswith("libra."):
            raise
        print(
            f"libra: {args.command} needs the fedora extra ({exc.name}); "
            f"run it on Fedora: ssh dyne@fedora libra {args.command}",
            file=sys.stderr,
        )
        return 2
    if args.command == "login":
        return commands.cmd_login(settings, args.timeout)
    if args.command == "fetch":
        return commands.cmd_fetch(settings)
    if args.command == "whisper":
        return commands.cmd_whisper(settings, args.until_hour)
    if args.command == "read":
        return commands.cmd_read(settings, args.course, args.path, args.pages, args.fetch)
    if args.command == "export":
        return commands.cmd_export(settings)
    if args.command == "status":
        return commands.cmd_status(settings)
    if args.command == "ocr":
        return commands.cmd_ocr(settings, args.image, args.notes, args.mime)
    return 2


def _vault_root(arg: Optional[Path]) -> Optional[Path]:
    """Return --root, else the configured vault; print why and return None when neither exists."""
    if arg is not None:
        return arg
    try:
        vault = Settings.load().obsidian_academic_vault_dir
    except SettingsError as exc:
        print(f"libra: {exc}", file=sys.stderr)
        return None
    if vault is None:
        print("libra: LIBRA_VAULT_DIR is not set; pass --root", file=sys.stderr)
        return None
    return vault


def _agent_refusal(
    args: argparse.Namespace, env: Mapping[str, str], stdin_tty: bool
) -> Optional[str]:
    """Return the refusal message for an owner-only command run by an agent, else None."""
    if env.get(OWNER_OK_VAR) == "1":
        return None

    agent_vars_set = any(env.get(var) for var in AGENT_VARS)
    if agent_vars_set:
        is_agent = True
    else:
        is_agent = bool(env.get("SSH_CONNECTION")) and not stdin_tty

    if not is_agent:
        return None

    if args.command == "read" and args.fetch:
        name = "read --fetch"
    elif args.command in OWNER_ONLY_COMMANDS:
        name = args.command
    else:
        return None

    message = (
        f"libra: {name} is owner-only; rerun with {OWNER_OK_VAR}=1 "
        "only if the owner asked"
    )
    if not agent_vars_set:
        message += "; if you are the owner on ssh, rerun with ssh -t"
    return message


def main(argv: Optional[List[str]] = None) -> int:
    """Run the CLI and return the exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )

    if args.command not in VAULT_COMMANDS:
        stdin_tty = sys.stdin.isatty() if sys.stdin is not None else False
        refusal = _agent_refusal(args, os.environ, stdin_tty)
        if refusal is not None:
            print(refusal, file=sys.stderr)
            return 2

        settings = _settings()
        if settings is None:
            return 2
        return _run_command(args, settings)

    root = _vault_root(args.root)
    if root is None:
        return 2

    if args.command == "search":
        return cmd_search(args, root)
    if args.command == "catalog":
        return cmd_catalog(args, root)
    if args.command == "map":
        return cmd_map(args, root)
    return 2
