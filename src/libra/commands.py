"""Handlers for the `libra` fetch, Whisper, read, export, login and status commands."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable
from zoneinfo import ZoneInfo

from libra import lecture_poll
from libra.config import Settings, load_secrets
from libra.gemini import GeminiError
from libra.lecture_docs import READS_DIR
from libra.lecture_fetch import AUDIO_DIR, state_path
from libra.login import cmd_podcast_login
from libra.ocr import DEFAULT_OCR_PROMPT, NOTES_OCR_PROMPT, transcribe_image
from libra.read import ReadError, read_pages
from libra.sources import INDEX_NAME

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_LOGIN_EXPIRED = 3


def _queued(settings: Settings) -> int:
    audio_dir = settings.state_dir / AUDIO_DIR
    if not audio_dir.is_dir():
        return 0
    return sum(
        1
        for p in audio_dir.glob("*.json")
        if p.with_suffix(".m4a").exists()
    )


def _cache_ready(settings: Settings) -> bool:
    """True when the reading cache index exists; exports from an empty cache would downgrade the shared vault."""
    if not (settings.state_dir / READS_DIR / INDEX_NAME).is_file():
        print(f"libra: no reading cache at {settings.state_dir / READS_DIR}; refusing to touch vault exports", file=sys.stderr)
        return False
    return True


def cmd_fetch(settings: Settings) -> int:
    if not _cache_ready(settings):
        return EXIT_USAGE
    try:
        r = lecture_poll.run_fetch_job(settings)
    except ValueError as exc:
        print(f"libra: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"fetch {settings.term}: {len(r.written)} new, {len(r.queued)} queued for Whisper, "
        f"{len(r.no_captions)} without captions, {len(r.errors)} errors"
    )
    for label in r.errors:
        print(f"  error: {label}")

    if r.expired:
        print("UCSD login expired: run `libra login`", file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    return EXIT_FAILED if r.errors else EXIT_OK


def cmd_login(settings: Settings, timeout: float) -> int:
    code = cmd_podcast_login(state_path(settings), timeout)
    if code != 0:
        return code
    return cmd_fetch(settings)


def cmd_whisper(
    settings: Settings,
    until_hour: int,
    *,
    now: Callable[[ZoneInfo], datetime] = datetime.now,
) -> int:
    count = 0
    while now(settings.zone).hour < until_hour:
        path = lecture_poll.run_whisper_job(settings)
        if path is None:
            break
        count += 1
    remaining = _queued(settings)
    print(f"whisper: {count} transcribed, {remaining} queued")
    return EXIT_OK


def parse_pages(spec: str | None) -> tuple[int | None, int | None]:
    if spec is None:
        return None, None
    if "-" in spec:
        a, b = spec.split("-", 1)
        if not a.isdigit() or not b.isdigit():
            raise ReadError("invalid_pages")
        return int(a), int(b)
    if not spec.isdigit():
        raise ReadError("invalid_pages")
    n = int(spec)
    return n, n


def cmd_read(
    settings: Settings,
    course: str,
    path: str,
    pages: str | None,
    fetch: bool,
) -> int:
    try:
        first, last = parse_pages(pages)
        if fetch:
            settings = load_secrets(settings)
        result = read_pages(
            settings,
            course,
            path,
            first=first,
            last=last,
            fetch=fetch,
        )
    except ReadError as exc:
        print(json.dumps({"ok": False, "error": exc.code}))
        return EXIT_FAILED

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_export(settings: Settings) -> int:
    if settings.obsidian_academic_vault_dir is None:
        print("libra: LIBRA_VAULT_DIR is not set", file=sys.stderr)
        return EXIT_USAGE
    if not _cache_ready(settings):
        return EXIT_USAGE
    lecture_poll.refresh_exports(settings)
    print("export: maps and readings refreshed")
    return EXIT_OK


def cmd_status(
    settings: Settings,
    *,
    now: Callable[[ZoneInfo], datetime] = datetime.now,
) -> int:
    vault = str(settings.obsidian_academic_vault_dir) if settings.obsidian_academic_vault_dir else "not set"
    print(f"vault: {vault}")
    print(f"term: {settings.term or 'not set'}")

    state = state_path(settings)
    if state.exists():
        hours = (now(settings.zone).timestamp() - state.stat().st_mtime) / 3600
        print(f"login state: saved {hours:.1f} h ago")
    else:
        print("login state: none (run `libra login`)")

    print(f"whisper queue: {_queued(settings)}")
    return EXIT_OK


def cmd_ocr(settings: Settings, image: str, notes: bool, mime: str | None, *, stdin: BinaryIO | None = None) -> int:
    if image == "-":
        data: bytes | Path
        if stdin is not None:
            data = stdin.read()
        else:
            data = sys.stdin.buffer.read()
    else:
        image_path = Path(image)
        if not image_path.is_file():
            print(f"libra: no such image: {image}", file=sys.stderr)
            return EXIT_USAGE
        data = image_path

    settings = load_secrets(settings)
    prompt = NOTES_OCR_PROMPT if notes else DEFAULT_OCR_PROMPT

    try:
        result = transcribe_image(data, settings, mime=mime, prompt=prompt)
    except GeminiError as exc:
        print(f"libra: ocr failed: {exc}", file=sys.stderr)
        return EXIT_FAILED

    if result is None:
        print("libra: ocr returned no text", file=sys.stderr)
        return EXIT_FAILED

    print(result)
    return EXIT_OK
