"""Lesson check kind `code_run`: run Python, C and C++ snippets in the sandbox and match their output markers (ADR-0046 C3)."""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from libra.sandbox import SandboxError, SandboxUnavailable, run_sandboxed
from libra.study.render import scan_blocks

if TYPE_CHECKING:
    from libra.study.check_kinds import Finding, Lesson

_TIMEOUT_S = 3
_MEM_MB = 512
_C_FLAGS = ["-std=c99", "-Wall", "-Wextra"]
_BROKEN_RE = r"^Broken\b"
_PY_OUTPUT_RE = r"#\s*output:\s?(.*)$"
_C_OUTPUT_RE = r"/\*\s*output:\s*(.*?)\s*\*/"
_CPP_FLAGS = ["-std=c++17", "-Wall", "-Wextra"]
_CPP_OUTPUT_RE = r"(?://|/\*)\s*output:\s*(.*?)\s*(?:\*/|$)"
_ERROR_NAME_RE = r"#.*?\b([A-Z]\w*(?:Error|Exception))\b"

__all__ = ["Note", "code_run", "code_run_validate"]


@dataclass(frozen=True)
class Note:
    line: int | None
    message: str


@dataclass(frozen=True)
class _Block:
    lang: str
    fence: int
    code: list[str]
    broken: bool
    quoted: bool


@dataclass(frozen=True)
class _Toolchain:
    compiler: str
    source: str
    label: str
    flags: tuple[str, ...]
    output: re.Pattern[str]


def code_run_validate(params: Mapping[str, object]) -> str | None:
    timeout = params.get("timeout_s")
    if timeout is not None and not 1 <= int(timeout) <= 60:
        return "timeout_s must be between 1 and 60"
    mem = params.get("mem_mb")
    if mem is not None and int(mem) < 64:
        return "mem_mb must be at least 64"
    for name in ("broken", "python_output", "c_output", "cpp_output", "error_name"):
        pattern = params.get(name)
        if pattern is None:
            continue
        try:
            compiled = re.compile(str(pattern))
        except re.error as exc:
            return f"bad regex {pattern!r}: {exc}"
        if compiled.groups < 1 and name in ("python_output", "c_output", "cpp_output", "error_name"):
            return f"{name} needs one group"
    return None


def _blocks(lesson: Lesson, params: Mapping[str, object]) -> list[_Block | Finding]:
    broken_regex = re.compile(str(params.get("broken", _BROKEN_RE)))
    body = lesson.body()
    out: list[_Block | Finding] = []
    for fence in scan_blocks(tuple(body)).fences:
        if not fence.closed:
            out.append((lesson.lineno(fence.start), "code_run: unclosed code fence"))
            break
        lang_word = fence.info.split()[0].lower() if fence.info else ""
        if lang_word in ("python", "py"):
            lang = "python"
        elif lang_word == "c":
            lang = "c"
        elif lang_word in ("cpp", "c++", "cxx"):
            lang = "cpp"
        else:
            lang = ""
        code = fence.content.splitlines()
        if not fence.quoted:
            broken = False
            k = fence.start - 1
            while k >= 0 and body[k].strip() == "":
                k -= 1
            if k >= 0 and broken_regex.match(body[k].strip()):
                broken = True
        else:
            broken = False
        if code and any(s.strip() for s in code):
            if all(re.match(r"^\s*\d+(?: {1,2}|$)", s) or s.strip() == "" for s in code):
                code = [re.sub(r"^\s*\d+(?: {1,2}|$)", "", s) for s in code]
        if lang:
            out.append(_Block(lang=lang, fence=fence.start, code=code, broken=broken, quoted=fence.quoted))
    return out


def _tail(text: str) -> str:
    for chunk in reversed(text.splitlines()):
        if chunk.strip():
            return chunk.strip()[:200]
    return "no stderr"


def _output_finding(lesson: Lesson, block: _Block, pattern: re.Pattern[str], stdout: str) -> Finding | None:
    parts = []
    for code_line in block.code:
        m = pattern.search(code_line)
        if m:
            parts.append(m.group(1))
    if not parts:
        return None
    expected = " ".join(" ".join(parts).split())
    got = " ".join(stdout.split())
    if expected != got:
        return (lesson.lineno(block.fence), f"code_run: output mismatch: expected {expected[:200]!r}, got {got[:200]!r}")
    return None


def _run_python(
    lesson: Lesson,
    block: _Block,
    tmp: Path,
    timeout_s: int,
    mem_bytes: int,
    error_pattern: re.Pattern[str],
    output_pattern: re.Pattern[str],
) -> list[Finding | Note]:
    script = tmp / "snippet.py"
    script.write_text("\n".join(block.code) + "\n", encoding="utf-8")
    findings: list[Finding | Note] = []
    matched_error = None
    if block.broken:
        for code_line in block.code:
            m = error_pattern.search(code_line)
            if m:
                matched_error = m.group(1)
                break
    try:
        proc = run_sandboxed(
            ["python3", "-I", "/work/snippet.py"],
            rw_dir=tmp,
            timeout_s=timeout_s,
            mem_bytes=mem_bytes,
        )
    except subprocess.TimeoutExpired:
        if not block.broken:
            findings.append((lesson.lineno(block.fence), f"code_run: python block timed out after {timeout_s}s"))
        if matched_error is not None:
            findings.append((lesson.lineno(block.fence), f"code_run: broken block never raised {matched_error}"))
        return findings
    if proc.returncode != 0 and not block.broken:
        findings.append(
            (lesson.lineno(block.fence), f"code_run: python block exited {proc.returncode}: {_tail(proc.stderr)}")
        )
    if matched_error is not None and (matched_error not in proc.stderr or proc.returncode == 0):
        findings.append((lesson.lineno(block.fence), f"code_run: broken block never raised {matched_error}"))
    finding = _output_finding(lesson, block, output_pattern, proc.stdout)
    if finding:
        findings.append(finding)
    if block.broken and proc.returncode == 0 and matched_error is None:
        findings.append(Note(lesson.lineno(block.fence), "code_run: broken python block ran clean and names no error"))
    return findings


def _signal(returncode: int) -> int | None:
    if returncode < 0:
        return -returncode
    if 128 < returncode < 160:
        return returncode - 128
    return None


def _run_compiled(
    lesson: Lesson,
    block: _Block,
    tmp: Path,
    timeout_s: int,
    mem_bytes: int,
    chain: _Toolchain,
) -> list[Finding | Note]:
    source = tmp / chain.source
    source.write_text("\n".join(block.code) + "\n", encoding="utf-8")
    findings: list[Finding | Note] = []
    compile_cmd = [chain.compiler, *chain.flags, *([] if block.broken else ["-Werror"]), "-o", "/work/a.out", f"/work/{chain.source}"]
    try:
        proc = run_sandboxed(compile_cmd, rw_dir=tmp, timeout_s=timeout_s, mem_bytes=mem_bytes)
    except subprocess.TimeoutExpired:
        return [(lesson.lineno(block.fence), f"code_run: {chain.label} compile timed out after {timeout_s}s")]
    if proc.returncode != 0:
        if block.broken:
            return findings
        first = None
        for line in proc.stderr.splitlines():
            if "error" in line:
                first = line
                break
        if first is None:
            first = next((line for line in proc.stderr.splitlines() if line.strip()), "no stderr")
        findings.append((lesson.lineno(block.fence), f"code_run: {chain.label} block does not compile: {first.strip()[:200]}"))
        return findings
    try:
        proc = run_sandboxed(["/work/a.out"], rw_dir=tmp, timeout_s=timeout_s, mem_bytes=mem_bytes)
    except subprocess.TimeoutExpired:
        if not block.broken:
            findings.append((lesson.lineno(block.fence), f"code_run: {chain.label} block timed out after {timeout_s}s"))
        return findings
    if not block.broken and (sig := _signal(proc.returncode)) is not None:
        findings.append((lesson.lineno(block.fence), f"code_run: {chain.label} block crashed (signal {sig})"))
        return findings
    finding = _output_finding(lesson, block, chain.output, proc.stdout)
    if finding:
        findings.append(finding)
    if block.broken and proc.returncode == 0:
        findings.append(Note(lesson.lineno(block.fence), f"code_run: broken {chain.label} block compiled and ran clean"))
    return findings


def code_run(lesson: Lesson, params: Mapping[str, object], vault: Path) -> list[Finding | Note]:
    del vault
    timeout_s = int(params.get("timeout_s", _TIMEOUT_S))
    mem_mb = int(params.get("mem_mb", _MEM_MB))
    mem_bytes = mem_mb * 1024 * 1024
    c_flags = [str(flag) for flag in params.get("c_flags", _C_FLAGS)]
    cpp_flags = [str(flag) for flag in params.get("cpp_flags", _CPP_FLAGS)]
    output_pattern = re.compile(str(params.get("python_output", _PY_OUTPUT_RE)))
    c_output_pattern = re.compile(str(params.get("c_output", _C_OUTPUT_RE)))
    cpp_output_pattern = re.compile(str(params.get("cpp_output", _CPP_OUTPUT_RE)))
    error_pattern = re.compile(str(params.get("error_name", _ERROR_NAME_RE)))
    toolchains: dict[str, _Toolchain] = {
        "c": _Toolchain("gcc", "snippet.c", "C", tuple(c_flags), c_output_pattern),
        "cpp": _Toolchain("g++", "snippet.cpp", "C++", tuple(cpp_flags), cpp_output_pattern),
    }
    findings: list[Finding | Note] = []
    for block in _blocks(lesson, params):
        if not isinstance(block, _Block):
            findings.append(block)
            continue
        if block.quoted:
            findings.append(Note(lesson.lineno(block.fence), "code_run: skipped code block inside a callout"))
            continue
        if block.lang in toolchains and not re.search(r"\bint\s+main\s*\(", "\n".join(block.code)):
            findings.append(Note(lesson.lineno(block.fence), f"code_run: skipped {toolchains[block.lang].label} fragment without main"))
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                if block.lang == "python":
                    new_findings = _run_python(
                        lesson, block, tmp_path, timeout_s, mem_bytes, error_pattern, output_pattern
                    )
                else:
                    new_findings = _run_compiled(
                        lesson, block, tmp_path, timeout_s, mem_bytes, toolchains[block.lang]
                    )
                findings.extend(new_findings)
        except SandboxUnavailable:
            findings.append(Note(None, "code_run: skipped, bwrap not found (Fedora only)"))
            break
        except (SandboxError, OSError) as exc:
            findings.append((None, f"code_run: sandbox unavailable: {exc}"))
            break
    return findings
