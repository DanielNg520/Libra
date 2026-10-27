"""Transcribe queued lecture audio with local faster-whisper into transcript JSON."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from libra.lecture_fetch import audio_paths, write_transcript

log = logging.getLogger(__name__)

MODEL_NAME = "large-v3"
SAMPLE_RATE = 16000
PARKED_SUFFIX = ".failed"


class WhisperModelLike(Protocol):
    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Iterable[Any], Any]: ...


def load_model() -> WhisperModelLike:
    from faster_whisper import WhisperModel

    return WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", local_files_only=True)


def decode_audio(path: Path) -> Any:
    # faster-whisper 1.2.1 passes metadata_errors, which installed PyAV 16 rejects.
    import numpy as np

    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, np.int16).astype(np.float32) / 32768.0


def transcribe_audio(audio: Any, model: WhisperModelLike) -> list[dict]:
    segments, _ = model.transcribe(
        audio, language="en", beam_size=5, vad_filter=True, condition_on_previous_text=False
    )
    result: list[dict] = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            result.append({"start": round(segment.start, 2), "end": round(segment.end, 2), "text": text})
    return result


def _park(audio: Path, label: str) -> None:
    try:
        parked = audio.rename(audio.with_name(audio.name + PARKED_SUFFIX))
        log.warning("%s: parked queued audio as %s", label, parked.name)
    except OSError as exc:
        log.warning("%s: could not park queued audio: %s", label, type(exc).__name__)


def next_queued(audio_dir: Path) -> Path | None:
    if not audio_dir.is_dir():
        return None
    sidecars = []
    for sidecar in audio_dir.glob("*.json"):
        audio_file, _ = audio_paths(audio_dir, sidecar.stem)
        if audio_file.exists():
            sidecars.append(sidecar)
    if not sidecars:
        return None
    sidecars.sort(key=lambda p: (p.stat().st_mtime, p.name))
    return sidecars[0]


def transcribe_next(
    audio_dir: Path,
    *,
    load: Callable[[], WhisperModelLike] = load_model,
    decode: Callable[[Path], Any] = decode_audio,
) -> Path | None:
    sidecar = next_queued(audio_dir)
    if sidecar is None:
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        transcript = Path(data["transcript"])
        label = data["label"]
        audio, _ = audio_paths(audio_dir, sidecar.stem)
    except (OSError, ValueError, KeyError, TypeError):
        log.warning("%s: unreadable Whisper queue entry", sidecar.name)
        _park(audio_paths(audio_dir, sidecar.stem)[0], sidecar.name)
        return None
    if transcript.exists():
        sidecar.unlink(missing_ok=True)
        audio.unlink(missing_ok=True)
        log.info("%s: transcript already exists; dropped queued audio", label)
        return None
    try:
        model = load()
    except Exception as exc:
        log.warning("%s: Whisper failed: %s", label, type(exc).__name__)
        return None

    try:
        segments = transcribe_audio(decode(audio), model)
    except Exception as exc:
        log.warning("%s: Whisper failed: %s", label, type(exc).__name__)
        _park(audio, label)
        return None
    if not segments:
        log.warning("%s: Whisper produced no speech; audio dropped, sidecar kept", label)
        audio.unlink(missing_ok=True)
        return None
    write_transcript(transcript, segments)
    try:
        written = json.loads(transcript.read_text(encoding="utf-8"))
        if len(written) != len(segments):
            log.warning("%s: transcript verification failed", label)
            return None
    except (OSError, ValueError):
        log.warning("%s: transcript verification failed", label)
        return None
    sidecar.unlink(missing_ok=True)
    audio.unlink(missing_ok=True)
    log.info("%s: Whisper wrote %d segments", label, len(segments))
    return transcript
