"""Tests for libra.lecture_whisper."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import types
from pathlib import Path
from typing import Any

import pytest

from libra import lecture_whisper as lw


class FakeModel:
    def __init__(self, segments: list[types.SimpleNamespace]) -> None:
        self.segments = segments
        self.calls: list[tuple[object, dict[str, Any]]] = []

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Any, Any]:
        self.calls.append((audio, kwargs))
        return iter(self.segments), types.SimpleNamespace(duration=100.0)


def _queue(
    audio_dir: Path, entry_id: str, transcript: Path, label: str = "ECE 158A Lecture 2026-10-08"
) -> tuple[Path, Path]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio = audio_dir / f"{entry_id}.m4a"
    audio.write_bytes(b"AUDIO")
    sidecar = audio_dir / f"{entry_id}.json"
    sidecar.write_text(
        json.dumps({"transcript": str(transcript), "label": label, "entry_id": entry_id}),
        encoding="utf-8",
    )
    return audio, sidecar


def _no_load() -> lw.WhisperModelLike:
    raise AssertionError("load must not be called")


def test_transcribe_audio_kwargs_rounding_and_blanks() -> None:
    segments = [
        types.SimpleNamespace(start=0.123, end=4.567, text="  Hello "),
        types.SimpleNamespace(start=5.0, end=6.0, text="   "),
        types.SimpleNamespace(start=6.004, end=9.999, text="World"),
    ]
    model = FakeModel(segments)
    sentinel = object()
    result = lw.transcribe_audio(sentinel, model)
    assert result == [
        {"start": 0.12, "end": 4.57, "text": "Hello"},
        {"start": 6.0, "end": 10.0, "text": "World"},
    ]
    assert len(model.calls) == 1
    audio, kwargs = model.calls[0]
    assert audio is sentinel
    assert kwargs == {
        "language": "en",
        "beam_size": 5,
        "vad_filter": True,
        "condition_on_previous_text": False,
    }


def test_next_queued_missing_dir(tmp_path: Path) -> None:
    assert lw.next_queued(tmp_path / "nope") is None


def test_next_queued_skips_sidecar_without_audio_and_picks_oldest(tmp_path: Path) -> None:
    audio_dir = tmp_path / "queue"
    audio_dir.mkdir()
    transcript = tmp_path / "vault" / "Transcripts" / "ECE 158A" / "2026-10-08.json"

    _, sidecar_old = _queue(audio_dir, "1_old", transcript)
    _, sidecar_new = _queue(audio_dir, "1_new", transcript)
    _, sidecar_lone = _queue(audio_dir, "1_lone", transcript)
    (audio_dir / "1_lone.m4a").unlink()

    os.utime(sidecar_old, (1000, 1000))
    os.utime(sidecar_new, (2000, 2000))
    os.utime(sidecar_lone, (500, 500))

    assert lw.next_queued(audio_dir) == sidecar_old


def test_transcribe_next_empty_queue_does_not_load(tmp_path: Path) -> None:
    audio_dir = tmp_path / "queue"
    audio_dir.mkdir()
    assert lw.transcribe_next(audio_dir, load=_no_load) is None


def test_transcribe_next_success(tmp_path: Path) -> None:
    audio_dir = tmp_path / "queue"
    transcript = tmp_path / "vault" / "Transcripts" / "ECE 158A" / "2026-10-08.json"
    audio, sidecar = _queue(audio_dir, "1_e1", transcript)

    model = FakeModel(
        [
            types.SimpleNamespace(start=0.0, end=2.0, text="Intro"),
            types.SimpleNamespace(start=2.5, end=4.0, text="Sinks"),
        ]
    )
    decoded_paths: list[Path] = []

    def decode(path: Path) -> str:
        decoded_paths.append(path)
        return "PCM"

    result = lw.transcribe_next(audio_dir, load=lambda: model, decode=decode)
    assert result == transcript
    assert json.loads(transcript.read_text(encoding="utf-8")) == [
        {"start": 0.0, "end": 2.0, "text": "Intro"},
        {"start": 2.5, "end": 4.0, "text": "Sinks"},
    ]
    assert decoded_paths == [audio]
    assert len(model.calls) == 1
    assert model.calls[0][0] == "PCM"
    assert not audio.exists()
    assert not sidecar.exists()


def test_transcribe_next_existing_transcript_drops_queue(tmp_path: Path) -> None:
    audio_dir = tmp_path / "queue"
    transcript = tmp_path / "vault" / "Transcripts" / "ECE 158A" / "2026-10-08.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("[]", encoding="utf-8")
    audio, sidecar = _queue(audio_dir, "1_e2", transcript)

    assert lw.transcribe_next(audio_dir, load=_no_load) is None
    assert not audio.exists()
    assert not sidecar.exists()
    assert transcript.read_text(encoding="utf-8") == "[]"


def test_transcribe_next_load_failure_keeps_queue_and_hides_message(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    audio_dir = tmp_path / "queue"
    transcript = tmp_path / "vault" / "Transcripts" / "ECE 158A" / "2026-10-08.json"
    audio, sidecar = _queue(audio_dir, "1_e3", transcript)

    def load() -> lw.WhisperModelLike:
        raise RuntimeError("SECRET detail")

    with caplog.at_level(logging.WARNING):
        assert lw.transcribe_next(audio_dir, load=load) is None
    assert audio.exists()
    assert sidecar.exists()
    assert not transcript.exists()
    assert "RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text


def test_transcribe_next_decode_failure_parks_audio(tmp_path: Path) -> None:
    audio_dir = tmp_path / "queue"
    transcript = tmp_path / "vault" / "Transcripts" / "ECE 158A" / "2026-10-08.json"
    audio, sidecar = _queue(audio_dir, "1_e4", transcript)

    def decode(path: Path) -> Any:
        raise subprocess.CalledProcessError(1, ["ffmpeg"])

    assert lw.transcribe_next(audio_dir, load=lambda: FakeModel([]), decode=decode) is None
    assert not audio.exists()
    assert (audio_dir / "1_e4.m4a.failed").exists()
    assert sidecar.exists()
    assert lw.next_queued(audio_dir) is None


def test_transcribe_next_parked_entry_unblocks_queue(tmp_path: Path) -> None:
    audio_dir = tmp_path / "queue"
    old_transcript = tmp_path / "vault" / "Transcripts" / "ECE 158A" / "2026-10-06.json"
    new_transcript = tmp_path / "vault" / "Transcripts" / "ECE 158A" / "2026-10-08.json"
    old_audio, old_sidecar = _queue(audio_dir, "1_old", old_transcript)
    new_audio, new_sidecar = _queue(audio_dir, "1_new", new_transcript)
    os.utime(old_sidecar, (1, 1))
    model = FakeModel([types.SimpleNamespace(start=0.0, end=1.5, text="hello")])

    def decode(path: Path) -> Any:
        if path.name == "1_old.m4a":
            raise subprocess.CalledProcessError(1, ["ffmpeg"])
        return "PCM"

    assert lw.transcribe_next(audio_dir, load=lambda: model, decode=decode) is None
    assert not old_audio.exists()
    assert (audio_dir / "1_old.m4a.failed").exists()
    result = lw.transcribe_next(audio_dir, load=lambda: model, decode=decode)
    assert result == new_transcript
    assert result.exists()
    assert not new_audio.exists()
    assert not new_sidecar.exists()
    assert old_sidecar.exists()


def test_transcribe_next_no_speech_drops_audio_keeps_sidecar(tmp_path: Path) -> None:
    audio_dir = tmp_path / "queue"
    transcript = tmp_path / "vault" / "Transcripts" / "ECE 158A" / "2026-10-08.json"
    audio, sidecar = _queue(audio_dir, "1_e5", transcript)
    model = FakeModel([types.SimpleNamespace(start=0.0, end=1.0, text="  ")])

    assert lw.transcribe_next(audio_dir, load=lambda: model, decode=lambda p: "PCM") is None
    assert not audio.exists()
    assert sidecar.exists()
    assert not transcript.exists()
    assert lw.next_queued(audio_dir) is None


def test_transcribe_next_unreadable_sidecar(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    audio_dir = tmp_path / "queue"
    audio_dir.mkdir()
    (audio_dir / "1_bad.m4a").write_bytes(b"AUDIO")
    (audio_dir / "1_bad.json").write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert lw.transcribe_next(audio_dir, load=_no_load) is None
    assert not (audio_dir / "1_bad.m4a").exists()
    assert (audio_dir / "1_bad.m4a.failed").exists()
    assert (audio_dir / "1_bad.json").exists()
    assert "1_bad.json: unreadable Whisper queue entry" in caplog.text
