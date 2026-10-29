from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError

import libra.login as cli

SIGNED_IN_HTML = '<a href="/watch/fa26/ece158a_a00/1">Lecture 1</a>'
SIGNED_OUT_HTML = '<a href="/Login/">Login</a>'

STATE = {
    "cookies": [
        {"name": "sid", "value": "SECRET-COOKIE-VALUE", "expires": -1},
        {"name": "duo", "value": "SECRET-DUO", "expires": 123},
    ],
    "origins": [],
}


class FakePage:
    def __init__(
        self,
        contents: list,
        goto_error: Exception | None = None,
        goto_failures: int | None = None,
        child_frames: list["FakePage"] | None = None,
    ) -> None:
        self._contents = contents
        self.goto_error = goto_error
        self.goto_failures = goto_failures
        self.goto_calls: int = 0
        self.goto_url: str | None = None
        self.goto_kwargs: dict[str, Any] | None = None
        self._child_frames = child_frames or []

    @property
    def frames(self) -> list["FakePage"]:
        return [self, *self._child_frames]

    def content(self) -> str:
        item = self._contents.pop(0)
        if isinstance(item, Exception):
            raise item
        if len(self._contents) == 0:
            self._contents.append(item)
        return item

    def goto(self, url: str, **kwargs: Any) -> None:
        self.goto_calls += 1
        self.goto_url = url
        self.goto_kwargs = kwargs
        if self.goto_error is not None and (
            self.goto_failures is None or self.goto_calls <= self.goto_failures
        ):
            raise self.goto_error


class FakeContext:
    def __init__(self, pages: list[FakePage], state: dict[str, Any]) -> None:
        self.pages = pages
        self._state = state

    def new_page(self) -> FakePage:
        return self.pages[0]

    def storage_state(self) -> dict[str, Any]:
        return self._state


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self._context = context
        self.closed = False
        self.context_calls: list[dict[str, Any]] = []
        self.seed_error: Exception | None = None

    def new_context(self, **kwargs: Any) -> FakeContext:
        self.context_calls.append(dict(kwargs))
        if self.seed_error is not None and "storage_state" in kwargs:
            raise self.seed_error
        return self._context

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self._browser = browser
        self.launch_kwargs: dict[str, Any] | None = None

    def launch(self, **kwargs: Any) -> FakeBrowser:
        self.launch_kwargs = kwargs
        return self._browser


class FakePlaywright:
    def __init__(self, browser: FakeBrowser) -> None:
        self.chromium = FakeChromium(browser)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleep_calls: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds


def _make_playwright_factory(
    pages: list[FakePage],
    state: dict[str, Any] = STATE,
    goto_error: Exception | None = None,
) -> tuple[Any, FakeBrowser, FakeChromium]:
    first_page = pages[0]
    if goto_error is not None:
        first_page.goto_error = goto_error
    context = FakeContext(pages, state)
    browser = FakeBrowser(context)
    playwright = FakePlaywright(browser)

    import contextlib

    @contextlib.contextmanager
    def factory() -> Any:
        yield playwright

    return factory, browser, playwright.chromium


def _run_login(
    tmp_path: Path,
    pages: list[FakePage],
    *,
    timeout: float = 900.0,
    state: dict[str, Any] | None = None,
    goto_error: Exception | None = None,
) -> tuple[int, FakeBrowser, FakeChromium, FakeClock, Path]:
    factory, browser, chromium = _make_playwright_factory(
        pages, state or STATE, goto_error
    )
    clock = FakeClock()
    state_file = tmp_path / "state.json"
    result = cli.cmd_podcast_login(
        state_file,
        timeout,
        playwright_factory=factory,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    return result, browser, chromium, clock, state_file


def test_signs_in_on_second_poll(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pages = [FakePage([SIGNED_OUT_HTML, SIGNED_IN_HTML])]
    result, browser, _, clock, state_file = _run_login(tmp_path, pages)

    captured = capsys.readouterr()

    assert result == 0
    assert state_file.exists()
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
    assert json.loads(state_file.read_text()) == STATE
    assert clock.sleep_calls == [15]
    assert "ssh -L 9222:127.0.0.1:9222 dyne@fedora" in captured.out
    assert "chrome://inspect" in captured.out
    assert "(2 cookies)" in captured.out
    assert "SECRET-COOKIE-VALUE" not in captured.out
    assert "SECRET-DUO" not in captured.out
    assert browser.closed
    assert browser.context_calls == [{}]


def test_launch_arguments_and_goto_url(tmp_path: Path) -> None:
    pages = [FakePage([SIGNED_IN_HTML])]
    result, _, chromium, _, _ = _run_login(tmp_path, pages)

    assert result == 0
    assert chromium.launch_kwargs is not None
    assert chromium.launch_kwargs["headless"] is True
    assert chromium.launch_kwargs["channel"] == "chromium"
    args = chromium.launch_kwargs["args"]
    assert "--remote-debugging-address=127.0.0.1" in args
    assert "--remote-debugging-port=9222" in args
    assert pages[0].goto_url == "https://podcast.ucsd.edu/Login/?dest=%2fMyCourses.aspx"


def test_timeout_returns_1_and_no_state_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = [FakePage([SIGNED_OUT_HTML])]
    result, browser, _, clock, state_file = _run_login(tmp_path, pages, timeout=30)

    captured = capsys.readouterr()

    assert result == 1
    assert not state_file.exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert "Timed out" in captured.out
    assert browser.closed
    assert clock.sleep_calls == [15, 15]


def test_playwright_error_from_content_counts_as_not_signed_in(
    tmp_path: Path,
) -> None:
    pages = [FakePage([PlaywrightError("navigating"), SIGNED_IN_HTML])]
    result, _, _, clock, state_file = _run_login(tmp_path, pages)

    assert result == 0
    assert state_file.exists()
    assert clock.sleep_calls == [15]


def test_any_open_page_counts(tmp_path: Path) -> None:
    pages = [FakePage([SIGNED_OUT_HTML]), FakePage([SIGNED_IN_HTML])]
    result, _, _, clock, state_file = _run_login(tmp_path, pages)

    assert result == 0
    assert state_file.exists()
    assert clock.sleep_calls == []


def test_child_frame_signed_in(tmp_path: Path) -> None:
    child = FakePage([SIGNED_IN_HTML])
    page = FakePage([SIGNED_OUT_HTML], child_frames=[child])
    result, _, _, clock, state_file = _run_login(tmp_path, [page])

    assert result == 0
    assert state_file.exists()
    assert clock.sleep_calls == []


def test_child_frame_error_then_signed_in(tmp_path: Path) -> None:
    detached_child = FakePage([PlaywrightError("detached")])
    signed_in_child = FakePage([SIGNED_IN_HTML])
    page = FakePage(
        [SIGNED_OUT_HTML],
        child_frames=[detached_child, signed_in_child],
    )
    result, _, _, clock, state_file = _run_login(tmp_path, [page])

    assert result == 0
    assert state_file.exists()


def test_goto_failure_prints_and_still_polls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = [FakePage([SIGNED_IN_HTML])]
    result, _, _, _, state_file = _run_login(
        tmp_path, pages, goto_error=PlaywrightError("net")
    )

    captured = capsys.readouterr()

    assert result == 0
    assert pages[0].goto_calls == 2
    assert "Could not open the UCSD sign-in page (Error)" in captured.out
    assert state_file.exists()


def test_goto_retries_once_after_timeout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = FakePage(
        [SIGNED_IN_HTML],
        goto_error=PlaywrightError("Timeout 60000ms exceeded"),
        goto_failures=1,
    )
    result, _, _, _, state_file = _run_login(tmp_path, [page])

    captured = capsys.readouterr()

    assert result == 0
    assert page.goto_calls == 2
    assert "Could not open the UCSD sign-in page" not in captured.out
    assert state_file.exists()


def test_browser_closes_when_polling_raises(tmp_path: Path) -> None:
    pages = [FakePage([RuntimeError("boom")])]
    factory, browser, _ = _make_playwright_factory(pages)
    clock = FakeClock()

    with pytest.raises(RuntimeError, match="boom"):
        cli.cmd_podcast_login(
            tmp_path / "state.json", 900.0,
            playwright_factory=factory,
            sleep=clock.sleep, monotonic=clock.monotonic,
        )

    assert browser.closed
    assert not (tmp_path / "state.json").exists()


def test_seeds_context_from_existing_state(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(STATE))
    result, browser, _chromium, _clock, _state_file = _run_login(tmp_path, [FakePage([SIGNED_IN_HTML])])
    assert result == 0
    assert browser.context_calls == [{"storage_state": str(state_file)}]


def test_unreadable_state_starts_fresh(tmp_path, capsys):
    state_file = tmp_path / "state.json"
    state_file.write_text("not json")
    factory, browser, _chromium = _make_playwright_factory([FakePage([SIGNED_IN_HTML])])
    browser.seed_error = PlaywrightError("bad state")
    clock = FakeClock()
    result = cli.cmd_podcast_login(
        state_file,
        900.0,
        playwright_factory=factory,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert result == 0
    assert browser.context_calls == [{"storage_state": str(state_file)}, {}]
    assert "Saved login state unreadable; starting fresh." in capsys.readouterr().out


def test_login_url_constant():
    assert cli.PODCAST_LOGIN_URL == "https://podcast.ucsd.edu/Login/?dest=%2fMyCourses.aspx"
