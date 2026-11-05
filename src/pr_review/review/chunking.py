"""Split a parsed diff into bounded prompt chunks.

Files that cannot fit in one chunk are skipped with an explicit reason.
The diff is never cut in the middle of a file.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pr_review.git.diff import FileDiff, FileStatus, LineKind, ParsedDiff
from pr_review.models import SkippedFile
from pr_review.review.filters import path_is_excluded


class DiffChunk(BaseModel):
    paths: list[str] = Field(min_length=1)
    text: str = Field(min_length=1)


class PreparedDiff(BaseModel):
    parsed: ParsedDiff
    chunks: list[DiffChunk] = Field(default_factory=list)
    skipped: list[SkippedFile] = Field(default_factory=list)


def prepare_diff(
    parsed: ParsedDiff,
    *,
    max_diff_bytes: int,
    max_files: int,
    exclude_globs: list[str],
) -> PreparedDiff:
    skipped: list[SkippedFile] = []
    selectable: list[FileDiff] = []

    for file_diff in parsed.files:
        path = file_diff.path or file_diff.new_path or file_diff.old_path or "(unknown)"
        reason = _skip_reason(file_diff, path, exclude_globs)
        if reason is not None:
            skipped.append(SkippedFile(path=path, reason=reason))
            continue
        selectable.append(file_diff)

    if max_files > 0 and len(selectable) > max_files:
        overflow = selectable[max_files:]
        selectable = selectable[:max_files]
        for file_diff in overflow:
            path = file_diff.path or "(unknown)"
            skipped.append(
                SkippedFile(
                    path=path,
                    reason=f"exceeded max_files ({max_files})",
                )
            )

    chunks: list[DiffChunk] = []
    kept: list[FileDiff] = []
    current_files: list[FileDiff] = []
    current_text = ""

    for file_diff in selectable:
        rendered = render_file_diff(file_diff)
        size = len(rendered.encode("utf-8"))
        path = file_diff.path or "(unknown)"
        if size > max_diff_bytes:
            skipped.append(
                SkippedFile(
                    path=path,
                    reason=(
                        f"file diff is {size} bytes, "
                        f"over max_diff_bytes ({max_diff_bytes})"
                    ),
                )
            )
            continue

        combined = current_text + rendered
        if current_files and len(combined.encode("utf-8")) > max_diff_bytes:
            chunks.append(_chunk(current_files, current_text))
            kept.extend(current_files)
            current_files = []
            current_text = ""

        current_files.append(file_diff)
        current_text += rendered

    if current_files:
        chunks.append(_chunk(current_files, current_text))
        kept.extend(current_files)

    return PreparedDiff(
        parsed=ParsedDiff(files=kept),
        chunks=chunks,
        skipped=skipped,
    )


def render_file_diff(file_diff: FileDiff) -> str:
    """Render one file with new-file line numbers on added and context lines."""
    path = file_diff.path or file_diff.new_path or file_diff.old_path or "(unknown)"
    lines = [
        f"file: {path}",
        f"status: {file_diff.status.value}",
    ]
    if (
        file_diff.old_path
        and file_diff.new_path
        and file_diff.old_path != file_diff.new_path
        and file_diff.old_path != "/dev/null"
        and file_diff.new_path != "/dev/null"
    ):
        lines.append(f"old_path: {file_diff.old_path}")
        lines.append(f"new_path: {file_diff.new_path}")

    for hunk in file_diff.hunks:
        lines.append(
            f"@@ -{hunk.old_start},{hunk.old_count} "
            f"+{hunk.new_start},{hunk.new_count} @@"
        )
        for line in hunk.lines:
            if line.kind == LineKind.DELETE:
                number = _format_number(line.old_lineno)
                lines.append(f"-{number}|{line.content}")
            elif line.kind == LineKind.ADD:
                number = _format_number(line.new_lineno)
                lines.append(f"+{number}|{line.content}")
            else:
                number = _format_number(line.new_lineno)
                lines.append(f" {number}|{line.content}")
    return "\n".join(lines) + "\n"


def _skip_reason(
    file_diff: FileDiff,
    path: str,
    exclude_globs: list[str],
) -> str | None:
    if file_diff.is_binary or file_diff.status == FileStatus.BINARY:
        return "binary file"
    if path_is_excluded(path, exclude_globs):
        return "matched an exclude glob"
    if not file_diff.hunks:
        return "no textual hunks"
    return None


def _chunk(files: list[FileDiff], text: str) -> DiffChunk:
    paths = [file_diff.path or "(unknown)" for file_diff in files]
    return DiffChunk(paths=paths, text=text)


def _format_number(number: int | None) -> str:
    if number is None:
        return "     "
    return f"{number:>5}"
