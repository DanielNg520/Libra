"""UCSD podcast sign-in over an ssh-tunnelled DevTools session (ported from SemAI `omll podcast-login`)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from libra.lecture_fetch import BASE_URL, count_watch_links, save_state

DEVTOOLS_PORT = 9222
PODCAST_LOGIN_POLL_SECONDS = 15
PODCAST_LOGIN_URL = BASE_URL + "/Login/?dest=%2fMyCourses.aspx"


def cmd_podcast_login(
    state: Path,
    timeout: float,
    *,
    playwright_factory: Callable[[], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    factory = playwright_factory or sync_playwright
    state_path_arg = state
    with factory() as p:
        browser = p.chromium.launch(
            headless=True,
            channel="chromium",
            args=[
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={DEVTOOLS_PORT}",
            ],
        )
        try:
            if state_path_arg.is_file():
                try:
                    context = browser.new_context(storage_state=str(state_path_arg))
                except (PlaywrightError, ValueError):
                    print("Saved login state unreadable; starting fresh.")
                    context = browser.new_context()
            else:
                context = browser.new_context()
            page = context.new_page()
            for attempt in range(2):
                try:
                    page.goto(
                        PODCAST_LOGIN_URL,
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                    break
                except PlaywrightError as exc:
                    if attempt == 1:
                        print(
                            f"Could not open the UCSD sign-in page ({type(exc).__name__}); open it from DevTools."
                        )

            print(
                f"1. On the Mac: ssh -L {DEVTOOLS_PORT}:127.0.0.1:{DEVTOOLS_PORT} dyne@fedora"
            )
            print("2. On the Mac, open chrome://inspect and add localhost:9222 under Configure.")
            print(
                "3. Inspect the podcast.ucsd.edu tab, sign in with SSO and Duo, "
                "and finish on My Courses."
            )
            print(f"Waiting up to {timeout:.0f} s for sign-in...")

            deadline = monotonic() + timeout
            found = False
            while not found:
                for active_page in context.pages:
                    for frame in active_page.frames:
                        try:
                            if count_watch_links(frame.content()) > 0:
                                found = True
                                break
                        except PlaywrightError:
                            continue
                    if found:
                        break
                if found:
                    break
                if monotonic() >= deadline:
                    print("Timed out waiting for sign-in; nothing was saved.")
                    return 1
                sleep(PODCAST_LOGIN_POLL_SECONDS)

            saved_state = context.storage_state()
            save_state(state_path_arg, saved_state)
            cookie_count = len(saved_state["cookies"])
            print(f"Saved login state to {state_path_arg} ({cookie_count} cookies)")
            return 0
        finally:
            browser.close()
