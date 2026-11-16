"""Shared bubblewrap (`bwrap`) sandbox for untrusted commands.

Cleared environment (`--clearenv`), no network or other namespaces
(`--unshare-all`), read-only `/usr` and loader config, tmpfs `/tmp`
`/run` `/var`, one optional writable work dir. No `/proc` mount because
`--proc` fails inside the systemd-sandboxed units.
"""
from __future__ import annotations

import resource
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


class SandboxError(RuntimeError):
    """Raised when the sandbox cannot run."""


class SandboxUnavailable(SandboxError):
    """Raised when the `bwrap` binary is missing."""


# Fixed argv pieces, shared by every sandbox invocation.
_RO_BINDS: tuple[tuple[str, str], ...] = (
    ("--ro-bind", "/usr", "/usr"),
    ("--symlink", "usr/bin", "/bin"),
    ("--symlink", "usr/sbin", "/sbin"),
    ("--symlink", "usr/lib", "/lib"),
    ("--symlink", "usr/lib64", "/lib64"),
)
_RO_BIND_TRIES: tuple[tuple[str, str], ...] = tuple(
    ("--ro-bind-try", p, p)
    for p in (
        "/etc/ld.so.cache",
        "/etc/ld.so.conf",
        "/etc/ld.so.conf.d",
        "/etc/alternatives",
        "/etc/fonts",
    )
)
_ISOLATION: tuple[tuple[str, ...], ...] = (
    ("--dev", "/dev"),
    ("--tmpfs", "/tmp"),
    ("--tmpfs", "/run"),
    ("--tmpfs", "/var"),
)
_UNSHARE: tuple[str, ...] = ("--unshare-all", "--new-session", "--die-with-parent")
# Never emit --proc: it fails with "Operation not permitted" inside the systemd-sandboxed units.


def _build_argv(
    cmd: list[str],
    ro_binds: Sequence[Path],
    rw_dir: Path | None,
    workdir: str,
    env: Mapping[str, str],
) -> list[str]:
    argv = ["bwrap", "--clearenv", "--setenv", "HOME", workdir, "--setenv", "PATH", "/usr/bin:/bin"]

    for key, value in env.items():
        argv.extend(("--setenv", key, value))

    for opt, *args in _RO_BINDS:
        argv.extend((opt, *args))
    for opt, *args in _RO_BIND_TRIES:
        argv.extend((opt, *args))
    for opt, *args in _ISOLATION:
        argv.extend((opt, *args))

    for path in ro_binds:
        argv.extend(("--ro-bind", str(path), str(path)))

    if rw_dir is not None:
        argv.extend(("--bind", str(rw_dir), workdir))
    else:
        argv.extend(("--dir", workdir))

    argv.extend(("--chdir", workdir))
    argv.extend(_UNSHARE)
    argv.extend(cmd)

    return argv


def sandbox_argv(
    cmd: list[str],
    *,
    ro_binds: Sequence[Path] = (),
    rw_dir: Path | None = None,
    workdir: str = "/work",
) -> list[str]:
    """Return the full bwrap argv for `cmd`."""
    return _build_argv(cmd, ro_binds, rw_dir, workdir, {})


def _make_preexec_fn(mem_bytes: int) -> Callable[[], None]:
    def set_limit() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

    return set_limit


def run_sandboxed(
    cmd: list[str],
    *,
    ro_binds: Sequence[Path] = (),
    rw_dir: Path | None = None,
    workdir: str = "/work",
    timeout_s: float,
    mem_bytes: int | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `cmd` inside bwrap and return the completed process."""
    if shutil.which("bwrap") is None:
        raise SandboxUnavailable("bwrap not found on PATH")

    argv = _build_argv(cmd, ro_binds, rw_dir, workdir, env or {})
    preexec_fn = _make_preexec_fn(mem_bytes) if mem_bytes is not None else None

    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        preexec_fn=preexec_fn,
        check=False,
    )
