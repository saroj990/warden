"""Unit tests for repository symbol search."""

from __future__ import annotations

import subprocess
from pathlib import Path

from pr_review.context.search import gather_symbol_context
from pr_review.git import parse_unified_diff

CALL_DIFF = """\
diff --git a/order.py b/order.py
--- a/order.py
+++ b/order.py
@@ -1 +1,2 @@
-total = 1
+total = apply_discount(1)
+return total
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "lib.py").write_text(
        "def apply_discount(amount):\n    return amount\n",
        encoding="utf-8",
    )
    (repo / "order.py").write_text("total = 1\n", encoding="utf-8")
    (repo / ".env").write_text("apply_discount=secret\n", encoding="utf-8")
    _git(repo, "add", "lib.py", "order.py", ".env")
    _git(repo, "commit", "-m", "init")
    return repo


def test_finds_callers_outside_the_changed_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    parsed = parse_unified_diff(CALL_DIFF)
    gathered = gather_symbol_context(
        repo_root=repo,
        file_diffs=parsed.files,
        exclude_globs=[".env", ".env.*"],
        max_bytes=10_000,
    )

    assert "def apply_discount" in gathered.prompt_text
    assert "order.py" not in gathered.prompt_text
    assert ".env" not in gathered.prompt_text
    assert gathered.inspected
    assert gathered.inspected[0].path == "lib.py"
    assert gathered.inspected[0].reason == "symbol search for apply_discount"
    assert any(
        "Excluded path from symbol search: .env" in note for note in gathered.notes
    )


def test_skips_symbol_search_outside_a_work_tree(tmp_path: Path) -> None:
    parsed = parse_unified_diff(CALL_DIFF)
    gathered = gather_symbol_context(
        repo_root=tmp_path,
        file_diffs=parsed.files,
        exclude_globs=[],
        max_bytes=10_000,
    )
    assert gathered.prompt_text == ""
    assert any("not a git work tree" in note for note in gathered.notes)


def test_stops_when_the_byte_budget_is_exhausted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    parsed = parse_unified_diff(CALL_DIFF)
    gathered = gather_symbol_context(
        repo_root=repo,
        file_diffs=parsed.files,
        exclude_globs=[".env", ".env.*"],
        max_bytes=20,
    )
    assert gathered.prompt_text == ""
    assert any("max_context_bytes" in note for note in gathered.notes)


def test_ignores_added_lines_without_symbols(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    diff = """\
diff --git a/order.py b/order.py
--- a/order.py
+++ b/order.py
@@ -1 +1 @@
-total = 1
+total = 2
"""
    parsed = parse_unified_diff(diff)
    gathered = gather_symbol_context(
        repo_root=repo,
        file_diffs=parsed.files,
        exclude_globs=[],
        max_bytes=10_000,
    )
    assert gathered.prompt_text == ""
    assert gathered.notes == []
