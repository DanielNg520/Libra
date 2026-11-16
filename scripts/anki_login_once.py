#!/usr/bin/env python3
"""Log in to AnkiWeb once and store the sync key in sops (Libra ADR-0002). Run: `uv run --extra anki python scripts/anki_login_once.py`. Email and password come from sops (`LIBRA_ANKIWEB_USER`, `LIBRA_ANKIWEB_PASSWORD`); a missing one is prompted for."""

from __future__ import annotations

import getpass
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import libra.config
from libra.study.anki_sync import ENDPOINT_SECRET, HKEY_SECRET

SECRETS_PATH = libra.config.secrets_path()


def _sops_set(key: str, value: str) -> None:
    subprocess.run(
        ["sops", "set", str(SECRETS_PATH), json.dumps([key]), json.dumps(value)],
        check=True,
    )


def main() -> int:
    credentials = libra.config._read_sops_secrets(
        SECRETS_PATH, ("LIBRA_ANKIWEB_USER", "LIBRA_ANKIWEB_PASSWORD")
    )
    username = (
        credentials.get("LIBRA_ANKIWEB_USER") or input("AnkiWeb email: ")
    ).strip()
    password = credentials.get("LIBRA_ANKIWEB_PASSWORD") or getpass.getpass(
        "AnkiWeb password: "
    )
    if not username or not password:
        print("aborted: empty input", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        from anki.collection import Collection

        col = Collection(str(Path(tmp) / "login.anki2"))
        try:
            auth = col.sync_login(username, password, None)
        except Exception as exc:
            print(f"login failed: {type(exc).__name__}", file=sys.stderr)
            return 1
        finally:
            col.close()

    _sops_set(HKEY_SECRET, auth.hkey)
    print(f"Stored {HKEY_SECRET} in sops.")
    if auth.endpoint:
        _sops_set(ENDPOINT_SECRET, auth.endpoint)
        print(f"Stored {ENDPOINT_SECRET} in sops.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
