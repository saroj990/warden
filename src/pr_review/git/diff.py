"""Unified diff parsing with old/new line mapping."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<section>.*)$"
)
_GIT_HEADER_RE = re.compile(r"^diff --git a/(?P<a_path>.+) b/(?P<b_path>.+)$")
_RENAME_FROM_RE = re.compile(r"^rename from (?P<path>.+)$")
_RENAME_TO_RE = re.compile(r"^rename to (?P<path>.+)$")
_COPY_FROM_RE = re.compile(r"^copy from (?P<path>.+)$")
_COPY_TO_RE = re.compile(r"^copy to (?P<path>.+)$")
_SIMILARITY_RE = re.compile(r"^similarity index (?P<pct>\d+)%$")
_INDEX_RE = re.compile(r"^index (?P<old>[0-9a-f]+)\.\.(?P<new>[0-9a-f]+)")
_BINARY_RE = re.compile(
    r"^Binary files (?P<old>.+) and (?P<new>.+) differ$"
)
_MODE_NEW_RE = re.compile(r"^new file mode (?P<mode>\d+)$")
_MODE_DELETED_RE = re.compile(r"^deleted file mode (?P<mode>\d+)$")


class LineKind(StrEnum):
    CONTEXT = "context"
    ADD = "add"
    DELETE = "delete"


class FileStatus(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    BINARY = "binary"


class DiffLine(BaseModel):
    kind: LineKind
    content: str
    old_lineno: int | None = None
    new_lineno: int | None = None


class Hunk(BaseModel):
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section_heading: str = ""
    lines: list[DiffLine] = Field(default_factory=list)


class FileDiff(BaseModel):
    old_path: str | None = None
    new_path: str | None = None
    status: FileStatus = FileStatus.MODIFIED
    is_binary: bool = False
    similarity_index: int | None = None
    old_mode: str | None = None
    new_mode: str | None = None
    hunks: list[Hunk] = Field(default_factory=list)

    @property
    def path(self) -> str | None:
        """Best path to refer to this change (prefer the new path)."""
        if self.new_path and self.new_path != "/dev/null":
            return self.new_path
        if self.old_path and self.old_path != "/dev/null":
            return self.old_path
        return None


class ParsedDiff(BaseModel):
    files: list[FileDiff] = Field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)


def is_inline_commentable(file_diff: FileDiff, new_lineno: int) -> bool:
    """Return True if ``new_lineno`` is a valid inline-comment location.

    Deleted lines and binary files are never commentable. Only added or
    context lines in the new file version are eligible.
    """
    if file_diff.is_binary or file_diff.status == FileStatus.BINARY:
        return False
    if file_diff.status == FileStatus.DELETED:
        return False
    if new_lineno < 1:
        return False

    for hunk in file_diff.hunks:
        for line in hunk.lines:
            if line.new_lineno == new_lineno and line.kind in {
                LineKind.ADD,
                LineKind.CONTEXT,
            }:
                return True
    return False


def parse_unified_diff_path(path: str | Path) -> ParsedDiff:
    return parse_unified_diff(Path(path).read_text(encoding="utf-8"))


def parse_unified_diff(text: str) -> ParsedDiff:
    """Parse a unified diff (including ``git diff`` output) into structured data."""
    lines = text.splitlines()
    files: list[FileDiff] = []
    current: FileDiff | None = None
    i = 0

    def finalize_status(file_diff: FileDiff) -> None:
        if file_diff.is_binary:
            file_diff.status = FileStatus.BINARY
            return
        if file_diff.status in {
            FileStatus.RENAMED,
            FileStatus.COPIED,
            FileStatus.ADDED,
            FileStatus.DELETED,
        }:
            # Keep explicit status from git headers unless path markers contradict.
            if file_diff.old_path == "/dev/null":
                file_diff.status = FileStatus.ADDED
            elif file_diff.new_path == "/dev/null":
                file_diff.status = FileStatus.DELETED
            return
        if file_diff.old_path == "/dev/null":
            file_diff.status = FileStatus.ADDED
            return
        if file_diff.new_path == "/dev/null":
            file_diff.status = FileStatus.DELETED
            return
        file_diff.status = FileStatus.MODIFIED

    while i < len(lines):
        line = lines[i]

        git_match = _GIT_HEADER_RE.match(line)
        if git_match:
            if current is not None:
                finalize_status(current)
            current = FileDiff(
                old_path=git_match.group("a_path"),
                new_path=git_match.group("b_path"),
            )
            files.append(current)
            i += 1
            continue

        if current is None and (
            line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@ ")
        ):
            current = FileDiff()
            files.append(current)

        if current is None:
            i += 1
            continue

        mode_new = _MODE_NEW_RE.match(line)
        if mode_new:
            current.new_mode = mode_new.group("mode")
            current.status = FileStatus.ADDED
            i += 1
            continue

        mode_deleted = _MODE_DELETED_RE.match(line)
        if mode_deleted:
            current.old_mode = mode_deleted.group("mode")
            current.status = FileStatus.DELETED
            i += 1
            continue

        similarity = _SIMILARITY_RE.match(line)
        if similarity:
            current.similarity_index = int(similarity.group("pct"))
            i += 1
            continue

        rename_from = _RENAME_FROM_RE.match(line)
        if rename_from:
            current.old_path = rename_from.group("path")
            current.status = FileStatus.RENAMED
            i += 1
            continue

        rename_to = _RENAME_TO_RE.match(line)
        if rename_to:
            current.new_path = rename_to.group("path")
            current.status = FileStatus.RENAMED
            i += 1
            continue

        copy_from = _COPY_FROM_RE.match(line)
        if copy_from:
            current.old_path = copy_from.group("path")
            current.status = FileStatus.COPIED
            i += 1
            continue

        copy_to = _COPY_TO_RE.match(line)
        if copy_to:
            current.new_path = copy_to.group("path")
            current.status = FileStatus.COPIED
            i += 1
            continue

        if _INDEX_RE.match(line):
            i += 1
            continue

        if line.startswith("old mode "):
            current.old_mode = line.removeprefix("old mode ").strip()
            i += 1
            continue

        if line.startswith("new mode "):
            current.new_mode = line.removeprefix("new mode ").strip()
            i += 1
            continue

        binary = _BINARY_RE.match(line)
        if binary or line.startswith("GIT binary patch"):
            current.is_binary = True
            current.status = FileStatus.BINARY
            if binary:
                current.old_path = _strip_diff_path(binary.group("old"))
                current.new_path = _strip_diff_path(binary.group("new"))
            i += 1
            continue

        if line.startswith("--- "):
            current.old_path = _strip_diff_path(line[4:])
            i += 1
            continue

        if line.startswith("+++ "):
            current.new_path = _strip_diff_path(line[4:])
            i += 1
            continue

        hunk_match = _HUNK_HEADER_RE.match(line)
        if hunk_match:
            hunk, consumed = _parse_hunk(lines, i)
            current.hunks.append(hunk)
            i = consumed
            continue

        # Ignore unknown metadata lines inside a file section.
        i += 1

    if current is not None:
        finalize_status(current)

    return ParsedDiff(files=files)


def _strip_diff_path(raw: str) -> str:
    path = raw.strip()
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    # Timestamps after a tab are common in non-git unified diffs.
    if "\t" in path:
        path = path.split("\t", 1)[0]
    return path


def _parse_hunk(lines: list[str], header_index: int) -> tuple[Hunk, int]:
    header_line = lines[header_index]
    match = _HUNK_HEADER_RE.match(header_line)
    if not match:
        raise ValueError(f"Invalid hunk header: {header_line!r}")

    old_start = int(match.group("old_start"))
    old_count_raw = match.group("old_count")
    old_count = int(old_count_raw) if old_count_raw is not None else 1
    new_start = int(match.group("new_start"))
    new_count_raw = match.group("new_count")
    new_count = int(new_count_raw) if new_count_raw is not None else 1
    section = match.group("section").strip()

    hunk = Hunk(
        old_start=old_start,
        old_count=old_count,
        new_start=new_start,
        new_count=new_count,
        section_heading=section,
    )

    old_lineno = old_start
    new_lineno = new_start
    # Counts of 0 mean the side does not advance (pure add/delete).
    old_remaining = old_count
    new_remaining = new_count
    i = header_index + 1

    while i < len(lines):
        line = lines[i]
        if (
            line.startswith("diff --git ")
            or line.startswith("--- ")
            or line.startswith("+++ ")
            or line.startswith("@@ ")
        ):
            break
        # No-newline marker is metadata, not a content line.
        if line.startswith("\\"):
            i += 1
            continue
        if not line and old_remaining <= 0 and new_remaining <= 0:
            break

        if not line.startswith((" ", "+", "-")):
            # End of hunk content (or unexpected); stop without consuming.
            break

        prefix = line[0]
        content = line[1:]

        if prefix == " ":
            hunk.lines.append(
                DiffLine(
                    kind=LineKind.CONTEXT,
                    content=content,
                    old_lineno=old_lineno,
                    new_lineno=new_lineno,
                )
            )
            old_lineno += 1
            new_lineno += 1
            old_remaining -= 1
            new_remaining -= 1
        elif prefix == "-":
            hunk.lines.append(
                DiffLine(
                    kind=LineKind.DELETE,
                    content=content,
                    old_lineno=old_lineno,
                    new_lineno=None,
                )
            )
            old_lineno += 1
            old_remaining -= 1
        elif prefix == "+":
            hunk.lines.append(
                DiffLine(
                    kind=LineKind.ADD,
                    content=content,
                    old_lineno=None,
                    new_lineno=new_lineno,
                )
            )
            new_lineno += 1
            new_remaining -= 1

        i += 1
        if old_remaining <= 0 and new_remaining <= 0:
            # Consume optional "\ No newline at end of file" after completing counts.
            if i < len(lines) and lines[i].startswith("\\"):
                i += 1
            break

    return hunk, i
