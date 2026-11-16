"""Claude CLI runner for Anki card answers (Libra ADR-0002)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

Runner = Callable[[str], str]


class LessonError(RuntimeError):
    """Generation cannot proceed."""


def claude_runner(
    vault: Path,
    read_dirs: Sequence[Path],
    *,
    timeout: float = 900.0,
    executable: str = "claude",
) -> Runner:
    argv: list[str] = [
        executable,
        "-p",
        "--output-format",
        "text",
        "--no-session-persistence",
        "--allowedTools",
        "Read",
        "Grep",
        "Glob",
        "Bash(pdftotext:*)",
        "--disallowedTools",
        "Write",
        "Edit",
        "NotebookEdit",
    ]
    for d in read_dirs:
        argv.extend(["--add-dir", str(d)])

    def run(prompt: str) -> str:
        try:
            proc = subprocess.run(
                list(argv),
                input=prompt,
                cwd=vault,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise LessonError(f"claude timed out after {timeout}s") from None
        except OSError as exc:
            raise LessonError(f"claude not runnable: {exc}") from None
        if proc.returncode != 0:
            stderr_tail = proc.stderr[-300:] if proc.stderr else ""
            raise LessonError(
                f"claude exited with code {proc.returncode}: {stderr_tail}"
            )
        stdout = proc.stdout.strip()
        if not stdout:
            raise LessonError("claude returned no output")
        return stdout

    return run


__all__ = [
    "Runner",
    "LessonError",
    "claude_runner",
]
