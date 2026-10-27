import subprocess
from pathlib import Path

import pytest

import libra.obsidian_vault as ov


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.setenv(name, "test")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    return repo


def test_commit_paths_basic(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    note = repo / "note.md"
    note.write_text("hello")
    assert ov.commit_paths(repo, [note], "add note")
    log = _git(repo, "log", "--oneline").stdout.strip().splitlines()
    assert len(log) == 1
    assert "add note" in log[0]
    show = _git(repo, "show", "--stat", "--name-only", "HEAD").stdout
    assert "note.md" in show


def test_commit_paths_only_given_file(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    untracked = repo / "untracked.md"
    untracked.write_text("untracked")
    tracked = repo / "tracked.md"
    tracked.write_text("original")
    _git(repo, "add", "tracked.md")
    _git(repo, "commit", "-m", "base")

    tracked.write_text("modified")
    note = repo / "note.md"
    note.write_text("note")

    assert ov.commit_paths(repo, [note], "add note")
    show = _git(repo, "show", "--name-only", "HEAD").stdout
    assert "note.md" in show
    assert "untracked.md" not in show
    status = _git(repo, "status", "--short").stdout
    assert "?? untracked.md" in status
    assert " M tracked.md" in status


def test_commit_paths_not_git_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    note = plain / "note.md"
    note.write_text("hello")
    assert ov.commit_paths(plain, [note], "msg") is False


def test_commit_paths_empty(tmp_path):
    repo = _init_repo(tmp_path)
    assert ov.commit_paths(repo, [], "msg") is False


def test_commit_paths_locked_index(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    note = repo / "note.md"
    note.write_text("hello")
    (repo / ".git" / "index.lock").write_text("locked")
    assert ov.commit_paths(repo, [note], "add note") is False
    assert note.exists()


def test_commit_paths_missing_path(tmp_path):
    repo = _init_repo(tmp_path)
    missing = repo / "missing.md"
    assert ov.commit_paths(repo, [missing], "msg") is False


def test_has_uncommitted_changes_clean_tracked(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "a.md").write_text("base\n")
    _git(repo, "add", "a.md")
    _git(repo, "commit", "-m", "base")
    assert ov.has_uncommitted_changes(repo, [Path("a.md")]) is False


def test_has_uncommitted_changes_modified(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "a.md").write_text("base\n")
    _git(repo, "add", "a.md")
    _git(repo, "commit", "-m", "base")
    (repo / "a.md").write_text("changed\n")
    assert ov.has_uncommitted_changes(repo, [Path("a.md")]) is True


def test_has_uncommitted_changes_untracked(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "b.md").write_text("new\n")
    assert ov.has_uncommitted_changes(repo, [Path("b.md")]) is True


def test_has_uncommitted_changes_ignores_other_paths(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "a.md").write_text("base\n")
    _git(repo, "add", "a.md")
    _git(repo, "commit", "-m", "base")
    (repo / "b.md").write_text("untracked\n")
    assert ov.has_uncommitted_changes(repo, [Path("a.md")]) is False


def test_has_uncommitted_changes_not_git_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.md").write_text("data\n")
    assert ov.has_uncommitted_changes(plain, [Path("a.md")]) is False


def test_has_uncommitted_changes_empty(tmp_path):
    repo = _init_repo(tmp_path)
    assert ov.has_uncommitted_changes(repo, []) is False


def test_has_uncommitted_changes_git_failure_is_true(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    (repo / "a.md").write_text("base\n")
    _git(repo, "add", "a.md")
    _git(repo, "commit", "-m", "base")

    real_git = ov._git

    def failing_git(
        repo_dir: Path,
        args: list[str],
        *,
        timeout_s: float,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess:
        if args and args[0] == "status":
            raise subprocess.TimeoutExpired(cmd="git", timeout=1)
        return real_git(repo_dir, args, timeout_s=timeout_s, env=env)

    monkeypatch.setattr(ov, "_git", failing_git)
    assert ov.has_uncommitted_changes(repo, [Path("a.md")]) is True
