"""Load bounded repository context around changed hunks."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from pr_review.git.diff import FileDiff, FileStatus
from pr_review.models import ContextInspection
from pr_review.review.filters import path_is_excluded


class GatheredContext(BaseModel):
    inspected: list[ContextInspection] = Field(default_factory=list)
    prompt_text: str = ""
    notes: list[str] = Field(default_factory=list)


def gather_surrounding_context(
    *,
    repo_root: str | Path,
    file_diffs: list[FileDiff],
    exclude_globs: list[str],
    surrounding_lines: int,
    max_bytes: int,
) -> GatheredContext:
    """Read expanded line ranges around each file's changed new-file lines."""
    root = Path(repo_root).expanduser().resolve()
    inspected: list[ContextInspection] = []
    notes: list[str] = []
    blocks: list[str] = []
    budget = max_bytes

    for file_diff in file_diffs:
        path = file_diff.path
        if not path:
            notes.append("Skipped a changed file with no path.")
            continue
        if file_diff.is_binary or file_diff.status == FileStatus.BINARY:
            notes.append(f"Skipped binary file for context: {path}")
            continue
        if file_diff.status == FileStatus.DELETED:
            notes.append(f"Skipped deleted file for context: {path}")
            continue
        if path_is_excluded(path, exclude_globs):
            notes.append(f"Excluded path from context: {path}")
            continue

        ranges = _expanded_ranges(file_diff, surrounding_lines)
        if not ranges:
            notes.append(f"No new-file line ranges for context: {path}")
            continue

        absolute = root / path
        if not absolute.is_file():
            notes.append(f"Context file not on disk: {path}")
            continue

        try:
            lines = absolute.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            notes.append(f"Could not read {path} for context: {exc}")
            continue

        for start, end in ranges:
            block = _render_block(path, lines, start, end)
            size = len(block.encode("utf-8"))
            if size > budget:
                notes.append(
                    f"Stopped context gathering at {path}:{start}-{end} "
                    f"(would exceed max_context_bytes)"
                )
                return GatheredContext(
                    inspected=inspected,
                    prompt_text="\n\n".join(blocks),
                    notes=notes,
                )
            budget -= size
            blocks.append(block)
            inspected.append(
                ContextInspection(
                    path=path,
                    start_line=start,
                    end_line=end,
                    reason="surrounding lines for changed hunks",
                )
            )

    return GatheredContext(
        inspected=inspected,
        prompt_text="\n\n".join(blocks),
        notes=notes,
    )


def _expanded_ranges(
    file_diff: FileDiff,
    surrounding_lines: int,
) -> list[tuple[int, int]]:
    raw: list[tuple[int, int]] = []
    for hunk in file_diff.hunks:
        new_lines = [
            line.new_lineno
            for line in hunk.lines
            if line.new_lineno is not None
        ]
        if not new_lines:
            continue
        start = max(1, min(new_lines) - surrounding_lines)
        end = max(new_lines) + surrounding_lines
        raw.append((start, end))
    return _merge_ranges(raw)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged: list[tuple[int, int]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _render_block(path: str, lines: list[str], start: int, end: int) -> str:
    clamped_end = min(end, len(lines))
    if start > len(lines):
        body = "(no lines in this range)"
    else:
        body_lines = [
            f"{index}| {lines[index - 1]}"
            for index in range(start, clamped_end + 1)
        ]
        body = "\n".join(body_lines) if body_lines else "(empty range)"
    return (
        f"--- repository context: {path} (lines {start}-{clamped_end}) ---\n"
        f"{body}"
    )
