"""Unit tests for read-only git diff collection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pr_review.git.repository import GitCommandError, collect_diff


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _repo_with_history(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "app.py").write_text("print('one')\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "init")
    (repo / "app.py").write_text("print('two')\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "second")
    return repo


def test_working_tree_includes_unstaged_changes(tmp_path: Path) -> None:
    repo = _repo_with_history(tmp_path)
    (repo / "app.py").write_text("print('three')\n", encoding="utf-8")

    text, label = collect_diff(repo=repo, base="HEAD")

    assert label == "working tree vs HEAD"
    assert "print('three')" in text
    assert "print('two')" in text


def test_base_head_range_ignores_later_unstaged_edits(tmp_path: Path) -> None:
    repo = _repo_with_history(tmp_path)
    (repo / "app.py").write_text("print('unstaged')\n", encoding="utf-8")

    text, label = collect_diff(repo=repo, base="HEAD~1", head="HEAD")

    assert label == "HEAD~1...HEAD (merge base to head)"
    assert "print('two')" in text
    assert "print('unstaged')" not in text


def test_missing_repository_raises(tmp_path: Path) -> None:
    with pytest.raises(GitCommandError, match="not a directory"):
        collect_diff(repo=tmp_path / "missing", base="main")


def test_non_repository_raises(tmp_path: Path) -> None:
    with pytest.raises(GitCommandError, match="not a git work tree"):
        collect_diff(repo=tmp_path, base="main")


def test_subdirectory_is_not_the_work_tree_root(tmp_path: Path) -> None:
    repo = _repo_with_history(tmp_path)
    nested = repo / "nested"
    nested.mkdir()
    with pytest.raises(GitCommandError, match="not the git work tree root"):
        collect_diff(repo=nested, base="HEAD")
