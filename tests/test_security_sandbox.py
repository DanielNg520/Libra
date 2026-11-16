import shutil
import subprocess
from pathlib import Path

import pytest

from libra.sandbox import SandboxError, SandboxUnavailable, run_sandboxed, sandbox_argv

NET_PROBE = "import socket\nsocket.create_connection(('1.1.1.1', 80), timeout=3)\n"

needs_bwrap = pytest.mark.skipif(
    shutil.which("bwrap") is None, reason="bwrap not installed"
)


def _index_of(argv: list[str], triple: list[str]) -> int:
    n = len(triple)
    for i in range(len(argv) - n + 1):
        if argv[i : i + n] == triple:
            return i
    raise AssertionError(f"{triple!r} not found in {argv!r}")


def test_argv_structure() -> None:
    cmd = ["bash", "-c", "true"]
    argv = sandbox_argv(cmd)
    assert argv[0] == "bwrap"
    assert argv[1] == "--clearenv"
    assert argv[2:8] == "--setenv HOME /work --setenv PATH /usr/bin:/bin".split()
    assert "--proc" not in argv
    assert argv[-3:] == cmd


def test_ro_binds_order() -> None:
    ro_binds = [Path("/opt/a"), Path("/opt/b")]
    argv = sandbox_argv(["true"], ro_binds=ro_binds)
    a_idx = _index_of(argv, ["--ro-bind", "/opt/a", "/opt/a"])
    b_idx = _index_of(argv, ["--ro-bind", "/opt/b", "/opt/b"])
    assert a_idx < b_idx


def test_rw_dir_and_workdir(tmp_path: Path) -> None:
    argv = sandbox_argv(["true"], rw_dir=tmp_path)
    _index_of(argv, ["--bind", str(tmp_path), "/work"])
    assert "--dir" not in argv
    argv = sandbox_argv(["true"])
    _index_of(argv, ["--dir", "/work"])
    _index_of(argv, ["--chdir", "/work"])
    argv = sandbox_argv(["true"], workdir="/out")
    _index_of(argv, ["--setenv", "HOME", "/out"])
    _index_of(argv, ["--chdir", "/out"])


def test_usr_ro_bind_no_home() -> None:
    argv = sandbox_argv(["true"])
    _index_of(argv, ["--ro-bind", "/usr", "/usr"])
    assert str(Path.home()) not in argv


def test_raises_sandbox_error_without_bwrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(SandboxUnavailable):
        run_sandboxed(["true"], timeout_s=1)
    assert issubclass(SandboxUnavailable, SandboxError)
    assert issubclass(SandboxError, RuntimeError)


@needs_bwrap
def test_env_cleared_and_extra_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMAI_SANDBOX_PROBE", "leak")
    proc = run_sandboxed(
        ["bash", "-c", 'printf %s "${SEMAI_SANDBOX_PROBE-unset}"'],
        timeout_s=10,
    )
    assert proc.stdout == "unset"
    proc = run_sandboxed(
        ["bash", "-c", 'printf %s "$EXTRA_OK"'],
        timeout_s=10,
        env={"EXTRA_OK": "1"},
    )
    assert proc.stdout == "1"


@needs_bwrap
def test_no_network() -> None:
    proc = run_sandboxed(["/usr/bin/python3", "-c", NET_PROBE], timeout_s=10)
    assert proc.returncode != 0


@needs_bwrap
def test_home_hidden() -> None:
    proc = run_sandboxed(["test", "-e", str(Path.home())], timeout_s=10)
    assert proc.returncode != 0


@needs_bwrap
def test_rw_dir_writable_and_visible(tmp_path: Path) -> None:
    proc = run_sandboxed(
        ["bash", "-c", "printf ok > made.txt"],
        timeout_s=10,
        rw_dir=tmp_path,
    )
    assert proc.returncode == 0
    assert (tmp_path / "made.txt").read_text() == "ok"


@needs_bwrap
def test_timeout() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        run_sandboxed(["sleep", "5"], timeout_s=0.5)


@needs_bwrap
def test_memory_cap() -> None:
    proc = run_sandboxed(
        ["/usr/bin/python3", "-c", "b = bytearray(1024 * 1024 * 1024)"],
        timeout_s=10,
        mem_bytes=256 * 1024 * 1024,
    )
    assert proc.returncode != 0
    assert "MemoryError" in proc.stderr
