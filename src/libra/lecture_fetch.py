"""Fetch UCSD podcast lecture captions and write them as transcript JSON into the vault."""
import contextlib
import html.parser
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urljoin

import httpx

from libra.config import Settings
from libra.courses import canonical_course_code
from libra.sources import TRANSCRIPTS_DIR

log = logging.getLogger(__name__)

BASE_URL = "https://podcast.ucsd.edu"
MY_COURSES_URL = BASE_URL + "/MyCourses.aspx"
KALTURA_API = "https://cdnapisec.kaltura.com/api_v3/service/"
STATE_FILE = "ucsd-podcast-state.json"
KINDS = {"LE": "Lecture", "DI": "Discussion"}
AUDIO_DIR = "lecture_audio"
MIN_COVERAGE = 0.25


@dataclass(frozen=True, slots=True)
class Podcast:
    code: str
    kind: str
    url: str


@dataclass(frozen=True, slots=True)
class Recording:
    number: int
    day: date
    url: str


@dataclass(slots=True)
class FetchResult:
    expired: bool = False
    written: list[Path] = field(default_factory=list)
    queued: list[str] = field(default_factory=list)
    no_captions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class KalturaError(RuntimeError):
    pass


class PageError(RuntimeError):
    """A podcast page failed to load."""


_FETCH_ERRORS = (httpx.HTTPError, KalturaError, PageError, ValueError, OSError)


class _LinkCollector(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str, str]] = []
        self._current: tuple[str, str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attr_map = dict(attrs)
            href = attr_map.get("href") or ""
            cls = attr_map.get("class") or ""
            self._current = (href, cls, [])

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current[2].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current is not None:
            href, cls, parts = self._current
            text = " ".join(" ".join(parts).split())
            self.links.append((href, cls, text))
            self._current = None


def _collect_links(html_text: str) -> list[tuple[str, str, str]]:
    parser = _LinkCollector()
    parser.feed(html_text)
    return parser.links


_PODCAST_RE = re.compile(r"^(?P<code>.+?) - .+ - (?P<kind>LE|DI) \[[^\]]+\]$")


def parse_my_courses(html: str, term: str) -> list[Podcast]:
    pattern = re.compile(rf"^https://podcast\.ucsd\.edu/watch/{re.escape(term.lower())}/[a-z0-9_-]+$")
    podcasts: list[Podcast] = []
    seen: set[str] = set()
    for href, _cls, text in _collect_links(html):
        resolved = urljoin(BASE_URL + "/", href)
        match = _PODCAST_RE.match(text)
        if not match or not pattern.match(resolved):
            continue
        if resolved in seen:
            continue
        code = canonical_course_code(match.group("code"))
        kind = KINDS[match.group("kind")]
        podcasts.append(Podcast(code=code, kind=kind, url=resolved))
        seen.add(resolved)
    return podcasts


def count_watch_links(html: str) -> int:
    return sum(1 for href, _cls, _text in _collect_links(html) if "/watch/" in href)


_RECORDING_RE = re.compile(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{1,2})/(\d{1,2})\b")


def parse_recordings(html: str, podcast_url: str, term: str) -> list[Recording]:
    year = 2000 + int(term[-2:])
    pattern = re.compile(re.escape(podcast_url) + r"/(\d+)")
    recordings: dict[int, Recording] = {}
    for href, cls, text in _collect_links(html):
        tokens = set(cls.split())
        if not ({"other-media", "current-media"} & tokens):
            continue
        resolved = urljoin(podcast_url + "/", href)
        match = pattern.fullmatch(resolved)
        if not match:
            continue
        date_match = _RECORDING_RE.match(text)
        if not date_match:
            continue
        month, day = int(date_match.group(1)), int(date_match.group(2))
        try:
            rec_day = date(year, month, day)
        except ValueError:
            continue
        number = int(match.group(1))
        recordings[number] = Recording(number=number, day=rec_day, url=resolved)
    return [recordings[n] for n in sorted(recordings)]


_ENTRY_ID_RE = re.compile(r"loadMedia\(\{\s*entryId:\s*'([^']+)'")
_KS_RE = re.compile(r"\bks:\s*'([^']+)'")


def parse_watch_page(html: str) -> tuple[str, str] | None:
    entry_match = _ENTRY_ID_RE.search(html)
    ks_match = _KS_RE.search(html)
    if not entry_match or not ks_match:
        return None
    return entry_match.group(1), ks_match.group(1)


def pick_caption(captions: list[dict]) -> dict | None:
    eligible: list[dict] = []
    for caption in captions:
        language_code = caption.get("languageCode")
        language_ok = (
            str(language_code).lower() == "en"
            if language_code is not None
            else caption.get("language") == "English"
        )
        if not language_ok or caption.get("status") != 2:
            continue
        if caption.get("fileExt") != "srt" and caption.get("format") != "1":
            continue
        eligible.append(caption)
    if not eligible:
        return None
    return max(eligible, key=lambda c: (c.get("accuracy") or 0, bool(c.get("isDefault"))))


_SRT_TIME_RE = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})"
)


def srt_to_segments(text: str) -> list[dict]:
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    segments: list[dict] = []
    for block in text.split("\n\n"):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        time_entry = next(
            (
                (i, match)
                for i, line in enumerate(lines)
                if (match := _SRT_TIME_RE.search(line)) is not None
            ),
            None,
        )
        if time_entry is None:
            continue
        time_index, time_match = time_entry
        content = " ".join(line.strip() for line in lines[time_index + 1 :]).strip()
        if not content:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, time_match.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": content})
    return segments


def transcript_path(vault: Path, code: str, kind: str, day: date) -> Path:
    suffix = "-DI" if kind == "Discussion" else ""
    return vault / code / TRANSCRIPTS_DIR / f"{day.isoformat()}{suffix}.json"


def _write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix=".tmp") as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def write_transcript(path: Path, segments: list[dict]) -> None:
    _write_json_atomic(path, segments)


def audio_paths(audio_dir: Path, entry_id: str) -> tuple[Path, Path]:
    return audio_dir / f"{entry_id}.m4a", audio_dir / f"{entry_id}.json"


def caption_coverage(segments: list[dict], duration: float) -> float:
    covered = sum(max(0.0, seg["end"] - seg["start"]) for seg in segments)
    return covered / duration


def state_path(settings: Settings) -> Path:
    return settings.state_dir / STATE_FILE


def save_state(path: Path, state: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def save_state_if_unchanged(path: Path, state: dict, mtime_ns: int) -> bool:
    try:
        if path.stat().st_mtime_ns != mtime_ns:
            log.info("Login state changed during fetch; kept the newer state")
            return False
    except FileNotFoundError:
        log.info("Login state changed during fetch; kept the newer state")
        return False
    save_state(path, state)
    return True


def list_captions(client: httpx.Client, ks: str, entry_id: str) -> list[dict]:
    response = client.post(
        KALTURA_API + "caption_captionAsset/action/list",
        data={"ks": ks, "format": 1, "filter[entryIdEqual]": entry_id},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("objects"), list):
        code = body.get("code") if isinstance(body, dict) else None
        raise KalturaError(str(code))
    return body["objects"]


def caption_url(client: httpx.Client, ks: str, caption_id: str) -> str:
    response = client.post(
        KALTURA_API + "caption_captionAsset/action/getUrl",
        data={"ks": ks, "format": 1, "id": caption_id},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, str):
        code = body.get("code") if isinstance(body, dict) else None
        raise KalturaError(str(code))
    return body


def media_duration(client: httpx.Client, ks: str, entry_id: str) -> float:
    response = client.post(
        KALTURA_API + "media/action/get",
        data={"ks": ks, "format": 1, "entryId": entry_id},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(body, dict) or "duration" not in body:
        raise KalturaError(str(code))
    duration = body["duration"]
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
        raise KalturaError(str(code))
    return float(duration)


def list_flavors(client: httpx.Client, ks: str, entry_id: str) -> list[dict]:
    response = client.post(
        KALTURA_API + "flavorAsset/action/list",
        data={"ks": ks, "format": 1, "filter[entryIdEqual]": entry_id},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(body, dict) or not isinstance(body.get("objects"), list):
        raise KalturaError(str(code))
    return body["objects"]


def flavor_url(client: httpx.Client, ks: str, flavor_id: str) -> str:
    response = client.post(
        KALTURA_API + "flavorAsset/action/getUrl",
        data={"ks": ks, "format": 1, "id": flavor_id},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(body, str):
        raise KalturaError(str(code))
    return body


def pick_audio_flavor(flavors: list[dict]) -> dict | None:
    candidates = []
    for flavor in flavors:
        if flavor.get("status") != 2:
            continue
        width = flavor.get("width")
        height = flavor.get("height")
        size = flavor.get("size") or 0
        if width != 0 or height != 0 or size <= 0:
            continue
        candidates.append(flavor)
    if not candidates:
        return None
    return min(candidates, key=lambda f: f.get("size") or 0)


@contextlib.contextmanager
def _httpx_logs_muted() -> Iterator[None]:
    logger = logging.getLogger("httpx")

    def _drop(record: logging.LogRecord) -> bool:
        return False

    logger.addFilter(_drop)
    try:
        yield
    finally:
        logger.removeFilter(_drop)


def download_text(client: httpx.Client, url: str) -> str:
    with _httpx_logs_muted():
        response = client.get(url, follow_redirects=True, timeout=60)
    response.raise_for_status()
    return response.content.decode("utf-8-sig")


def download_file(client: httpx.Client, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest.with_name(dest.name + ".part")
    try:
        with _httpx_logs_muted():
            with client.stream("GET", url, follow_redirects=True, timeout=60) as response:
                response.raise_for_status()
                with part_path.open("wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
        os.replace(part_path, dest)
    except Exception:
        part_path.unlink(missing_ok=True)
        raise


def queue_audio(
    client: httpx.Client,
    ks: str,
    entry_id: str,
    transcript: Path,
    label: str,
    audio_dir: Path,
) -> bool:
    flavors = list_flavors(client, ks, entry_id)
    flavor = pick_audio_flavor(flavors)
    if flavor is None:
        return False
    audio, sidecar = audio_paths(audio_dir, entry_id)
    download_file(client, flavor_url(client, ks, str(flavor["id"])), audio)
    _write_json_atomic(
        sidecar,
        {"transcript": str(transcript), "label": label, "entry_id": entry_id},
    )
    return True


def _describe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__} {exc.response.status_code}"
    return type(exc).__name__


def _fetch_recording(
    client: httpx.Client,
    ks: str,
    entry_id: str,
    label: str,
    path: Path,
    audio_dir: Path,
    result: FetchResult,
) -> None:
    captions = list_captions(client, ks, entry_id)
    caption = pick_caption(captions)
    segments: list[dict] = []
    if caption is not None:
        srt_url = caption_url(client, ks, str(caption["id"]))
        srt_text = download_text(client, srt_url)
        segments = srt_to_segments(srt_text)
    if segments:
        coverage = caption_coverage(segments, media_duration(client, ks, entry_id))
        if coverage >= MIN_COVERAGE:
            write_transcript(path, segments)
            result.written.append(path)
            return
        log.warning("%s: captions cover %.0f%% of the recording", label, coverage * 100)
    elif caption is not None:
        log.warning("%s: empty transcript", label)
    else:
        log.warning("%s: no eligible captions", label)
    if queue_audio(client, ks, entry_id, path, label, audio_dir):
        result.queued.append(label)
        log.info("%s: queued audio for Whisper", label)
    else:
        log.warning("%s: no audio flavor", label)
        result.no_captions.append(label)


def run_fetch(
    vault: Path,
    wanted: set[str],
    term: str,
    *,
    get_html: Callable[[str], str],
    client: httpx.Client,
    audio_dir: Path,
) -> FetchResult:
    html = get_html(MY_COURSES_URL)
    if count_watch_links(html) == 0:
        log.warning("Saved login appears expired; no watch links on MyCourses page")
        return FetchResult(expired=True)

    result = FetchResult()
    for podcast in parse_my_courses(html, term):
        if podcast.code not in wanted:
            continue
        podcast_label = f"{podcast.code} {podcast.kind}"
        try:
            page = get_html(podcast.url)
        except _FETCH_ERRORS as exc:
            log.warning("%s: %s", podcast_label, _describe_error(exc))
            result.errors.append(podcast_label)
            continue

        for recording in parse_recordings(page, podcast.url, term):
            label = f"{podcast.code} {podcast.kind} {recording.day.isoformat()}"
            path = transcript_path(vault, podcast.code, podcast.kind, recording.day)
            if path.exists():
                continue
            try:
                parsed = parse_watch_page(get_html(recording.url))
                if parsed is None:
                    log.warning("%s: missing player data", label)
                    result.errors.append(label)
                    continue
                entry_id, ks = parsed
                if audio_paths(audio_dir, entry_id)[1].exists():
                    continue
                _fetch_recording(client, ks, entry_id, label, path, audio_dir, result)
            except _FETCH_ERRORS as exc:
                log.warning("%s: %s", label, _describe_error(exc))
                result.errors.append(label)

    log.info(
        "Transcript fetch complete: %d written, %d queued, %d no captions, %d errors",
        len(result.written),
        len(result.queued),
        len(result.no_captions),
        len(result.errors),
    )
    return result


def fetch_transcripts(
    settings: Settings,
    wanted: set[str],
    term: str,
    *,
    client: httpx.Client | None = None,
) -> FetchResult:
    if settings.obsidian_academic_vault_dir is None:
        raise ValueError("Obsidian academic vault is not configured")
    state_file = state_path(settings)
    if not state_file.exists():
        log.warning("No saved login state at %s; cannot fetch transcripts", state_file)
        return FetchResult(expired=True)

    state_mtime_ns = state_file.stat().st_mtime_ns

    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    own_client = client is None
    httpx_client = client or httpx.Client()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(storage_state=str(state_file))
                page = context.new_page()

                def get_html(url: str) -> str:
                    wait_until = "networkidle" if url == MY_COURSES_URL else "domcontentloaded"
                    try:
                        page.goto(url, wait_until=wait_until, timeout=60_000)
                        return page.content()
                    except PlaywrightError as exc:
                        raise PageError(type(exc).__name__) from exc

                result = run_fetch(
                    settings.obsidian_academic_vault_dir,
                    wanted,
                    term,
                    get_html=get_html,
                    client=httpx_client,
                    audio_dir=settings.state_dir / AUDIO_DIR,
                )
                if not result.expired:
                    save_state_if_unchanged(state_file, context.storage_state(), state_mtime_ns)
                return result
            finally:
                browser.close()
    finally:
        if own_client:
            httpx_client.close()
