"""The `libra` command: search transcripts and readings, catalog course material, view lecture maps.

Usage: libra search [--in transcripts|readings|textbooks|all] [options] <terms...>
       libra catalog [--course X] [--json]
       libra map [--course X] [--date D] [--json]
       libra map --confirm --course X --transcript ID --deck DECK [--from T] [--to T]
       libra login [--timeout S]   (sign in to podcast.ucsd.edu, then fetch)
       libra fetch | libra whisper [--until H] | libra export | libra status
       libra read --course X PATH [--pages A-B] [--fetch]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from libra import commands
from libra.catalog import cmd_catalog
from libra.config import Settings, SettingsError
from libra.mapview import cmd_map
from libra.search import _validate_date, cmd_search

VAULT_COMMANDS = frozenset({"search", "catalog", "map"})


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="libra")
    parser.add_argument("--root", type=Path, default=None, help="vault root (default: LIBRA_VAULT_DIR)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("terms", nargs="+")
    search_parser.add_argument("--course", default=None)
    search_parser.add_argument("--since", type=_validate_date, default=None)
    search_parser.add_argument("--until", type=_validate_date, default=None)
    search_parser.add_argument(
        "--kind", choices=["lecture", "discussion", "all"], default="all"
    )
    search_parser.add_argument(
        "--any", dest="any_mode", action="store_true", default=False
    )
    search_parser.add_argument("--window", type=int, default=4)
    search_parser.add_argument("-C", "--context", type=int, default=1)
    search_parser.add_argument("--limit", type=int, default=20)
    search_parser.add_argument(
        "--in",
        dest="scope",
        action="append",
        choices=["transcripts", "readings", "textbooks", "all"],
        default=None,
    )
    search_parser.add_argument("--json", action="store_true", default=False)

    catalog_parser = subparsers.add_parser("catalog")
    catalog_parser.add_argument("--course", default=None)
    catalog_parser.add_argument("--json", action="store_true", default=False)
    map_parser = subparsers.add_parser("map")
    map_parser.add_argument("--course", default=None)
    map_parser.add_argument("--date", type=_validate_date)
    map_parser.add_argument("--json", action="store_true", default=False)
    map_parser.add_argument("--confirm", action="store_true", default=False)
    map_parser.add_argument("--transcript", default=None)
    map_parser.add_argument("--deck", default=None)
    map_parser.add_argument("--from", dest="from_t", default=None)
    map_parser.add_argument("--to", dest="to_t", default=None)

    login_parser = subparsers.add_parser("login")
    login_parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="seconds to wait for sign-in",
    )
    subparsers.add_parser("fetch")
    subparsers.add_parser("export")
    subparsers.add_parser("status")

    whisper_parser = subparsers.add_parser("whisper")
    whisper_parser.add_argument(
        "--until",
        dest="until_hour",
        type=int,
        default=6,
        help="stop starting new jobs at this local hour",
    )

    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("path")
    read_parser.add_argument("--course", required=True)
    read_parser.add_argument("--pages", default=None, help="N or A-B")
    read_parser.add_argument("--fetch", action="store_true", default=False)
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
        settings = _settings()
        if settings is None:
            return commands.EXIT_USAGE
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
