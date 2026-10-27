"""Rendering and checkpointed reading of course documents into cached page transcriptions."""
import base64
import hashlib
import io
import itertools
import json
import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from PIL import Image, ImageOps
from libra.config import Settings
from libra.gemini import GeminiCapError, GeminiError, GeminiRecitationError, chat


MAX_PAGES = 150
BATCH_PAGES = 8
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
READS_DIR = "lecture_reads"

log = logging.getLogger(__name__)

READ_PROMPT = (
    "These are pages {first}-{last} of lecture material for {course}. "
    "For each page in order output a heading `### Page N` (N the absolute page number), then a faithful, complete "
    "transcription of all text, math as LaTeX in `$...$`, and a precise description of every diagram, plot, table, or "
    "circuit with its labels and values. Never summarize, merge, or skip pages. No preamble or closing remarks."
)

TEXTBOOK_READ_PROMPT = (
    "These are pages {first}-{last} of a textbook used in {course}. For each page in order output a heading `### Page N` (N the absolute page number), then study notes for that page: every definition, theorem, and key result restated in your own words; every displayed equation as LaTeX in `$...$` with its equation number; the steps of each worked example; and a precise description of every figure or table with its labels and values. Paraphrase prose, never copy sentences. Never merge or skip pages. No preamble or closing remarks."
)


class TooManyPages(Exception):
    """A document exceeds the configured page limit."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run_soffice(source: Path, workdir: Path) -> Path:
    subprocess.run(
        ["soffice", f"-env:UserInstallation={(workdir / 'lo-profile').as_uri()}", "--headless", "--convert-to", "pdf", "--outdir", str(workdir), str(source)],
        check=True,
        capture_output=True,
        timeout=300,
    )
    return workdir / f"{source.stem}.pdf"


def pdf_page_count(pdf: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf)], check=True, capture_output=True, timeout=300, text=True
    )
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise ValueError("pdfinfo did not report page count")


def _render_pdf(pdf: Path, workdir: Path, page_range: tuple[int, int] | None = None) -> list[tuple[str, bytes]]:
    pages = pdf_page_count(pdf)
    if page_range is None:
        if pages > MAX_PAGES:
            raise TooManyPages(f"{pages} pages")
        args = ["pdftoppm", "-r", "110", "-hide-annotations", "-png", str(pdf), str(workdir / "page")]
    else:
        first, last = page_range
        if not 1 <= first <= last <= pages:
            raise ValueError(f"page range {first}-{last} outside 1-{pages}")
        if last - first + 1 > MAX_PAGES:
            raise TooManyPages(f"{last - first + 1} pages")
        args = ["pdftoppm", "-r", "110", "-hide-annotations", "-png", "-f", str(first), "-l", str(last), str(pdf), str(workdir / "page")]
    subprocess.run(
        args,
        check=True,
        capture_output=True,
        timeout=300,
    )
    result = []
    for image_path in sorted(workdir.glob("page*.png")):
        result.append(("image/png", image_path.read_bytes()))
    return result


def _render_doc(source: Path, workdir: Path, page_range: tuple[int, int] | None = None) -> list[tuple[str, bytes]]:
    if source.suffix.lower() == ".pptx":
        source = _run_soffice(source, workdir)
    return _render_pdf(source, workdir, page_range)


def _render_photos(sources: list[Path]) -> list[tuple[str, bytes]]:
    result = []
    for source in sources:
        with Image.open(source) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img.thumbnail((1600, 1600))
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            result.append(("image/jpeg", buffer.getvalue()))
    return result


def render_pages(kind: str, sources: list[Path], workdir: Path, page_range: tuple[int, int] | None = None) -> list[tuple[str, bytes]]:
    if kind == "photos":
        if page_range is not None:
            raise ValueError("page_range applies to doc kind only")
        return _render_photos(sources)
    if kind == "doc":
        if len(sources) != 1:
            raise ValueError("doc kind requires exactly one source")
        return _render_doc(sources[0], workdir, page_range)
    raise ValueError(f"unknown kind: {kind}")


def _chat_fallback(settings: Settings, messages: list[dict], model: str, reasoning_effort: str, timeout_s: float) -> str:
    try:
        return chat(
            messages,
            model,
            api_key=settings.gemini_api_key,
            reasoning_effort=reasoning_effort,
            timeout_s=timeout_s,
        )
    except GeminiCapError:
        log.warning("Gemini cap exhausted; trying OpenRouter fallback")
        return chat(
            messages,
            f"google/{model}",
            api_key=settings.openrouter_api_key,
            reasoning_effort=reasoning_effort,
            timeout_s=timeout_s,
            url=OPENROUTER_CHAT_URL,
        )


def read_pages(settings: Settings, prompt: str, pages: list[tuple[str, bytes]], *, model: str, effort: str) -> str:
    content: list[dict] = [{"type": "text", "text": prompt}]
    for mime, data in pages:
        b64 = base64.b64encode(data).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    messages = [{"role": "user", "content": content}]
    return _chat_fallback(settings, messages, model, effort, 120.0)


def _escape_yaml(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


class PageHeadingError(GeminiError):
    """Page heading count did not match the batch's page count."""


_PAGE_HEADING_RE = re.compile(
    r"^#{2,4}[ \t]*page[ \t]*(\d+)(.*)$", re.MULTILINE | re.IGNORECASE
)


def _renumber_pages(reply: str, first: int, last: int) -> str:
    expected = last - first + 1
    found = len(_PAGE_HEADING_RE.findall(reply))
    if found != expected:
        raise PageHeadingError(
            f"page headings: expected {expected} for pages {first}-{last}, got {found}"
        )
    counter = itertools.count(first)

    def _replace(match: re.Match[str]) -> str:
        trailing = match.group(2).strip().lstrip(":-.\u2013\u2014 \t")
        heading = f"### Page {next(counter)}"
        return f"{heading}\n{trailing}" if trailing else heading

    return _PAGE_HEADING_RE.sub(_replace, reply)


def _read_pages_with_fallback(
    settings: Settings,
    key: str,
    course: str,
    model: str,
    effort: str,
    prompt_template: str,
    first: int,
    last: int,
    batch: list[tuple[str, bytes]],
) -> str:
    prompt = prompt_template.format(course=course, first=first, last=last)
    try:
        reply = read_pages(settings, prompt, batch, model=model, effort=effort).strip()
    except GeminiRecitationError:
        if prompt_template is TEXTBOOK_READ_PROMPT:
            raise
        log.warning(
            "Recitation refusal for %s pages %d-%d; retrying with study-notes prompt",
            key, first, last,
        )
        reply = read_pages(
            settings,
            TEXTBOOK_READ_PROMPT.format(course=course, first=first, last=last),
            batch,
            model=model,
            effort=effort,
        ).strip()
    if first == last and not _PAGE_HEADING_RE.search(reply):
        reply = f"### Page {first}\n{reply}"
    return _renumber_pages(reply, first, last)


# Bumped whenever reply post-processing (_renumber_pages) changes.
READER_VERSION = 1


def reading_key(render_key: str, *, model: str, effort: str, prompt_template: str) -> str:
    return hashlib.sha256(
        "\n".join(
            [
                str(READER_VERSION),
                str(BATCH_PAGES),
                model,
                effort,
                prompt_template,
                render_key,
            ]
        ).encode("utf-8")
    ).hexdigest()


def write_reading(settings: Settings, key: str, course: str, kind: str, pages: int, sources: list[str], body: str, *, model: str) -> Path:
    reads_dir = settings.state_dir / READS_DIR
    reads_dir.mkdir(parents=True, exist_ok=True)
    target = reads_dir / f"{key}.md"
    tmp = target.with_suffix(".tmp")
    lines = ["---", f"course: {course}", f"kind: {kind}", f"pages: {pages}", f"model: {model}", "sources:"]
    lines.extend(f'  - "{_escape_yaml(src)}"' for src in sources)
    lines.extend(["---", "", body])
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {"batches": {}, "batch_pages": BATCH_PAGES}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("checkpoint not a dict")
        batches = data.get("batches", {})
        if not isinstance(batches, dict):
            raise ValueError("checkpoint wrong shape")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in batches.items()):
            raise ValueError("checkpoint batches wrong shape")
        batch_pages = data.get("batch_pages")
        if batch_pages != BATCH_PAGES:
            log.info("Discarding lecture doc checkpoint %s: batch size changed", path)
            return {"batches": {}, "batch_pages": BATCH_PAGES}
        return {"batches": batches, "batch_pages": batch_pages}
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        log.warning("Ignoring unparseable lecture doc checkpoint %s: %s", path, exc)
        return {"batches": {}, "batch_pages": BATCH_PAGES}


def save_checkpoint(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def read_document(
    settings: Settings,
    *,
    key: str,
    course: str,
    kind: str,
    paths: list[str],
    sources: list[Path],
    model: str,
    effort: str,
    on_batch: Callable[[], None] | None = None,
    pages: list[tuple[str, bytes]] | None = None,
    page_range: tuple[int, int] | None = None,
    prompt_template: str = READ_PROMPT,
) -> Path:
    if pages is not None and page_range is not None:
        expected = page_range[1] - page_range[0] + 1
        if len(pages) != expected:
            raise ValueError(
                f"pages has {len(pages)} entries but page_range {page_range[0]}-{page_range[1]} spans {expected}"
            )
    checkpoint_path = settings.state_dir / READS_DIR / f"{key}.partial.json"
    with tempfile.TemporaryDirectory(prefix="semai-lecture-") as tmpdir:
        workdir = Path(tmpdir)
        if pages is None:
            try:
                pages = render_pages(kind, sources, workdir, page_range=page_range)
            except TooManyPages:
                checkpoint_path.unlink(missing_ok=True)
                raise
        if not pages:
            raise ValueError("no pages")

        checkpoint = load_checkpoint(checkpoint_path)

        chunks: list[str] = []
        offset = page_range[0] - 1 if page_range else 0
        for start in range(0, len(pages), BATCH_PAGES):
            first = offset + start + 1
            first_key = str(first)
            if first_key in checkpoint["batches"]:
                chunks.append(checkpoint["batches"][first_key])
                continue
            batch = pages[start : start + BATCH_PAGES]
            last = offset + start + len(batch)

            try:
                reply = _read_pages_with_fallback(
                    settings,
                    key,
                    course,
                    model,
                    effort,
                    prompt_template,
                    first,
                    last,
                    batch,
                )
            except PageHeadingError as exc:
                log.warning("%s for %s; retrying batch once", exc, key)
                try:
                    reply = _read_pages_with_fallback(
                        settings,
                        key,
                        course,
                        model,
                        effort,
                        prompt_template,
                        first,
                        last,
                        batch,
                    )
                except PageHeadingError as retry_exc:
                    log.warning(
                        "%s for %s; reading pages %d-%d one at a time",
                        retry_exc, key, first, last,
                    )
                    page_replies: list[str] = []
                    for i in range(len(batch)):
                        page_num = first + i
                        page_replies.append(
                            _read_pages_with_fallback(
                                settings,
                                key,
                                course,
                                model,
                                effort,
                                prompt_template,
                                page_num,
                                page_num,
                                batch[i : i + 1],
                            )
                        )
                    reply = "\n\n".join(page_replies)
            checkpoint["batches"][first_key] = reply
            save_checkpoint(checkpoint_path, checkpoint)
            if on_batch is not None:
                on_batch()
            chunks.append(reply)
        body = "\n\n".join(chunks)

        reading_path = write_reading(settings, key, course, kind, len(pages), paths, body, model=model)
        checkpoint_path.unlink(missing_ok=True)
        return reading_path
