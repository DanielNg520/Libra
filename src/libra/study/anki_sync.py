"""AnkiWeb sync of Libra's Anki collection (Libra ADR-0002); `anki` is imported lazily."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from libra.config import Settings

log = logging.getLogger(__name__)

__all__ = [
    "COLLECTION_DIR",
    "COLLECTION_FILE",
    "HKEY_SECRET",
    "ENDPOINT_SECRET",
    "NOTE_TYPE",
    "AnkiSyncError",
    "AnkiAuth",
    "load_auth",
    "collection_path",
    "open_collection",
    "sync",
    "add_cards",
]

COLLECTION_DIR = "anki"
COLLECTION_FILE = "collection.anki2"
HKEY_SECRET = "LIBRA_ANKIWEB_HKEY"
ENDPOINT_SECRET = "LIBRA_ANKIWEB_ENDPOINT"
NOTE_TYPE = "Basic"


class AnkiSyncError(RuntimeError):
    """The collection cannot be synced or written safely."""


@dataclass(frozen=True)
class AnkiAuth:
    hkey: str
    endpoint: str | None = None

    def __repr__(self) -> str:
        return "AnkiAuth(hkey=***)"


def load_auth(settings: Settings) -> AnkiAuth | None:
    hkey = settings.anki_hkey
    if not hkey:
        return None
    endpoint = settings.anki_endpoint or None
    return AnkiAuth(hkey, endpoint)


def collection_path(state_dir: Path) -> Path:
    return state_dir / COLLECTION_DIR / COLLECTION_FILE


def open_collection(state_dir: Path) -> Any:
    path = collection_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    from anki.collection import Collection

    return Collection(str(path))


def _sync_auth(auth: AnkiAuth, endpoint: str | None = None) -> Any:
    from anki.sync import SyncAuth

    chosen = endpoint or auth.endpoint
    if chosen:
        return SyncAuth(hkey=auth.hkey, endpoint=chosen)
    return SyncAuth(hkey=auth.hkey)


def sync(col: Any, auth: AnkiAuth) -> None:
    from anki.sync_pb2 import SyncCollectionResponse

    fresh = col.note_count() == 0
    out = col.sync_collection(_sync_auth(auth), sync_media=False)

    if out.new_endpoint:
        log.info(
            "anki: AnkiWeb moved this account to a new endpoint; store it as %s",
            ENDPOINT_SECRET,
        )

    required = out.required

    if required in (SyncCollectionResponse.NO_CHANGES, SyncCollectionResponse.NORMAL_SYNC):
        return

    if fresh and required in (
        SyncCollectionResponse.FULL_SYNC,
        SyncCollectionResponse.FULL_DOWNLOAD,
    ):
        col.close_for_full_sync()
        try:
            col.full_upload_or_download(
                auth=_sync_auth(auth, out.new_endpoint or None),
                server_usn=out.server_media_usn,
                upload=False,
            )
        finally:
            col.reopen(after_full_sync=True)
        log.info("anki: downloaded the AnkiWeb collection")
        return

    raise AnkiSyncError(
        f"AnkiWeb asks for a full sync (required={required}); Libra never uploads a whole collection"
    )


def add_cards(
    col: Any,
    deck: str,
    notes: Sequence[tuple[str, str, str]],
    tags: Sequence[str],
) -> int:
    """Add the notes not yet in the collection, all in one transaction; return how many were added."""
    model = col.models.by_name(NOTE_TYPE)
    if model is None:
        raise AnkiSyncError("note type Basic is missing")
    from anki.collection import AddNoteRequest

    deck_id = col.decks.id(deck, create=True)
    requests = []
    seen: dict[str, str] = {}

    for guid, front_html, back_html in notes:
        existing = seen.get(guid)
        if existing is None:
            note_id = col.db.scalar("select id from notes where guid = ?", guid)
            if note_id is not None:
                existing = col.get_note(note_id)["Back"]
        if existing is not None:
            if existing != back_html:
                log.warning("anki: %s note %s exists with a different back; kept the existing one", deck, guid)
            continue

        seen[guid] = back_html
        note = col.new_note(model)
        note["Front"] = front_html
        note["Back"] = back_html
        note.tags = list(tags)
        note.guid = guid
        requests.append(AddNoteRequest(note, deck_id))

    if requests:
        col.add_notes(requests)

    return len(requests)
