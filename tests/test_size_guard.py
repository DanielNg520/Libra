# ADR-0027 size guard: files <= 600 lines, functions <= 100 code lines (no permanent exceptions).
import ast
from pathlib import Path

import pytest

MAX_FILE_LINES = 600
MAX_FUNC_CODE_LINES = 100


_PERMANENT_FUNC_CAPS: dict[str, int] = {}

REPO_ROOT = Path(__file__).resolve().parent.parent


def count_code_lines(source: str, node: ast.AST) -> int:
    lines = source.splitlines()
    start_lineno = node.lineno
    end_lineno = node.end_lineno
    docstring_lines = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            for i in range(node.body[0].lineno, node.body[0].end_lineno + 1):
                docstring_lines.add(i)
    count = 0
    for i in range(start_lineno, end_lineno + 1):
        if i in docstring_lines:
            continue
        text = lines[i - 1].strip()
        if text and not text.startswith("#"):
            count += 1
    return count


def _qualified_name(node: ast.AST) -> str:
    parts = []
    current = node
    while isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        parts.append(current.name)
        parent = getattr(current, "_semai_parent", None)
        current = parent
    return ".".join(reversed(parts))


def _collect_functions(tree: ast.AST, prefix: str, func_counts: dict, source: str, rel: str):
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qname = f"{prefix}.{node.name}" if prefix else node.name
            func_counts[f"{rel}::{qname}"] = count_code_lines(source, node)
            _collect_functions(node, qname, func_counts, source, rel)
        elif isinstance(node, ast.ClassDef):
            class_prefix = f"{prefix}.{node.name}" if prefix else node.name
            _collect_functions(node, class_prefix, func_counts, source, rel)


def _scan_sources():
    file_counts = {}
    func_counts = {}
    for py_file in (REPO_ROOT / "src" / "libra").rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        source = py_file.read_text()
        file_counts[rel] = len(source.splitlines())
        tree = ast.parse(source)
        _collect_functions(tree, "", func_counts, source, rel)
    return file_counts, func_counts


@pytest.fixture(scope="module")
def scan_data():
    return _scan_sources()


def test_counting_rule():
    src = '''def outer(x):
    """Docstring line one.
    Docstring line two."""

    a = 1  # inline comment
    # full-line comment
    def inner():
        return 2
    return a + inner()


@decorator
def decorated():
    pass
'''
    tree = ast.parse(src)
    outer = tree.body[0]
    assert isinstance(outer, ast.FunctionDef)
    assert count_code_lines(src, outer) == 5


def test_file_limit(scan_data):
    file_counts, _ = scan_data
    failures = []
    for path, count in file_counts.items():
        limit = MAX_FILE_LINES
        if count > limit:
            failures.append(f"{path}: {count} lines > limit {limit}")
    assert not failures, "\n".join(failures)


def test_function_limit(scan_data):
    _, func_counts = scan_data
    failures = []
    for key, count in func_counts.items():
        path, qname = key.split("::", 1)
        limit = _PERMANENT_FUNC_CAPS.get(key, MAX_FUNC_CODE_LINES)
        if count > limit:
            failures.append(f"{key}: {count} code lines > limit {limit}")
    assert not failures, "\n".join(failures)


def test_permanent_exceptions(scan_data):
    _, func_counts = scan_data
    failures = []
    for key, cap in _PERMANENT_FUNC_CAPS.items():
        if key not in func_counts:
            failures.append(f"permanent exception for missing function {key}")
            continue
        current = func_counts[key]
        if current > cap:
            failures.append(f"{key}: {current} code lines > permanent limit {cap}")
    assert not failures, "\n".join(failures)
