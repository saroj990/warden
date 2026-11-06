"""Unit tests for surrounding-line context gathering."""

from __future__ import annotations

from pr_review.context import gather_surrounding_context
from pr_review.git import parse_unified_diff

SAMPLE_DIFF = """\
diff --git a/pkg/service.py b/pkg/service.py
index 1111111..2222222 100644
--- a/pkg/service.py
+++ b/pkg/service.py
@@ -8,3 +8,4 @@ def load():
     header = read_header()
-    return header
+    value = header.get("id")
+    return value
"""


def test_loads_surrounding_lines_around_hunk(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "pkg"
    source.mkdir()
    lines = [f"line {index}" for index in range(1, 21)]
    lines[7] = "def load():"
    lines[8] = "    header = read_header()"
    lines[9] = "    value = header.get('id')"
    lines[10] = "    return value"
    (source / "service.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    parsed = parse_unified_diff(SAMPLE_DIFF)
    gathered = gather_surrounding_context(
        repo_root=repo,
        file_diffs=parsed.files,
        exclude_globs=[],
        surrounding_lines=2,
        max_bytes=10_000,
    )

    assert len(gathered.inspected) == 1
    inspection = gathered.inspected[0]
    assert inspection.path == "pkg/service.py"
    assert inspection.start_line == 6
    assert inspection.end_line == 12
    assert "value = header.get" in gathered.prompt_text
    assert "line 1|" not in gathered.prompt_text


def test_respects_exclude_globs(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    secret = repo / ".env"
    secret.write_text("TOKEN=1\n", encoding="utf-8")
    diff = """\
diff --git a/.env b/.env
--- a/.env
+++ b/.env
@@ -1 +1 @@
-TOKEN=0
+TOKEN=1
"""
    parsed = parse_unified_diff(diff)
    gathered = gather_surrounding_context(
        repo_root=repo,
        file_diffs=parsed.files,
        exclude_globs=[".env"],
        surrounding_lines=5,
        max_bytes=10_000,
    )
    assert gathered.inspected == []
    assert gathered.prompt_text == ""
    assert any("Excluded path" in note for note in gathered.notes)
