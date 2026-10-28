from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from libra import commands
from libra.config import Settings
from libra.gemini import GeminiCapError, GeminiError
from libra.ocr import DEFAULT_OCR_PROMPT, NOTES_OCR_PROMPT, transcribe_image


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "GEMINI_API_KEY": "key-1",
        }
    )


def _client_with_handler(handler: Any) -> tuple[httpx.Client, Any]:
    captured: dict[str, Any] = {}
    captured["requests"] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        captured["requests"].append(
            {
                "body": json.loads(request.content),
                "headers": dict(request.headers),
            }
        )
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped)), captured


def _json_response(content: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "choices": [{"message": {"content": content}}],
        },
    )


def test_transcribe_image_bytes_default_prompt(
    settings: Settings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response("  hello  ")

    client, captured = _client_with_handler(handler)

    result = transcribe_image(b"\x89PNG", settings, client=client)

    assert result == "hello"
    assert len(captured["requests"]) == 1
    req = captured["requests"][0]
    assert req["body"]["model"] == settings.ocr_model
    assert req["body"]["reasoning_effort"] == "low"
    assert req["headers"]["authorization"] == "Bearer key-1"

    messages = req["body"]["messages"]
    assert len(messages) == 1
    user_message = messages[0]
    assert user_message["role"] == "user"
    content = user_message["content"]
    assert len(content) == 2
    assert content[0] == {"type": "text", "text": DEFAULT_OCR_PROMPT}
    assert content[1]["type"] == "image_url"
    expected_uri = "data:image/jpeg;base64," + base64.b64encode(b"\x89PNG").decode()
    assert content[1]["image_url"]["url"] == expected_uri


def test_transcribe_image_path_guesses_mime(
    settings: Settings, tmp_path: Path
) -> None:
    image_path = tmp_path / "board.png"
    image_path.write_bytes(b"png-bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response("text")

    client, captured = _client_with_handler(handler)

    transcribe_image(image_path, settings, client=client)

    req = captured["requests"][0]
    content = req["body"]["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_transcribe_image_explicit_mime_wins(
    settings: Settings, tmp_path: Path
) -> None:
    image_path = tmp_path / "board.png"
    image_path.write_bytes(b"png-bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response("text")

    client, captured = _client_with_handler(handler)

    transcribe_image(
        image_path, settings, client=client, mime="image/webp"
    )

    req = captured["requests"][0]
    content = req["body"]["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith(
        "data:image/webp;base64,"
    )


def test_transcribe_image_custom_prompt(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response("text")

    client, captured = _client_with_handler(handler)

    transcribe_image(
        b"raw", settings, client=client, prompt=NOTES_OCR_PROMPT
    )

    req = captured["requests"][0]
    content = req["body"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": NOTES_OCR_PROMPT}


def test_transcribe_image_whitespace_reply_returns_none(
    settings: Settings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response("   ")

    client, _ = _client_with_handler(handler)

    assert transcribe_image(b"raw", settings, client=client) is None


def test_transcribe_image_spending_cap_raises_gemini_cap_error(
    settings: Settings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            text="spending cap exceeded",
        )

    client, _ = _client_with_handler(handler)

    with pytest.raises(GeminiCapError):
        transcribe_image(b"raw", settings, client=client)


@pytest.fixture
def patched_cmd(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> dict[str, Any]:
    calls: dict[str, Any] = {"transcribe": [], "load_count": 0}

    monkeypatch.setattr(
        commands,
        "load_secrets",
        lambda s: s,
    )

    def fake_transcribe(*args: Any, **kwargs: Any) -> Any:
        calls["transcribe"].append((args, kwargs))
        return calls.get("transcribe_result", "default text")

    monkeypatch.setattr(commands, "transcribe_image", fake_transcribe)

    return {
        "calls": calls,
        "fake": fake_transcribe,
    }


def test_cmd_ocr_existing_image_defaults(
    settings: Settings,
    patched_cmd: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "scan.jpg"
    image_path.write_bytes(b"jpeg")

    result = commands.cmd_ocr(settings, str(image_path), notes=False, mime=None)

    calls = patched_cmd["calls"]
    assert len(calls["transcribe"]) == 1
    args, kwargs = calls["transcribe"][0]
    assert args[0] == image_path
    assert kwargs["prompt"] == DEFAULT_OCR_PROMPT
    assert kwargs["mime"] is None

    captured = capsys.readouterr()
    assert captured.out == "default text\n"
    assert result == commands.EXIT_OK


def test_cmd_ocr_notes_and_mime(
    settings: Settings,
    patched_cmd: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "scan.jpg"
    image_path.write_bytes(b"jpeg")

    result = commands.cmd_ocr(
        settings, str(image_path), notes=True, mime="image/png"
    )

    calls = patched_cmd["calls"]
    assert len(calls["transcribe"]) == 1
    _, kwargs = calls["transcribe"][0]
    assert kwargs["prompt"] == NOTES_OCR_PROMPT
    assert kwargs["mime"] == "image/png"
    assert result == commands.EXIT_OK
    capsys.readouterr()


def test_cmd_ocr_stdin_dash(
    settings: Settings,
    patched_cmd: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = commands.cmd_ocr(
        settings,
        "-",
        notes=False,
        mime=None,
        stdin=io.BytesIO(b"raw"),
    )

    calls = patched_cmd["calls"]
    assert len(calls["transcribe"]) == 1
    args, _ = calls["transcribe"][0]
    assert args[0] == b"raw"
    assert result == commands.EXIT_OK
    capsys.readouterr()


def test_cmd_ocr_missing_path(
    settings: Settings,
    patched_cmd: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_called = {"count": 0}

    def counting_load(s: Settings) -> Settings:
        load_called["count"] += 1
        return s

    monkeypatch.setattr(commands, "load_secrets", counting_load)

    result = commands.cmd_ocr(
        settings, "/nonexistent/image.png", notes=False, mime=None
    )

    assert result == commands.EXIT_USAGE
    captured = capsys.readouterr()
    assert "no such image" in captured.err
    assert "/nonexistent/image.png" in captured.err
    assert len(patched_cmd["calls"]["transcribe"]) == 0
    assert load_called["count"] == 0


def test_cmd_ocr_gemini_error(
    settings: Settings,
    patched_cmd: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "scan.jpg"
    image_path.write_bytes(b"jpeg")

    def raising_fake(*args: Any, **kwargs: Any) -> str:
        raise GeminiError("m: timeout")

    monkeypatch.setattr(commands, "transcribe_image", raising_fake)

    result = commands.cmd_ocr(
        settings, str(image_path), notes=False, mime=None
    )

    assert result == commands.EXIT_FAILED
    captured = capsys.readouterr()
    assert "ocr failed: m: timeout" in captured.err


def test_cmd_ocr_none_result(
    settings: Settings,
    patched_cmd: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "scan.jpg"
    image_path.write_bytes(b"jpeg")

    monkeypatch.setattr(
        commands,
        "transcribe_image",
        lambda *args, **kwargs: None,
    )

    result = commands.cmd_ocr(
        settings, str(image_path), notes=False, mime=None
    )

    assert result == commands.EXIT_FAILED
    captured = capsys.readouterr()
    assert "returned no text" in captured.err


def test_cmd_ocr_load_secrets_result_used(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "scan.jpg"
    image_path.write_bytes(b"jpeg")

    marker_settings = Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "GEMINI_API_KEY": "marker-key",
        }
    )
    received: list[Settings] = []
    monkeypatch.setattr(
        commands,
        "load_secrets",
        lambda s: marker_settings,
    )

    def fake_transcribe(*args: Any, **kwargs: Any) -> str:
        received.append(args[1])
        return "text"

    monkeypatch.setattr(commands, "transcribe_image", fake_transcribe)

    result = commands.cmd_ocr(
        settings, str(image_path), notes=False, mime=None
    )

    assert result == commands.EXIT_OK
    assert len(received) == 1
    assert received[0] is marker_settings
    capsys.readouterr()
