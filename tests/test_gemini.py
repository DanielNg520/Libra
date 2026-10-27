import json
from typing import Any

import httpx
import pytest

from libra import gemini
from libra.gemini import GEMINI_CHAT_URL, GeminiError


MESSAGES = [{"role": "user", "content": "Hello"}]
MODEL = "test-model"


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def success_handler(request: httpx.Request) -> httpx.Response:
    body = {"choices": [{"message": {"content": "  response text  "}}]}
    return httpx.Response(200, json=body)


def test_success_returns_stripped_content_and_correct_request():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        captured["body_keys"] = list(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "  response text  "}}]},
        )

    client = make_client(handler)

    result = gemini.chat(MESSAGES, MODEL, api_key="key-1", client=client)

    assert result == "response text"
    assert captured["method"] == "POST"
    assert captured["url"] == GEMINI_CHAT_URL
    assert captured["headers"]["authorization"] == "Bearer key-1"
    assert captured["body"] == {"model": MODEL, "messages": MESSAGES}
    assert captured["body_keys"] == ["model", "messages"]


def test_json_mode_sends_response_format():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = make_client(handler)
    result = gemini.chat(
        MESSAGES,
        MODEL,
        api_key="key-1",
        client=client,
        reasoning_effort="low",
        json_mode=True,
    )

    assert result == "{}"
    assert captured["body"] == {
        "model": MODEL,
        "messages": MESSAGES,
        "reasoning_effort": "low",
        "response_format": {"type": "json_object"},
    }


@pytest.mark.parametrize("missing_key", [None, ""])
def test_missing_api_key_raises_without_calling_transport(missing_key):
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    client = make_client(handler)

    with pytest.raises(GeminiError):
        gemini.chat(MESSAGES, MODEL, api_key=missing_key, client=client)

    assert not called


@pytest.mark.parametrize("status_code", [500, 429])
def test_http_error_raises_with_status_and_no_body(status_code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="SECRET-BODY")

    client = make_client(handler)

    with pytest.raises(GeminiError) as exc_info:
        gemini.chat(MESSAGES, MODEL, api_key="key-1", client=client)

    message = str(exc_info.value)
    assert MODEL in message
    assert str(status_code) in message
    assert "SECRET-BODY" not in message


@pytest.mark.parametrize(
    "response_factory",
    [
        lambda: httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
        lambda: httpx.Response(200, json={"no_choices": []}),
        lambda: httpx.Response(200, text="not json"),
    ],
)
def test_malformed_response_raises(response_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return response_factory()

    client = make_client(handler)

    with pytest.raises(GeminiError):
        gemini.chat(MESSAGES, MODEL, api_key="key-1", client=client)


def test_refusal_names_finish_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"choices": [{"finish_reason": "content_filter: RECITATION", "message": {"role": "assistant"}}]}
        return httpx.Response(200, json=body)

    client = make_client(handler)

    with pytest.raises(GeminiError) as exc_info:
        gemini.chat(MESSAGES, MODEL, api_key="key-1", client=client)

    assert "RECITATION" in str(exc_info.value)


def test_recitation_refusal_raises_recitation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"choices": [{"finish_reason": "content_filter: RECITATION", "message": {"role": "assistant"}}]}
        return httpx.Response(200, json=body)

    with pytest.raises(gemini.GeminiRecitationError) as exc_info:
        gemini.chat(MESSAGES, MODEL, api_key="key-1", client=make_client(handler))
    assert isinstance(exc_info.value, gemini.GeminiError)


def test_other_refusal_is_not_recitation_error():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"choices": [{"finish_reason": "SAFETY", "message": {"role": "assistant"}}]}
        return httpx.Response(200, json=body)

    with pytest.raises(gemini.GeminiError) as exc_info:
        gemini.chat(MESSAGES, MODEL, api_key="key-1", client=make_client(handler))
    assert not isinstance(exc_info.value, gemini.GeminiRecitationError)
    assert "SAFETY" in str(exc_info.value)


def test_connect_timeout_sets_cause():
    timeout_exc = httpx.ConnectTimeout("connection timed out")

    def handler(request: httpx.Request) -> httpx.Response:
        raise timeout_exc

    client = make_client(handler)

    with pytest.raises(GeminiError) as exc_info:
        gemini.chat(MESSAGES, MODEL, api_key="key-1", client=client)

    assert exc_info.value.__cause__ is timeout_exc


def test_passed_client_not_closed():
    client = make_client(success_handler)

    gemini.chat(MESSAGES, MODEL, api_key="key-1", client=client)

    assert not client.is_closed


def test_created_client_closed(monkeypatch):
    created_client: httpx.Client | None = None
    real_client_class = httpx.Client

    def factory(*args, **kwargs):
        nonlocal created_client
        created_client = real_client_class(
            transport=httpx.MockTransport(success_handler)
        )
        return created_client

    monkeypatch.setattr(httpx, "Client", factory)

    gemini.chat(MESSAGES, MODEL, api_key="key-1")

    assert created_client is not None
    assert created_client.is_closed


def test_api_key_never_in_exception_message():
    secret = "super-secret-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="SECRET-BODY")

    client = make_client(handler)

    with pytest.raises(GeminiError) as exc_info:
        gemini.chat(MESSAGES, MODEL, api_key=secret, client=client)

    assert secret not in str(exc_info.value)
    assert repr(secret) not in repr(exc_info.value)


def test_chat_with_reasoning_effort() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {
            "model": MODEL,
            "messages": MESSAGES,
            "reasoning_effort": "low",
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "  response text  "}}]},
        )

    client = make_client(handler)
    output = gemini.chat(
        MESSAGES,
        MODEL,
        api_key="key-1",
        client=client,
        reasoning_effort="low",
    )

    assert output == "response text"


def test_custom_url_is_used() -> None:
    captured_url: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_url
        captured_url = str(request.url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "  response text  "}}]},
        )

    client = make_client(handler)
    output = gemini.chat(
        MESSAGES,
        MODEL,
        api_key="key-1",
        client=client,
        url="https://openrouter.ai/api/v1/chat/completions",
    )

    assert captured_url == "https://openrouter.ai/api/v1/chat/completions"
    assert output == "response text"


def test_spending_cap_429_raises_cap_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            text='{"error": {"code": 429, "message": "Your billing account has exceeded its monthly SPENDING CAP.", "status": "RESOURCE_EXHAUSTED"}}',
        )

    client = make_client(handler)

    with pytest.raises(gemini.GeminiCapError) as exc_info:
        gemini.chat(MESSAGES, MODEL, api_key="key-1", client=client)

    assert isinstance(exc_info.value, GeminiError)
    assert MODEL in str(exc_info.value)
    assert "429" in str(exc_info.value)
    assert "billing" not in str(exc_info.value)


def test_rate_limit_429_is_not_cap_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            text='{"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota).", "status": "RESOURCE_EXHAUSTED"}}',
        )

    client = make_client(handler)

    with pytest.raises(GeminiError) as exc_info:
        gemini.chat(MESSAGES, MODEL, api_key="key-1", client=client)

    assert not isinstance(exc_info.value, gemini.GeminiCapError)


def test_payment_required_402_raises_cap_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            text='{"error": {"code": 402, "message": "Insufficient credits"}}',
        )

    client = make_client(handler)

    with pytest.raises(gemini.GeminiCapError) as exc_info:
        gemini.chat(
            MESSAGES,
            MODEL,
            api_key="key-1",
            client=client,
            url="https://openrouter.ai/api/v1/chat/completions",
        )

    assert "402" in str(exc_info.value)
    assert "Insufficient" not in str(exc_info.value)
