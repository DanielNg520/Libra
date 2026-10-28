"""Image transcription through Gemini, for `libra ocr`."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from libra.config import Settings
from libra.gemini import chat

DEFAULT_OCR_PROMPT = "Transcribe any handwritten text in this image verbatim. Transcription only, no commentary."
NOTES_OCR_PROMPT = (
    "Transcribe all text in this image, handwritten and printed, verbatim. Keep line breaks, bullets and headings. "
    "Write [?] for any illegible word. Transcription only, no commentary. Write every mathematical expression as LaTeX, "
    "inline math between single dollar signs and display (own-line) equations between double dollar signs. "
    "Write [?] in place of any single symbol, subscript, exponent or operator that cannot be read with confidence, never guess it. "
    "Never simplify, correct or complete a formula, reproduce exactly what is written even if it looks wrong."
)


def transcribe_image(
    image: bytes | Path,
    settings: Settings,
    client: httpx.Client | None = None,
    *,
    mime: str | None = None,
    prompt: str = DEFAULT_OCR_PROMPT,
) -> str | None:
    """Transcribe an image through Gemini and return the extracted text."""
    if isinstance(image, Path):
        data = image.read_bytes()
        guessed = mimetypes.guess_type(image.name)[0]
    else:
        data = image
        guessed = None

    resolved_mime = mime or guessed or "image/jpeg"
    data_uri = f"data:{resolved_mime};base64,{base64.b64encode(data).decode('ascii')}"

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }
    ]

    # low effort because a thinking Flash model takes about 30 s per image against the 60 s timeout
    reply = chat(
        messages,
        settings.ocr_model,
        api_key=settings.gemini_api_key,
        client=client,
        reasoning_effort="low",
    )

    stripped = reply.strip()
    return stripped or None
