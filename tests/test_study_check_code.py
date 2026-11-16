"""Tests for the C3 code_run kind (`study/check_code.py`) and engine notes."""

import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from libra.study import check_code
from libra.study.check_code import Note
from libra.study.check_kinds import KINDS, parse_lesson
from libra.study.checks import Failure, Rule, check_text

FRONTMATTER = "---\ntags:\n  - topic/c\n---\n"


def _run(lines: Sequence[str], params: Mapping[str, object] | None = None) -> list:
    text = FRONTMATTER + "\n".join(lines)
    lesson = parse_lesson(text, "Coding Practice/Bare Metal C/lessons/01 x.md")
    return KINDS["code_run"].check(lesson, params or {}, Path("/nonexistent"))


def _failures(out: list) -> list:
    return [x for x in out if isinstance(x, tuple)]


def _notes(out: list) -> list:
    return [x for x in out if isinstance(x, Note)]


class _Fake:
    def __init__(self, results: list, capture: dict | None = None):
        self.results = list(results)
        self.calls: list[dict] = []
        self.capture = capture if capture is not None else {}

    def __call__(self, cmd, *, rw_dir=None, timeout_s, mem_bytes=None, **kw):
        self.calls.append(
            {
                "cmd": list(cmd),
                "files": sorted(p.name for p in rw_dir.iterdir()) if rw_dir else [],
                "timeout_s": timeout_s,
                "mem_bytes": mem_bytes,
            }
        )
        if rw_dir and (rw_dir / "snippet.c").exists():
            self.capture["snippet.c"] = (rw_dir / "snippet.c").read_text()
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


needs_python = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
needs_gcc = pytest.mark.skipif(
    shutil.which("bwrap") is None or shutil.which("gcc") is None, reason="bwrap or gcc not installed"
)

needs_gpp = pytest.mark.skipif(
    shutil.which("bwrap") is None or shutil.which("g++") is None, reason="bwrap or g++ not installed"
)


def _ok(stdout="", rc=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_python_no_markers_rc0(monkeypatch):
    fake = _Fake([_ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```python", "print(1)", "```"])
    assert _failures(out) == []
    assert _notes(out) == []
    assert fake.calls[0]["cmd"] == ["python3", "-I", "/work/snippet.py"]
    assert "snippet.py" in fake.calls[0]["files"]


def test_python_output_matches_whitespace_collapsed(monkeypatch):
    fake = _Fake([_ok(stdout="1\n2   3\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(
        [
            "```python",
            "print(1)  # output: 1",
            "print(2, 3)  # output: 2 3",
            "```",
        ]
    )
    assert _failures(out) == []
    assert _notes(out) == []


def test_python_output_mismatch(monkeypatch):
    fake = _Fake([_ok(stdout="1\n2 4\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(
        [
            "```python",
            "print(1)  # output: 1",
            "print(2, 3)  # output: 2 3",
            "```",
        ]
    )
    assert _failures(out) == [(5, "code_run: output mismatch: expected '1 2 3', got '1 2 4'")]


def test_python_output_long_mismatch_after_200(monkeypatch):
    fake = _Fake([_ok(stdout="a" * 249 + "b\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```python", f'print("{"a" * 250}")  # output: {"a" * 250}', "```"])
    findings = _failures(out)
    assert len(findings) == 1
    assert findings[0][0] == 5
    assert findings[0][1].startswith("code_run: output mismatch: expected '")


def test_python_exit_error(monkeypatch):
    fake = _Fake([_ok(rc=1, stderr="Traceback\n  x\nNameError: name 'y' is not defined\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```python", "print(y)", "```"])
    assert _failures(out) == [(5, "code_run: python block exited 1: NameError: name 'y' is not defined")]


def test_python_timeout(monkeypatch):
    fake = _Fake([subprocess.TimeoutExpired(cmd="x", timeout=3)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```python", "while True: pass", "```"])
    assert _failures(out) == [(5, "code_run: python block timed out after 3s")]


def test_broken_python_typeerror_matches(monkeypatch):
    fake = _Fake([_ok(rc=1, stderr="TypeError: list indices")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "Broken: bad index.",
        "",
        "```python",
        "x = [1][0.5]  # TypeError: bad",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == []
    assert _notes(out) == []


def test_broken_python_typeerror_not_raised(monkeypatch):
    fake = _Fake([_ok(rc=0)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "Broken: bad index.",
        "",
        "```python",
        "x = [1][0.5]  # TypeError: bad",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == [(7, "code_run: broken block never raised TypeError")]


def test_broken_python_typeerror_timeout(monkeypatch):
    fake = _Fake([subprocess.TimeoutExpired(cmd="x", timeout=3)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "Broken: bad index.",
        "",
        "```python",
        "x = [1][0.5]  # TypeError: bad",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == [(7, "code_run: broken block never raised TypeError")]


def test_broken_python_typeerror_wrong_error(monkeypatch):
    fake = _Fake([_ok(rc=1, stderr="ValueError: v")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "Broken: bad index.",
        "",
        "```python",
        "x = [1][0.5]  # TypeError: bad",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == [(7, "code_run: broken block never raised TypeError")]


def test_broken_python_typeerror_rc0_with_stderr(monkeypatch):
    fake = _Fake([_ok(rc=0, stderr="TypeError mentioned in a warning")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "Broken: bad index.",
        "",
        "```python",
        "x = [1][0.5]  # TypeError: bad",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == [(7, "code_run: broken block never raised TypeError")]


def test_broken_python_no_error_name_rc1(monkeypatch):
    fake = _Fake([_ok(rc=1, stderr="boom")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "Broken: bad.",
        "",
        "```python",
        "raise ValueError('x')",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == []
    assert _notes(out) == []


def test_broken_python_no_error_name_timeout(monkeypatch):
    fake = _Fake([subprocess.TimeoutExpired(cmd="x", timeout=3)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "Broken: bad.",
        "",
        "```python",
        "while True: pass",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == []
    assert _notes(out) == []


def test_broken_python_output_checked_on_error(monkeypatch):
    fake = _Fake([_ok(rc=1, stdout="6\n", stderr="TypeError: t")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "Broken: bad.",
        "",
        "```python",
        "print(5)  # output: 5",
        "# TypeError",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == [(7, "code_run: output mismatch: expected '5', got '6'")]


def test_fixed_line_not_broken(monkeypatch):
    fake = _Fake([_ok(rc=1, stderr="boom")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "Fixed: this works now.",
        "",
        "```python",
        "raise ValueError('x')  # ValueError: bad",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == [(7, "code_run: python block exited 1: boom")]


def test_c_full_block_runs(monkeypatch):
    fake = _Fake([_ok(), _ok(stdout="8 10\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(
        [
            "```c",
            "int main(void) {",
            "    return 0;",
            "} /* output: 8 10 */",
            "```",
        ]
    )
    assert _failures(out) == []
    assert _notes(out) == []
    assert len(fake.calls) == 2
    assert fake.calls[0]["cmd"] == [
        "gcc",
        "-std=c99",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-o",
        "/work/a.out",
        "/work/snippet.c",
    ]
    assert fake.calls[1]["cmd"] == ["/work/a.out"]
    assert "snippet.c" in fake.calls[0]["files"]


def test_broken_c_compile_no_werror(monkeypatch):
    fake = _Fake([_ok(rc=1, stderr="error: bad")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "Broken: bad.",
        "",
        "```c",
        "int main(void) { return bad; }",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == []
    assert _notes(out) == []
    assert len(fake.calls) == 1
    assert "-Werror" not in fake.calls[0]["cmd"]


def test_broken_python_clean_run_notes(monkeypatch):
    fake = _Fake([_ok(rc=0)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["Broken: bad.", "", "```python", "x = 1", "```"])
    assert _failures(out) == []
    assert _notes(out) == [Note(7, "code_run: broken python block ran clean and names no error")]


def test_broken_python_named_error_clean_run_no_note(monkeypatch):
    fake = _Fake([_ok(rc=0)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["Broken: bad.", "", "```python", "x = 1  # TypeError: bad", "```"])
    assert _failures(out) == [(7, "code_run: broken block never raised TypeError")]
    assert _notes(out) == []


def test_broken_c_clean_run_notes(monkeypatch):
    fake = _Fake([_ok(), _ok(rc=0)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["Broken: bad.", "", "```c", "int main(void) { return 0; }", "```"])
    assert _failures(out) == []
    assert _notes(out) == [Note(7, "code_run: broken C block compiled and ran clean")]


def test_broken_c_nonzero_run_no_note(monkeypatch):
    fake = _Fake([_ok(), _ok(rc=1)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["Broken: bad.", "", "```c", "int main(void) { return 1; }", "```"])
    assert _failures(out) == []
    assert _notes(out) == []


def test_broken_cpp_clean_run_notes(monkeypatch):
    fake = _Fake([_ok(), _ok(rc=0)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["Broken: bad.", "", "```cpp", "int main() { return 0; }", "```"])
    assert _failures(out) == []
    assert _notes(out) == [Note(7, "code_run: broken C++ block compiled and ran clean")]


def test_c_compile_error_nonbroken(monkeypatch):
    fake = _Fake([_ok(rc=1, stderr="snippet.c: In function 'main':\nsnippet.c:3:5: error: boom\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```c", "int main(void) {", "    bad();", "}", "```"])
    assert _failures(out) == [(5, "code_run: C block does not compile: snippet.c:3:5: error: boom")]


def test_c_run_nonzero_allowed(monkeypatch):
    fake = _Fake([_ok(), _ok(rc=1)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```c", "int main(void) { return 1; }", "```"])
    assert _failures(out) == []
    assert _notes(out) == []


def test_c_run_signal_crash(monkeypatch):
    fake = _Fake([_ok(), _ok(rc=-11)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```c", "int main(void) { return 0; }", "```"])
    assert _failures(out) == [(5, "code_run: C block crashed (signal 11)")]


def test_c_run_signal_via_bwrap_status(monkeypatch):
    fake = _Fake([_ok(), _ok(rc=139)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```c", "int main(void) { return 0; }", "```"])
    assert _failures(out) == [(5, "code_run: C block crashed (signal 11)")]


def test_c_run_exit_128_allowed(monkeypatch):
    fake = _Fake([_ok(), _ok(rc=128)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```c", "int main(void) { return 0; }", "```"])
    assert _failures(out) == []


def test_c_run_timeout(monkeypatch):
    fake = _Fake([_ok(), subprocess.TimeoutExpired(cmd="x", timeout=3)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```c", "int main(void) { while(1){} }", "```"])
    assert _failures(out) == [(5, "code_run: C block timed out after 3s")]


def test_c_compile_timeout(monkeypatch):
    fake = _Fake([subprocess.TimeoutExpired(cmd="x", timeout=3)])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```c", "int main(void) { return 0; }", "```"])
    assert _failures(out) == [(5, "code_run: C compile timed out after 3s")]


def test_c_fragment_skipped(monkeypatch):
    fake = _Fake([])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```c", "int helper(void) { return 1; }", "```"])
    assert _failures(out) == []
    assert _notes(out) == [Note(5, "code_run: skipped C fragment without main")]
    assert fake.calls == []


def test_quoted_block_skipped(monkeypatch):
    fake = _Fake([])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "> [!success]- Answer",
        "> ```python",
        "> print(1)",
        "> ```",
    ]
    out = _run(lines)
    assert _failures(out) == []
    assert _notes(out) == [Note(6, "code_run: skipped code block inside a callout")]
    assert fake.calls == []


def test_other_languages_ignored(monkeypatch):
    fake = _Fake([_ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "```bash",
        "echo hi",
        "```",
        "```",
        "plain",
        "```",
        "```python",
        "print(1)",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == []
    assert len(fake.calls) == 1


def test_unclosed_python_fence(monkeypatch):
    fake = _Fake([])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```python", "print(1)"])
    assert _failures(out) == [(5, "code_run: unclosed code fence")]
    assert fake.calls == []


def test_tilde_python_fence_runs(monkeypatch):
    fake = _Fake([_ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["~~~python", "print(1)", "~~~"])
    assert _failures(out) == []
    assert len(fake.calls) == 1


def test_long_fence_inner_marker_is_content(monkeypatch):
    fake = _Fake([])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["````md", "```python", "print(1)", "```", "````"])
    assert _failures(out) == []
    assert _notes(out) == []
    assert fake.calls == []


def test_info_string_after_language(monkeypatch):
    fake = _Fake([_ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```python title=demo", "print(1)", "```"])
    assert _failures(out) == []
    assert len(fake.calls) == 1


def test_numbered_listing_code_extracted(monkeypatch):
    capture: dict = {}
    fake = _Fake([_ok(), _ok()], capture=capture)
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "```c",
        " 1  #include <stdio.h>",
        " 2  int main(void) {",
        " 3      return 0;",
        " 4  }",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == []
    assert capture["snippet.c"] == "#include <stdio.h>\nint main(void) {\n    return 0;\n}\n"


def test_sandbox_unavailable_stops(monkeypatch):
    from libra.sandbox import SandboxError

    fake = _Fake([SandboxError("sandbox exploded"), _ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "```python",
        "print(1)",
        "```",
        "```python",
        "print(2)",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == [(None, "code_run: sandbox unavailable: sandbox exploded")]
    assert len(fake.calls) == 1


def test_missing_bwrap_is_a_note(monkeypatch):
    from libra.sandbox import SandboxUnavailable

    fake = _Fake([SandboxUnavailable(), _ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    lines = [
        "```python",
        "print(1)",
        "```",
        "```python",
        "print(2)",
        "```",
    ]
    out = _run(lines)
    assert _failures(out) == []
    notes = _notes(out)
    assert [(n.line, n.message) for n in notes] == [
        (None, "code_run: skipped, bwrap not found (Fedora only)")
    ]
    assert len(fake.calls) == 1


def test_params_reach_fake(monkeypatch):
    fake = _Fake([_ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    _run(["```python", "print(1)", "```"], {"timeout_s": 7, "mem_mb": 100})
    assert fake.calls[0]["timeout_s"] == 7
    assert fake.calls[0]["mem_bytes"] == 100 * 1024 * 1024


def test_params_c_flags_override(monkeypatch):
    fake = _Fake([_ok(), _ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    _run(["```c", "int main(void) { return 0; }", "```"], {"c_flags": ["-std=c11"]})
    assert fake.calls[0]["cmd"] == ["gcc", "-std=c11", "-Werror", "-o", "/work/a.out", "/work/snippet.c"]


def _validate(params: Mapping[str, object]) -> str | None:
    return KINDS["code_run"].validate(params)


def test_validate_empty():
    assert _validate({}) is None


def test_validate_timeout_low():
    assert _validate({"timeout_s": 0}) == "timeout_s must be between 1 and 60"


def test_validate_timeout_high():
    assert _validate({"timeout_s": 61}) == "timeout_s must be between 1 and 60"


def test_validate_mem_low():
    assert _validate({"mem_mb": 63}) == "mem_mb must be at least 64"


def test_validate_broken_bad_regex():
    assert _validate({"broken": "("}).startswith("bad regex")


def test_validate_python_output_no_group():
    assert _validate({"python_output": "output:"}) == "python_output needs one group"


def test_validate_error_name_no_group():
    assert _validate({"error_name": "x"}) == "error_name needs one group"


def test_cpp_full_block_runs(monkeypatch):
    fake = _Fake([_ok(), _ok(stdout="5\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```cpp", "int main() {", "    return 0;", "}", "// output: 5", "```"])
    assert _failures(out) == []
    assert _notes(out) == []
    assert len(fake.calls) == 2
    assert fake.calls[0]["cmd"] == ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-o", "/work/a.out", "/work/snippet.cpp"]
    assert "snippet.cpp" in fake.calls[0]["files"]
    assert fake.calls[1]["cmd"] == ["/work/a.out"]


def test_cpp_line_comment_output_mismatch(monkeypatch):
    fake = _Fake([_ok(), _ok(stdout="4\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```cpp", "int main() {", "    return 0;", "}", "// output: 5", "```"])
    assert _failures(out) == [(5, "code_run: output mismatch: expected '5', got '4'")]


def test_cpp_block_comment_output_mismatch(monkeypatch):
    fake = _Fake([_ok(), _ok(stdout="4\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```cpp", "int main() {", "    return 0;", "}", "/* output: 5 */", "```"])
    assert _failures(out) == [(5, "code_run: output mismatch: expected '5', got '4'")]


@pytest.mark.parametrize("lang", ["cpp", "c++", "cxx", "C++"])
def test_cpp_fence_aliases(monkeypatch, lang):
    fake = _Fake([_ok(), _ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    _run([f"```{lang}", "int main() {", "    return 0;", "}", "```"])
    assert fake.calls[0]["cmd"][0] == "g++"


def test_broken_cpp_compile_no_werror(monkeypatch):
    fake = _Fake([_ok(rc=1, stderr="error: bad\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["Broken: missing semicolon.", "", "```cpp", "int main() {", "    return 0", "}", "```"])
    assert _failures(out) == []
    assert len(fake.calls) == 1
    assert "-Werror" not in fake.calls[0]["cmd"]


def test_cpp_compile_error_nonbroken(monkeypatch):
    fake = _Fake([_ok(rc=1, stderr="snippet.cpp: In function 'int main()':\nsnippet.cpp:3:5: error: boom\n")])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```cpp", "int main() {", "    bad();", "}", "```"])
    assert _failures(out) == [(5, "code_run: C++ block does not compile: snippet.cpp:3:5: error: boom")]


def test_cpp_fragment_skipped(monkeypatch):
    fake = _Fake([])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    out = _run(["```cpp", "int helper() { return 1; }", "```"])
    assert _failures(out) == []
    assert _notes(out) == [Note(5, "code_run: skipped C++ fragment without main")]
    assert fake.calls == []


def test_params_cpp_flags_override(monkeypatch):
    fake = _Fake([_ok(), _ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    _run(["```cpp", "int main() {", "    return 0;", "}", "```"], params={"cpp_flags": ["-std=c++20"]})
    assert fake.calls[0]["cmd"] == ["g++", "-std=c++20", "-Werror", "-o", "/work/a.out", "/work/snippet.cpp"]


def test_c_flags_do_not_reach_cpp(monkeypatch):
    fake = _Fake([_ok(), _ok()])
    monkeypatch.setattr(check_code, "run_sandboxed", fake)
    _run(["```cpp", "int main() {", "    return 0;", "}", "```"], params={"c_flags": ["-std=c11"]})
    assert fake.calls[0]["cmd"] == ["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-o", "/work/a.out", "/work/snippet.cpp"]


def test_validate_cpp_output_no_group():
    assert _validate({"cpp_output": "output:"}) == "cpp_output needs one group"


def test_validate_cpp_output_bad_regex():
    assert _validate({"cpp_output": "("}).startswith("bad regex")


def test_code_run_accepts_cpp_params():
    assert {"cpp_flags", "cpp_output"} <= set(KINDS["code_run"].optional)


@needs_gpp
def test_real_cpp_success():
    out = _run(
        [
            "```cpp",
            "#include <iostream>",
            "int main() { std::cout << 2 + 3 << '\\n'; return 0; }",
            "// output: 5",
            "```",
        ]
    )
    assert _failures(out) == []
    assert _notes(out) == []


@needs_gpp
def test_real_cpp_unused_variable_fails():
    out = _run(
        [
            "```cpp",
            "#include <iostream>",
            "int main() { int u; std::cout << 2 + 3 << '\\n'; return 0; }",
            "```",
        ]
    )
    failures = _failures(out)
    assert len(failures) == 1
    assert failures[0][0] == 5
    assert failures[0][1].startswith("code_run: C++ block does not compile:")


def test_check_text_c_fragment_note():
    text = FRONTMATTER + "```c\nint helper(void) { return 1; }\n```\n"
    rel = "Coding Practice/Bare Metal C/lessons/01 x.md"
    failures = check_text(
        text,
        rel,
        Path("/nonexistent"),
        [Rule("code-runs", "t", "code_run", ("code",), True, None, {})],
    )
    assert failures == [Failure("code-runs", rel, 5, "code_run: skipped C fragment without main", note=True)]
    assert failures[0].format().startswith("note code-runs ")


def test_failure_format_default():
    f = Failure("r", "a.md", 3, "m")
    assert f.format() == "r a.md:3 m"


@needs_python
def test_real_python_output_match():
    out = _run(["```python", "print(7 // 2)  # output: 3", "```"])
    assert _failures(out) == []
    assert _notes(out) == []


@needs_python
def test_real_python_output_mismatch():
    out = _run(["```python", "print(7 // 2)  # output: 4", "```"])
    assert _failures(out) == [
        (5, "code_run: output mismatch: expected '4', got '3'")
    ]


@needs_python
def test_real_python_timeout():
    out = _run(["```python", "while True: pass", "```"], {"timeout_s": 1})
    assert _failures(out) == [(5, "code_run: python block timed out after 1s")]


@needs_gcc
def test_real_c_success():
    out = _run(
        [
            "```c",
            "#include <stdio.h>",
            "int main(void) { printf(\"%d\\n\", 2 + 3); return 0; }",
            "/* output: 5 */",
            "```",
        ]
    )
    assert _failures(out) == []
    assert _notes(out) == []


@needs_gcc
def test_real_c_unused_variable_fails():
    out = _run(
        [
            "```c",
            "#include <stdio.h>",
            "int main(void) { int u; printf(\"%d\\n\", 2 + 3); return 0; }",
            "```",
        ]
    )
    findings = _failures(out)
    assert len(findings) == 1
    assert findings[0][0] == 5
    assert findings[0][1].startswith("code_run: C block does not compile:")
