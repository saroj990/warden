"""Unit tests for unified diff parsing and line mapping."""

from __future__ import annotations

from pathlib import Path

from pr_review.git import (
    FileStatus,
    LineKind,
    is_inline_commentable,
    parse_unified_diff,
    parse_unified_diff_path,
)

MODIFIED_MULTI_HUNK = """\
diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,3 +1,4 @@
 def greet(name):
-    return "hi"
+    # say hello
+    return f"hi {name}"
     pass
@@ -20,1 +21,4 @@ def unused():
     return None
+
+def extra():
+    return 1
"""

ADDED_FILE = """\
diff --git a/new.py b/new.py
new file mode 100644
index 0000000..aaaaaaa
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+print("hello")
+print("world")
"""

DELETED_FILE = """\
diff --git a/gone.py b/gone.py
deleted file mode 100644
index aaaaaaa..0000000
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-print("bye")
-print("now")
"""

RENAMED_FILE = """\
diff --git a/old_name.py b/new_name.py
similarity index 90%
rename from old_name.py
rename to new_name.py
index 1111111..2222222 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,3 +1,3 @@
 def value():
-    return 1
+    return 2
"""

BINARY_FILE = """\
diff --git a/logo.png b/logo.png
index 1111111..2222222 100644
Binary files a/logo.png and b/logo.png differ
"""

EMPTY_ADDED_FILE = """\
diff --git a/empty.txt b/empty.txt
new file mode 100644
index 0000000..e69de29
"""

SIMPLE_UNIFIED = """\
--- a/sample.txt
+++ b/sample.txt
@@ -1,3 +1,4 @@
 alpha
-beta
+beta!
 gamma
+delta
"""


def test_parse_modified_file_with_multiple_hunks() -> None:
    parsed = parse_unified_diff(MODIFIED_MULTI_HUNK)
    assert parsed.file_count == 1
    file_diff = parsed.files[0]
    assert file_diff.status == FileStatus.MODIFIED
    assert file_diff.path == "app.py"
    assert len(file_diff.hunks) == 2

    first = file_diff.hunks[0]
    assert first.old_start == 1
    assert first.new_start == 1
    assert first.old_count == 3
    assert first.new_count == 4

    deleted = [line for line in first.lines if line.kind == LineKind.DELETE]
    added = [line for line in first.lines if line.kind == LineKind.ADD]
    assert deleted[0].old_lineno == 2
    assert deleted[0].new_lineno is None
    assert added[0].new_lineno == 2
    assert added[0].old_lineno is None
    assert added[1].new_lineno == 3

    second = file_diff.hunks[1]
    assert second.old_start == 20
    assert second.new_start == 21
    assert second.old_count == 1
    assert second.new_count == 4
    assert second.section_heading == "def unused():"


def test_old_and_new_line_mapping_in_simple_unified_diff() -> None:
    parsed = parse_unified_diff(SIMPLE_UNIFIED)
    file_diff = parsed.files[0]
    hunk = file_diff.hunks[0]
    by_content = {line.content: line for line in hunk.lines}

    assert by_content["alpha"].kind == LineKind.CONTEXT
    assert by_content["alpha"].old_lineno == 1
    assert by_content["alpha"].new_lineno == 1

    assert by_content["beta"].kind == LineKind.DELETE
    assert by_content["beta"].old_lineno == 2
    assert by_content["beta"].new_lineno is None

    assert by_content["beta!"].kind == LineKind.ADD
    assert by_content["beta!"].old_lineno is None
    assert by_content["beta!"].new_lineno == 2

    assert by_content["gamma"].old_lineno == 3
    assert by_content["gamma"].new_lineno == 3
    assert by_content["delta"].new_lineno == 4


def test_parse_added_file() -> None:
    parsed = parse_unified_diff(ADDED_FILE)
    file_diff = parsed.files[0]
    assert file_diff.status == FileStatus.ADDED
    assert file_diff.old_path == "/dev/null"
    assert file_diff.new_path == "new.py"
    assert file_diff.hunks[0].old_count == 0
    assert file_diff.hunks[0].new_count == 2
    assert all(line.kind == LineKind.ADD for line in file_diff.hunks[0].lines)


def test_parse_deleted_file() -> None:
    parsed = parse_unified_diff(DELETED_FILE)
    file_diff = parsed.files[0]
    assert file_diff.status == FileStatus.DELETED
    assert file_diff.new_path == "/dev/null"
    assert file_diff.old_path == "gone.py"
    assert all(line.kind == LineKind.DELETE for line in file_diff.hunks[0].lines)
    assert not is_inline_commentable(file_diff, 1)


def test_parse_renamed_file() -> None:
    parsed = parse_unified_diff(RENAMED_FILE)
    file_diff = parsed.files[0]
    assert file_diff.status == FileStatus.RENAMED
    assert file_diff.old_path == "old_name.py"
    assert file_diff.new_path == "new_name.py"
    assert file_diff.similarity_index == 90
    assert file_diff.path == "new_name.py"


def test_parse_binary_file() -> None:
    parsed = parse_unified_diff(BINARY_FILE)
    file_diff = parsed.files[0]
    assert file_diff.status == FileStatus.BINARY
    assert file_diff.is_binary is True
    assert file_diff.hunks == []
    assert not is_inline_commentable(file_diff, 1)


def test_parse_empty_added_file_without_hunks() -> None:
    parsed = parse_unified_diff(EMPTY_ADDED_FILE)
    file_diff = parsed.files[0]
    assert file_diff.status == FileStatus.ADDED
    assert file_diff.path == "empty.txt"
    assert file_diff.hunks == []


def test_inline_commentable_only_for_new_side_lines() -> None:
    parsed = parse_unified_diff(SIMPLE_UNIFIED)
    file_diff = parsed.files[0]

    assert is_inline_commentable(file_diff, 1)  # context
    assert is_inline_commentable(file_diff, 2)  # added beta!
    assert is_inline_commentable(file_diff, 3)  # context gamma
    assert is_inline_commentable(file_diff, 4)  # added delta
    assert not is_inline_commentable(file_diff, 99)
    assert not is_inline_commentable(file_diff, 0)


def test_parse_multiple_files_in_one_diff() -> None:
    combined = ADDED_FILE + DELETED_FILE + BINARY_FILE
    parsed = parse_unified_diff(combined)
    assert parsed.file_count == 3
    assert [f.status for f in parsed.files] == [
        FileStatus.ADDED,
        FileStatus.DELETED,
        FileStatus.BINARY,
    ]


def test_parse_unified_diff_path(tmp_path: Path) -> None:
    diff_path = tmp_path / "changes.diff"
    diff_path.write_text(ADDED_FILE, encoding="utf-8")
    parsed = parse_unified_diff_path(diff_path)
    assert parsed.files[0].status == FileStatus.ADDED


def test_no_newline_marker_is_ignored() -> None:
    text = """\
diff --git a/x.txt b/x.txt
--- a/x.txt
+++ b/x.txt
@@ -1 +1 @@
-hello
\\ No newline at end of file
+hello!
\\ No newline at end of file
"""
    parsed = parse_unified_diff(text)
    hunk = parsed.files[0].hunks[0]
    assert [line.content for line in hunk.lines] == ["hello", "hello!"]
    assert hunk.lines[0].old_lineno == 1
    assert hunk.lines[1].new_lineno == 1
