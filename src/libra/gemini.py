"""
libra.gemini
──────────────────────
Client for any OpenAI-compatible chat-completions endpoint (Gemini by default,
OpenRouter for the Stage 8 fallback via `url`).
"""
from __future__ import annotations

from typing import Any

import httpx

from libra.errors import ProviderError

GEMINI_CHAT_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


class GeminiError(ProviderError):
    """Gemini API call failed."""


class GeminiCapError(GeminiError):
    """Spending cap or prepaid credit exhausted (Gemini 429 "spending cap", OpenRouter 402)."""


class GeminiRecitationError(GeminiError):
    """Model withheld content for recitation (finish_reason contains RECITATION)."""


def chat(
    messages: list[dict[str, Any]],
    model: str,
    *,
    api_key: str | None,
    client: httpx.Client | None = None,
    reasoning_effort: str | None = None,
    timeout_s: float = 60.0,
    url: str = GEMINI_CHAT_URL,
    json_mode: bool = False,
) -> str:
    if not api_key:
        raise GeminiError(f"{model}: not configured")

    def do_request(http_client: httpx.Client) -> str:
        try:
            request_body: dict[str, Any] = {"model": model, "messages": messages}
            if reasoning_effort is not None:
                request_body["reasoning_effort"] = reasoning_effort
            if json_mode:
                request_body["response_format"] = {"type": "json_object"}

            response = http_client.post(
                url,
                json=request_body,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"].get("content")
            if not isinstance(content, str):
                reason = choice.get("finish_reason") or "none"
                if "RECITATION" in str(reason).upper():
                    raise GeminiRecitationError(f"{model}: no content (finish_reason {reason})")
                raise GeminiError(f"{model}: no content (finish_reason {reason})")
            return content.strip()
        except httpx.TimeoutException as exc:
            raise GeminiError(f"{model}: timeout") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if (status == 429 and "spending cap" in exc.response.text.lower()) or status == 402:
                raise GeminiCapError(f"{model}: HTTP {status}") from exc
            raise GeminiError(f"{model}: HTTP {status}") from exc
        except httpx.HTTPError as exc:
            raise GeminiError(f"{model}: network error") from exc
        except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise GeminiError(f"{model}: malformed response") from exc

    if client is not None:
        return do_request(client)

    with httpx.Client(timeout=timeout_s) as owned_client:
        return do_request(owned_client)
