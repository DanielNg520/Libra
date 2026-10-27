from __future__ import annotations

import json
import logging
import os
import stat
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from libra.config import Settings
from libra import lecture_fetch as lf

MY_COURSES_HTML = """
<div class="quarter"><h2><span>Fall Qtr 2026</span></h2>
<table class="directory"><tbody><tr>
<td class="title"><a class="PodcastLink" href="https://podcast.ucsd.edu/watch/fa26/ece108_001-001-di">ECE 108 - Digital Circuits - DI [001-001-DI]</a></td>
<td class="links"><a title="Screencast" href="https://podcast.ucsd.edu/watch/fa26/ece108_001-001-di/kaltura"><img alt="Screencast for ECE 108 - Digital Circuits - DI [001-001-DI]"></a></td>
</tr><tr>
<td class="title"><a class="PodcastLink" href="https://podcast.ucsd.edu/watch/fa26/ece108_001-000-le">ECE 108 - Digital Circuits - LE [001-000-LE]</a></td>
<td class="links"><a title="Audio" href="https://podcast.ucsd.edu/watch/fa26/ece108_001-000-le/kaltura"><img alt="Audio"></a></td>
</tr><tr>
<td class="title"><a class="PodcastLink" href="https://podcast.ucsd.edu/watch/fa26/ece158a_001-000-le">ECE 158A - Data Networks I - LE [001-000-LE]</a></td>
</tr><tr>
<td class="title"><a class="PodcastLink" href="https://podcast.ucsd.edu/watch/fa26/ece158a_001-000-le">ECE 158A - Data Networks I - LE [001-000-LE]</a></td>
</tr></tbody></table></div>
<div class="quarter"><h2><span>Spring Qtr 2026</span></h2>
<table class="directory"><tbody><tr>
<td class="title"><a class="PodcastLink" href="https://podcast.ucsd.edu/watch/sp26/ece153_a00">ECE 153 - Probability&amp;Random Process/Eng - LE [A00]</a></td>
</tr></tbody></table></div>
"""

COURSE_URL = "https://podcast.ucsd.edu/watch/fa26/ece158a_001-000-le"

COURSE_HTML = """
<div class="LectureList">
<div class="week"><h3>Week 0</h3>
<div class="lecture"><a class="other-media video match " href="https://podcast.ucsd.edu/watch/fa26/ece158a_001-000-le/1">Thu 9/24
<div class="timepieContainer"><span class="timePie" style="display: none;"></span></div>
</a></div></div>
<div class="week"><h3>Week 1</h3>
<div class="lecture"><a class="other-media video match " href="https://podcast.ucsd.edu/watch/fa26/ece158a_001-000-le/2">Tue 9/29
<div class="timepieContainer"><span class="timePie" style="display: none;"></span></div>
</a></div>
<div class="lecture"><a class="current-media video match " href="https://podcast.ucsd.edu/watch/fa26/ece158a_001-000-le/3">Thu 10/1
<div class="timepieContainer"><span class="timePie" style="display: none;"></span></div>
</a></div></div>
<div class="week"><h3>&nbsp;</h3>
<div class="lecture"><a class="other-media match" href="../../Podcasts/Schedule.aspx?podcastID=24129">Schedule</a></div></div>
</div>
"""

WATCH_HTML = """
<script type="text/javascript">
kalturaPlayer = KalturaPlayer.setup({
    targetId: "kaltura_player",
    provider: {
        partnerId: 2323111,
        uiConfId: 54337512,
        ks: 'SECRETKS123'
    }
});
kalturaPlayer.loadMedia({ entryId: '{entry}' }, { startTime: startTime });
</script>
"""

SRT_TEXT = """
1
00:01:26,800 --> 00:01:34,620
All right, so
welcome to EC 158A.

2
00:01:36,060 --> 00:01:40,520
That's a class of course

3
00:01:40,520 --> 00:01:44,820

"""


def make_settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir()
    return Settings.load(
        {
            "LIBRA_STATE_DIR": str(tmp_path / "state"),
            "LIBRA_VAULT_DIR": str(vault),
            "GEMINI_API_KEY": "gem",
            "OPENROUTER_API_KEY": "or",
        }
    )


def test_parse_my_courses_fa26() -> None:
    expected = [
        lf.Podcast("ECE 108", "Discussion", "https://podcast.ucsd.edu/watch/fa26/ece108_001-001-di"),
        lf.Podcast("ECE 108", "Lecture", "https://podcast.ucsd.edu/watch/fa26/ece108_001-000-le"),
        lf.Podcast("ECE 158A", "Lecture", "https://podcast.ucsd.edu/watch/fa26/ece158a_001-000-le"),
    ]
    assert lf.parse_my_courses(MY_COURSES_HTML, "FA26") == expected
    assert lf.parse_my_courses(MY_COURSES_HTML, "SP26") == [
        lf.Podcast("ECE 153", "Lecture", "https://podcast.ucsd.edu/watch/sp26/ece153_a00")
    ]


def test_count_watch_links() -> None:
    assert lf.count_watch_links(MY_COURSES_HTML) == 7
    assert lf.count_watch_links('<a href="https://podcast.ucsd.edu/Login/">Login</a>') == 0


def test_parse_recordings() -> None:
    recordings = lf.parse_recordings(COURSE_HTML, COURSE_URL, "FA26")
    assert [r.number for r in recordings] == [1, 2, 3]
    assert [r.day for r in recordings] == [date(2026, 9, 24), date(2026, 9, 29), date(2026, 10, 1)]
    html = COURSE_HTML.replace("Thu 10/1", "Thu 2/30")
    assert [r.number for r in lf.parse_recordings(html, COURSE_URL, "FA26")] == [1, 2]


def test_parse_watch_page() -> None:
    assert lf.parse_watch_page(WATCH_HTML.replace("{entry}", "1_aaa")) == ("1_aaa", "SECRETKS123")
    assert lf.parse_watch_page("<html></html>") is None


def test_pick_caption() -> None:
    captions = [
        {"languageCode": "en", "status": 2, "fileExt": "srt", "format": "1", "accuracy": 80, "isDefault": True},
        {"languageCode": "en", "status": 2, "fileExt": "srt", "format": "1", "accuracy": 93, "isDefault": False},
        {"languageCode": "fr", "status": 2, "fileExt": "srt", "format": "1", "accuracy": 99, "isDefault": False},
        {"languageCode": "en", "status": 1, "fileExt": "srt", "format": "1", "accuracy": 99, "isDefault": False},
    ]
    assert lf.pick_caption(captions) == captions[1]
    captions.append({"languageCode": "en", "status": 2, "fileExt": "srt", "format": "1", "accuracy": 93, "isDefault": True})
    assert lf.pick_caption(captions) == captions[4]
    assert lf.pick_caption([]) is None


def test_srt_to_segments() -> None:
    expected = [
        {"start": 86.8, "end": 94.62, "text": "All right, so welcome to EC 158A."},
        {"start": 96.06, "end": 100.52, "text": "That's a class of course"},
    ]
    assert lf.srt_to_segments(SRT_TEXT) == expected
    bom_crlf = "\ufeff" + SRT_TEXT.replace("\n", "\r\n")
    assert lf.srt_to_segments(bom_crlf) == expected


def test_transcript_path(tmp_path: Path) -> None:
    base = tmp_path
    assert str(lf.transcript_path(base, "ECE 108", "Discussion", date(2026, 9, 30))).endswith(
        "ECE 108/Transcripts/2026-09-30-DI.json"
    )
    assert str(lf.transcript_path(base, "ECE 108", "Lecture", date(2026, 9, 30))).endswith(
        "ECE 108/Transcripts/2026-09-30.json"
    )


def test_write_transcript(tmp_path: Path) -> None:
    path = tmp_path / "ECE 158A" / "Transcripts" / "x.json"
    segments = [{"start": 1.0, "end": 2.0, "text": "hi"}]
    lf.write_transcript(path, segments)
    assert path.parent.is_dir()
    assert json.loads(path.read_text()) == segments
    assert not list(path.parent.glob("*.tmp"))


def test_save_state(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = {"a": 1}
    lf.save_state(path, state)
    assert json.loads(path.read_text()) == state
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_save_state_if_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    lf.save_state(path, {"old": 1})
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))

    assert not lf.save_state_if_unchanged(path, {"fetch": 1}, 2_000_000_000)
    assert json.loads(path.read_text()) == {"old": 1}

    assert lf.save_state_if_unchanged(path, {"fetch": 2}, 1_000_000_000)
    assert json.loads(path.read_text()) == {"fetch": 2}

    missing = tmp_path / "gone.json"
    assert not lf.save_state_if_unchanged(missing, {"fetch": 1}, 1)
    assert not missing.exists()


def _mock_transport(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_list_captions() -> None:
    sent_fields: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent_fields.update(urllib.parse.parse_qs(request.content.decode()))
        return httpx.Response(200, json={"objects": [{"id": "c1"}]})

    client = _mock_transport(handler)
    result = lf.list_captions(client, "ks", "1_e1")
    assert result == [{"id": "c1"}]
    assert sent_fields["filter[entryIdEqual]"] == ["1_e1"]

    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"objectType": "KalturaAPIException", "code": "INVALID_KS", "message": "bad SECRETKS123 token"},
        )

    client = _mock_transport(error_handler)
    with pytest.raises(lf.KalturaError) as excinfo:
        lf.list_captions(client, "ks", "1_e1")
    assert "SECRETKS123" not in str(excinfo.value)


def _make_run_fetch_client(
    caption_map: dict[str, list[dict[str, Any]]],
    get_url_status: dict[str, int] | None = None,
    *,
    durations: dict[str, int] | None = None,
    flavor_map: dict[str, list[dict[str, Any]]] | None = None,
    flavor_url_status: dict[str, int] | None = None,
    kaltura_calls: list[tuple[str, str]] | None = None,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            fields = urllib.parse.parse_qs(request.content.decode())
            path = request.url.path
            entry = fields["entryId"][0] if "entryId" in fields else None
            caption_id = fields["id"][0] if "id" in fields else None
            list_entry = fields["filter[entryIdEqual]"][0] if "filter[entryIdEqual]" in fields else None
            value = entry if entry is not None else list_entry if list_entry is not None else caption_id
            if kaltura_calls is not None:
                kaltura_calls.append((path.split("/service/", 1)[-1], value))
            if path.endswith("/media/action/get"):
                return httpx.Response(200, json={"duration": (durations or {}).get(entry, 40)})
            if path.endswith("/caption_captionAsset/action/list"):
                objects = caption_map.get(list_entry, [])
                return httpx.Response(200, json={"objects": objects})
            if path.endswith("/caption_captionAsset/action/getUrl"):
                status = (get_url_status or {}).get(caption_id, 200)
                if status != 200:
                    return httpx.Response(status, text="boom")
                return httpx.Response(200, json=f"https://cdn.example/{caption_id}.srt?ks=SECRETKS123")
            if path.endswith("/flavorAsset/action/list"):
                objects = (flavor_map or {}).get(list_entry, [])
                return httpx.Response(200, json={"objects": objects})
            if path.endswith("/flavorAsset/action/getUrl"):
                status = (flavor_url_status or {}).get(caption_id, 200)
                if status != 200:
                    return httpx.Response(status, text="boom")
                return httpx.Response(200, json=f"https://cdn.example/{caption_id}.m4a?ks=SECRETKS123")
        if request.url.path.endswith(".m4a"):
            return httpx.Response(200, content=b"AUDIO")
        return httpx.Response(200, text=SRT_TEXT)

    return _mock_transport(handler)


AUDIO_FLAVORS = [
    {"id": "1_zpy8r8ic", "fileExt": "mp4", "width": 960, "height": 528, "size": 108375, "status": 2},
    {"id": "1_986zp0gb", "fileExt": "mp4", "width": 0, "height": 0, "size": 80618, "status": 2},
    {"id": "1_small", "fileExt": "mp4", "width": 0, "height": 0, "size": 500, "status": 2},
    {"id": "1_xzpppnk4", "fileExt": "mp4", "width": 0, "height": 0, "size": 0, "status": 4},
]


def _make_get_html(
    caption_map: dict[str, list[dict[str, Any]]],
    tmp_path: Path,
) -> tuple[Any, list[str], Path]:
    requested: list[str] = []
    vault = tmp_path / "vault"
    pages: dict[str, str] = {
        lf.MY_COURSES_URL: MY_COURSES_HTML,
        COURSE_URL: COURSE_HTML,
        f"{COURSE_URL}/1": WATCH_HTML.replace("{entry}", "1_e1"),
        f"{COURSE_URL}/2": WATCH_HTML.replace("{entry}", "1_e2"),
        f"{COURSE_URL}/3": WATCH_HTML.replace("{entry}", "1_e3"),
    }

    def get_html(url: str) -> str:
        requested.append(url)
        return pages[url]

    return get_html, requested, vault


def test_run_fetch_end_to_end(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    eligible = {"languageCode": "en", "status": 2, "fileExt": "srt", "format": "1", "accuracy": 90, "isDefault": True}
    caption_map = {"1_e1": [eligible | {"id": "c1"}], "1_e2": [], "1_e3": [eligible | {"id": "c3"}]}
    get_html, requested, vault = _make_get_html(caption_map, tmp_path)
    client = _make_run_fetch_client(caption_map, flavor_map={"1_e2": AUDIO_FLAVORS})

    pre_created = vault / "ECE 158A" / "Transcripts" / "2026-10-01.json"
    pre_created.parent.mkdir(parents=True)
    pre_created.write_text("[]")

    with caplog.at_level(logging.DEBUG):
        result = lf.run_fetch(vault, {"ECE 158A"}, "FA26", get_html=get_html, client=client, audio_dir=tmp_path / "audio")

    written_path = vault / "ECE 158A" / "Transcripts" / "2026-09-24.json"
    assert result.written == [written_path]
    assert len(json.loads(written_path.read_text())) == 2
    assert result.queued == ["ECE 158A Lecture 2026-09-29"]
    assert result.no_captions == []
    assert result.errors == []
    assert result.expired is False
    assert pre_created.read_text() == "[]"
    assert (tmp_path / "audio" / "1_e2.m4a").read_bytes() == b"AUDIO"
    assert json.loads((tmp_path / "audio" / "1_e2.json").read_text()) == {
        "transcript": str(vault / "ECE 158A" / "Transcripts" / "2026-09-29.json"),
        "label": "ECE 158A Lecture 2026-09-29",
        "entry_id": "1_e2",
    }
    assert not list((tmp_path / "audio").glob("*.part"))
    assert not (vault / "ECE 158A" / "Transcripts" / "2026-09-29.json").exists()
    assert COURSE_URL.replace("ece158a_001-000-le", "ece108") not in "\n".join(requested)
    assert not any("ece108" in url for url in requested)
    assert "SECRETKS123" not in caplog.text


def test_run_fetch_expired(tmp_path: Path) -> None:
    calls = 0

    def get_html(url: str) -> str:
        nonlocal calls
        calls += 1
        return '<a href="https://podcast.ucsd.edu/Login/">Login</a>'

    client = _mock_transport(lambda request: httpx.Response(500, text="bad"))
    result = lf.run_fetch(tmp_path / "vault", {"ECE 158A"}, "FA26", get_html=get_html, client=client, audio_dir=tmp_path / "audio")
    assert result.expired is True
    assert result.written == []
    assert calls == 1


def test_run_fetch_error_no_leak(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    eligible = {"languageCode": "en", "status": 2, "fileExt": "srt", "format": "1", "accuracy": 90, "isDefault": True}
    caption_map = {"1_e1": [eligible | {"id": "c1"}], "1_e2": [], "1_e3": []}
    get_html, _, vault = _make_get_html(caption_map, tmp_path)
    client = _make_run_fetch_client(caption_map, get_url_status={"c1": 500})

    with caplog.at_level(logging.DEBUG):
        result = lf.run_fetch(vault, {"ECE 158A"}, "FA26", get_html=get_html, client=client, audio_dir=tmp_path / "audio")

    assert "ECE 158A Lecture 2026-09-24" in result.errors
    assert not (vault / "ECE 158A" / "Transcripts" / "2026-09-24.json").exists()
    assert "SECRETKS123" not in caplog.text


def test_run_fetch_low_coverage_queues(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    eligible = {"languageCode": "en", "status": 2, "fileExt": "srt", "format": "1", "accuracy": 90, "isDefault": True}
    caption_map = {"1_e1": [eligible | {"id": "c1"}], "1_e2": [], "1_e3": []}
    get_html, _, vault = _make_get_html(caption_map, tmp_path)
    kaltura_calls: list[tuple[str, str]] = []
    client = _make_run_fetch_client(
        caption_map,
        durations={"1_e1": 100},
        flavor_map={"1_e1": AUDIO_FLAVORS},
        kaltura_calls=kaltura_calls,
    )

    with caplog.at_level(logging.DEBUG):
        result = lf.run_fetch(vault, {"ECE 158A"}, "FA26", get_html=get_html, client=client, audio_dir=tmp_path / "audio")

    assert "ECE 158A Lecture 2026-09-24" in result.queued
    assert not (vault / "ECE 158A" / "Transcripts" / "2026-09-24.json").exists()
    assert "captions cover 12% of the recording" in caplog.text
    assert "SECRETKS123" not in caplog.text
    assert "ECE 158A Lecture 2026-09-29" in result.no_captions
    assert "ECE 158A Lecture 2026-10-01" in result.no_captions
    assert ("flavorAsset/action/getUrl", "1_small") in kaltura_calls


def test_run_fetch_skips_queued_entry(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "1_e2.json").write_text("{}")
    caption_map: dict[str, list[dict[str, Any]]] = {"1_e1": [], "1_e2": [], "1_e3": []}
    get_html, _, vault = _make_get_html(caption_map, tmp_path)
    kaltura_calls: list[tuple[str, str]] = []
    client = _make_run_fetch_client(caption_map, flavor_map={"1_e1": AUDIO_FLAVORS, "1_e2": AUDIO_FLAVORS, "1_e3": AUDIO_FLAVORS}, kaltura_calls=kaltura_calls)

    result = lf.run_fetch(vault, {"ECE 158A"}, "FA26", get_html=get_html, client=client, audio_dir=audio_dir)

    assert not any(value == "1_e2" for _, value in kaltura_calls)
    assert "ECE 158A Lecture 2026-09-29" not in result.queued
    assert "ECE 158A Lecture 2026-09-29" not in result.no_captions
    assert "ECE 158A Lecture 2026-09-29" not in result.errors


def test_run_fetch_flavor_url_error(tmp_path: Path) -> None:
    caption_map: dict[str, list[dict[str, Any]]] = {"1_e1": [], "1_e2": [], "1_e3": []}
    get_html, _, vault = _make_get_html(caption_map, tmp_path)
    client = _make_run_fetch_client(caption_map, flavor_map={"1_e1": AUDIO_FLAVORS}, flavor_url_status={"1_small": 500})

    result = lf.run_fetch(vault, {"ECE 158A"}, "FA26", get_html=get_html, client=client, audio_dir=tmp_path / "audio")

    assert "ECE 158A Lecture 2026-09-24" in result.errors
    assert not (tmp_path / "audio" / "1_e1.json").exists()
    assert not (tmp_path / "audio" / "1_e1.m4a").exists()


def test_pick_audio_flavor() -> None:
    assert lf.pick_audio_flavor(AUDIO_FLAVORS)["id"] == "1_small"
    assert lf.pick_audio_flavor([AUDIO_FLAVORS[0], AUDIO_FLAVORS[3]]) is None
    assert lf.pick_audio_flavor([{"id": "x", "size": 10, "status": 2}]) is None
    assert lf.pick_audio_flavor([]) is None


def test_caption_coverage() -> None:
    assert lf.caption_coverage([{"start": 0, "end": 10, "text": "a"}, {"start": 20, "end": 25, "text": "b"}], 60) == pytest.approx(0.25)
    assert lf.caption_coverage([{"start": 25, "end": 20, "text": "b"}], 60) == 0.0


def test_media_duration_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        fields = dict(urllib.parse.parse_qsl(request.content.decode()))
        assert fields["entryId"] == "1_e1"
        return httpx.Response(200, json={"duration": 5100})

    client = _mock_transport(handler)
    assert lf.media_duration(client, "ks", "1_e1") == 5100.0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"duration": 0},
        {"duration": True},
        {"duration": "x"},
        {"objectType": "KalturaAPIException", "code": "INVALID_KS", "message": "bad SECRETKS123 token"},
    ],
)
def test_media_duration_raises(body: dict[str, Any]) -> None:
    client = _mock_transport(lambda request: httpx.Response(200, json=body))
    with pytest.raises(lf.KalturaError) as excinfo:
        lf.media_duration(client, "ks", "1_e1")
    assert "SECRETKS123" not in str(excinfo.value)


@pytest.mark.parametrize(
    "body",
    [
        [],
        "x",
        {"objects": None},
        {"objects": {}},
        {"objectType": "KalturaAPIException", "code": "INVALID_KS", "message": "bad SECRETKS123 token"},
    ],
)
def test_list_flavors_rejects_bad_body(body: Any) -> None:
    client = _mock_transport(lambda request: httpx.Response(200, json=body))

    with pytest.raises(lf.KalturaError) as excinfo:
        lf.list_flavors(client, "ks", "1_e1")

    assert "SECRETKS123" not in str(excinfo.value)


def test_download_file_failure_cleans_up(tmp_path: Path) -> None:
    dest = tmp_path / "a" / "x.m4a"
    client = _mock_transport(lambda request: httpx.Response(500, text="bad"))
    with pytest.raises(httpx.HTTPStatusError):
        lf.download_file(client, "https://cdn.example/x.m4a", dest)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()


def test_fetch_transcripts_state_missing(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    result = lf.fetch_transcripts(settings, {"ECE 158A"}, "FA26")
    assert result.expired is True


def test_fetch_transcripts_vault_none(tmp_path: Path) -> None:
    settings = Settings.load({"LIBRA_STATE_DIR": str(tmp_path / "state")})
    with pytest.raises(ValueError):
        lf.fetch_transcripts(settings, {"ECE 158A"}, "FA26")
