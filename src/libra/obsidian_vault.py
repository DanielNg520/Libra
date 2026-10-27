"""Commit helpers for the academic vault's local git repo (undo history, never pushed)."""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _git(repo_dir: Path, args: list[str], *, timeout_s: float, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
    )


def commit_paths(repo_dir: Path, paths: list[Path], message: str, *, timeout_s: float = 10.0) -> bool:
    """Commit only the given paths in the git work tree containing repo_dir.

    Returns True only if a commit was made. Returns False without raising when
    repo_dir is not inside a git work tree, paths is empty, or any git step
    fails (nonzero exit, timeout, or git missing).
    """
    if not paths:
        return False

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        check = _git(repo_dir, ["rev-parse", "--is-inside-work-tree"], timeout_s=timeout_s, env=env)
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        logger.debug("not a git work tree: %s", exc)
        return False

    if check.returncode != 0:
        logger.debug("not a git work tree: %s", check.stderr.strip())
        return False

    path_strings = [str(path) for path in paths]

    try:
        staged = _git(repo_dir, ["add", "--", *path_strings], timeout_s=timeout_s, env=env)
        if staged.returncode != 0:
            logger.warning("git add failed: %s", staged.stderr.strip())
            return False

        committed = _git(repo_dir, ["commit", "-m", message, "--", *path_strings], timeout_s=timeout_s, env=env)
        if committed.returncode != 0:
            logger.warning("git commit failed: %s", committed.stderr.strip())
            return False
    except subprocess.TimeoutExpired as exc:
        logger.warning("git command timed out: %s", exc)
        return False
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        logger.warning("git command failed: %s", exc)
        return False

    return True


def has_uncommitted_changes(repo_dir: Path, paths: list[Path], *, timeout_s: float = 10.0) -> bool:
    """Return True if any of the given paths hold changes git has not committed.

    Returns False for an empty paths list or when repo_dir is not inside a git
    work tree. Fails safe by returning True when the status check cannot be
    completed (nonzero exit, timeout, or git missing).
    """
    if not paths:
        return False

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        check = _git(repo_dir, ["rev-parse", "--is-inside-work-tree"], timeout_s=timeout_s, env=env)
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        logger.debug("not a git work tree: %s", exc)
        return False

    if check.returncode != 0:
        logger.debug("not a git work tree: %s", check.stderr.strip())
        return False

    path_strings = [str(path) for path in paths]

    try:
        status = _git(repo_dir, ["status", "--porcelain", "--untracked-files=all", "--", *path_strings], timeout_s=timeout_s, env=env)
        if status.returncode != 0:
            logger.warning("git status failed: %s", status.stderr.strip())
            return True
    except subprocess.TimeoutExpired as exc:
        logger.warning("git command timed out: %s", exc)
        return True
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        logger.warning("git command failed: %s", exc)
        return True

    return bool(status.stdout.strip())
