import logging
import types
from pathlib import Path

import pytest

pytest.importorskip("anki")
from anki.sync_pb2 import SyncCollectionResponse

from libra.config import Settings
from libra.study.anki_sync import (
    AnkiAuth,
    AnkiSyncError,
    add_cards,
    collection_path,
    load_auth,
    open_collection,
    sync,
)


class FakeCol:
    def __init__(self, notes: int, required: int):
        self._notes = notes
        self._required = required
        self.calls: list[str] = []
        self.full_kwargs: dict = {}
        self.sync_media: bool | None = None
        self.reopen_after_full_sync: bool | None = None

    def note_count(self) -> int:
        return self._notes

    def sync_collection(self, auth, sync_media: bool):
        self.calls.append("sync_collection")
        self.sync_media = sync_media
        return types.SimpleNamespace(
            required=self._required, new_endpoint="", server_media_usn=7
        )

    def close_for_full_sync(self):
        self.calls.append("close_for_full_sync")

    def full_upload_or_download(self, **kwargs):
        self.calls.append("full_upload_or_download")
        self.full_kwargs = kwargs

    def reopen(self, after_full_sync: bool = False):
        self.calls.append("reopen")
        self.reopen_after_full_sync = after_full_sync


def _auth() -> AnkiAuth:
    return AnkiAuth("hkey")


def test_load_auth_missing(tmp_path: Path):
    settings = Settings(state_dir=tmp_path)
    assert load_auth(settings) is None


def test_load_auth_hkey_only(tmp_path: Path):
    settings = Settings(state_dir=tmp_path, anki_hkey="k1")
    assert load_auth(settings) == AnkiAuth("k1", None)


def test_load_auth_both(tmp_path: Path):
    settings = Settings(
        state_dir=tmp_path,
        anki_hkey="k1",
        anki_endpoint="https://example.com",
    )
    assert load_auth(settings) == AnkiAuth("k1", "https://example.com")


def test_repr_does_not_leak_secret():
    assert "secret" not in repr(AnkiAuth("secret"))


@pytest.mark.parametrize("required", [SyncCollectionResponse.NO_CHANGES, SyncCollectionResponse.NORMAL_SYNC])
def test_sync_no_full(required):
    col = FakeCol(notes=0, required=required)
    sync(col, _auth())
    assert col.calls == ["sync_collection"]
    assert col.sync_media is False


@pytest.mark.parametrize("required", [SyncCollectionResponse.FULL_SYNC, SyncCollectionResponse.FULL_DOWNLOAD])
def test_sync_full_fresh(required):
    col = FakeCol(notes=0, required=required)
    sync(col, _auth())
    assert col.calls == [
        "sync_collection",
        "close_for_full_sync",
        "full_upload_or_download",
        "reopen",
    ]
    assert col.full_kwargs["upload"] is False
    assert col.full_kwargs["server_usn"] == 7
    assert col.reopen_after_full_sync is True


@pytest.mark.parametrize(
    "required",
    [
        SyncCollectionResponse.FULL_SYNC,
        SyncCollectionResponse.FULL_DOWNLOAD,
        SyncCollectionResponse.FULL_UPLOAD,
    ],
)
def test_sync_full_non_fresh_raises(required):
    col = FakeCol(notes=5, required=required)
    with pytest.raises(AnkiSyncError):
        sync(col, _auth())
    assert "full_upload_or_download" not in col.calls


def test_sync_full_upload_fresh_raises():
    col = FakeCol(notes=0, required=SyncCollectionResponse.FULL_UPLOAD)
    with pytest.raises(AnkiSyncError):
        sync(col, _auth())
    assert "full_upload_or_download" not in col.calls


def test_open_collection_creates_file(tmp_path: Path):
    col = open_collection(tmp_path)
    try:
        assert collection_path(tmp_path).exists()
    finally:
        col.close()


def test_add_cards(tmp_path: Path):
    col = open_collection(tmp_path)
    try:
        notes = [("semai-a", "Q1", "A1"), ("semai-b", "Q2", "A2")]
        added = add_cards(col, "Self study::Test", notes, ["semai", "lesson::x"])
        assert added == 2

        note_ids = col.find_notes('deck:"Self study::Test"')
        assert len(note_ids) == 2

        nid = col.db.scalar("select id from notes where guid = ?", "semai-a")
        note = col.get_note(nid)
        assert note["Front"] == "Q1"
        assert note["Back"] == "A1"
        assert "semai" in note.tags

        assert add_cards(col, "Self study::Test", notes, ["semai", "lesson::x"]) == 0
    finally:
        col.close()


def test_add_cards_is_all_or_nothing(tmp_path: Path, monkeypatch) -> None:
    col = open_collection(tmp_path)
    original_add_notes = col.add_notes

    def failing(requests):
        for r in requests:
            if r.note.guid == "semai-c":
                r.note.fields = ["only one"]
        return original_add_notes(requests)

    monkeypatch.setattr(col, "add_notes", failing)
    try:
        with pytest.raises(Exception):
            add_cards(
                col,
                "Self study::Test",
                [
                    ("semai-a", "Q1", "A1"),
                    ("semai-b", "Q2", "A2"),
                    ("semai-c", "Q3", "A3"),
                ],
                ["semai"],
            )
        assert col.note_count() == 0
    finally:
        col.close()


def test_add_cards_dedupes_guid_within_batch(tmp_path: Path) -> None:
    col = open_collection(tmp_path)
    try:
        assert (
            add_cards(
                col,
                "Self study::Test",
                [("semai-a", "Q1", "A1"), ("semai-a", "Q1 again", "A1 again")],
                ["semai"],
            )
            == 1
        )
        assert col.note_count() == 1
        note = col.get_note(col.db.scalar("select id from notes where guid = ?", "semai-a"))
        assert note["Front"] == "Q1"
    finally:
        col.close()


def test_add_cards_warns_on_changed_back_in_collection(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="libra.study.anki_sync")

    col = open_collection(tmp_path)
    try:
        add_cards(col, "Self study::Test", [("semai-a", "Q1", "A1")], ["semai"])
        assert (
            add_cards(col, "Self study::Test", [("semai-a", "Q1", "A2")], ["semai"])
            == 0
        )

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "semai-a" in warnings[0].getMessage()
        assert "Self study::Test" in warnings[0].getMessage()

        note = col.get_note(col.db.scalar("select id from notes where guid = ?", "semai-a"))
        assert note["Back"] == "A1"
    finally:
        col.close()


def test_add_cards_same_back_is_silent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="libra.study.anki_sync")

    col = open_collection(tmp_path)
    try:
        add_cards(col, "Self study::Test", [("semai-a", "Q1", "A1")], ["semai"])
        assert (
            add_cards(col, "Self study::Test", [("semai-a", "Q1", "A1")], ["semai"])
            == 0
        )

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 0
    finally:
        col.close()


def test_add_cards_warns_on_changed_back_in_batch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="libra.study.anki_sync")

    col = open_collection(tmp_path)
    try:
        assert (
            add_cards(
                col,
                "Self study::Test",
                [("semai-a", "Q1", "A1"), ("semai-a", "Q1", "A2")],
                ["semai"],
            )
            == 1
        )

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "semai-a" in warnings[0].getMessage()

        note = col.get_note(col.db.scalar("select id from notes where guid = ?", "semai-a"))
        assert note["Back"] == "A1"
    finally:
        col.close()
