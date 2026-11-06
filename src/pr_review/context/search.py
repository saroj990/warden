"""Find definitions and callers for symbols introduced in a diff."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pr_review.context.loader import GatheredContext
from pr_review.git.diff import FileDiff, FileStatus, LineKind
from pr_review.models import ContextInspection
from pr_review.review.filters import path_is_excluded

_MAX_SYMBOLS = 8
_MAX_MATCHES = 5
_GIT_TIMEOUT_SECONDS = 30
_DEF_RE = re.compile(
    r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b"
)
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_SKIP_NAMES = frozenset(
    {
        "all",
        "any",
        "append",
        "bool",
        "bytes",
        "classmethod",
        "dict",
        "enumerate",
        "filter",
        "float",
        "format",
        "get",
        "int",
        "isinstance",
        "items",
        "join",
        "keys",
        "len",
        "list",
        "map",
        "max",
        "min",
        "object",
        "open",
        "pop",
        "print",
        "property",
        "range",
        "replace",
        "set",
        "sorted",
        "split",
        "staticmethod",
        "str",
        "strip",
        "sum",
        "super",
        "tuple",
        "type",
        "update",
        "values",
        "zip",
    }
)


def gather_symbol_context(
    *,
    repo_root: str | Path,
    file_diffs: list[FileDiff],
    exclude_globs: list[str],
    max_bytes: int,
) -> GatheredContext:
    """Search the work tree for definitions and callers of added symbols."""
    root = Path(repo_root).expanduser().resolve()
    symbols = _added_symbols(file_diffs, exclude_globs)
    if not symbols:
        return GatheredContext()

    if not _is_work_tree(root):
        return GatheredContext(
            notes=["Symbol search skipped: not a git work tree."],
        )

    inspected: list[ContextInspection] = []
    notes: list[str] = []
    blocks: list[str] = []
    budget = max_bytes
    noted_exclusions: set[str] = set()

    for name, origin in symbols:
        lines, error = _git_grep(root, _word_pattern(name))
        if error:
            notes.append(f"Symbol search for {name} failed: {error}")
            continue

        matches: list[tuple[str, int, str]] = []
        for raw in lines:
            parsed = _parse_grep_line(raw)
            if parsed is None:
                continue
            path, line_no, text = parsed
            if path == origin:
                continue
            if path_is_excluded(path, exclude_globs):
                if path not in noted_exclusions:
                    notes.append(f"Excluded path from symbol search: {path}")
                    noted_exclusions.add(path)
                continue
            matches.append((path, line_no, text))
            if len(matches) >= _MAX_MATCHES:
                break

        if not matches:
            continue

        block = _render_symbol(name, matches)
        size = len(block.encode("utf-8"))
        if size > budget:
            notes.append(
                f"Stopped symbol search at {name} (would exceed max_context_bytes)"
            )
            break
        budget -= size
        blocks.append(block)
        for path, line_no, _text in matches:
            inspected.append(
                ContextInspection(
                    path=path,
                    start_line=line_no,
                    end_line=line_no,
                    reason=f"symbol search for {name}",
                )
            )

    return GatheredContext(
        inspected=inspected,
        prompt_text="\n\n".join(blocks),
        notes=notes,
    )


def _added_symbols(
    file_diffs: list[FileDiff],
    exclude_globs: list[str],
) -> list[tuple[str, str]]:
    definitions: list[tuple[str, str]] = []
    calls: list[tuple[str, str]] = []
    for file_diff in file_diffs:
        path = file_diff.path
        if not path:
            continue
        if file_diff.is_binary or file_diff.status in {
            FileStatus.BINARY,
            FileStatus.DELETED,
        }:
            continue
        if path_is_excluded(path, exclude_globs):
            continue
        for hunk in file_diff.hunks:
            for line in hunk.lines:
                if line.kind != LineKind.ADD:
                    continue
                defined = _DEF_RE.match(line.content)
                if defined and _keep_symbol(defined.group(1)):
                    definitions.append((defined.group(1), path))
                for name in _CALL_RE.findall(line.content):
                    if _keep_symbol(name):
                        calls.append((name, path))

    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, origin in [*definitions, *calls]:
        if name in seen:
            continue
        seen.add(name)
        ordered.append((name, origin))
        if len(ordered) >= _MAX_SYMBOLS:
            break
    return ordered


def _keep_symbol(name: str) -> bool:
    return len(name) >= 3 and name not in _SKIP_NAMES and not name.startswith("_")


def _word_pattern(name: str) -> str:
    return rf"(^|[^A-Za-z0-9_]){re.escape(name)}([^A-Za-z0-9_]|$)"


def _is_work_tree(root: Path) -> bool:
    if not root.is_dir():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_grep(root: Path, pattern: str) -> tuple[list[str], str | None]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "grep",
                "-n",
                "-I",
                "-E",
                "-e",
                pattern,
                "--",
                ".",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return [], "git grep timed out"
    except OSError as exc:
        return [], f"could not run git grep: {exc}"
    if result.returncode == 1:
        return [], None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git grep failed").strip()
        return [], detail[:300]
    return [line for line in result.stdout.splitlines() if line], None


def _parse_grep_line(raw: str) -> tuple[str, int, str] | None:
    path, separator, rest = raw.partition(":")
    if not separator or not path:
        return None
    line_text, separator, content = rest.partition(":")
    if not separator or not line_text.isdigit():
        return None
    line_no = int(line_text)
    if line_no < 1:
        return None
    return path, line_no, content.strip()


def _render_symbol(name: str, matches: list[tuple[str, int, str]]) -> str:
    rows = [
        f"{path}:{line_no}: {text[:200]}" for path, line_no, text in matches
    ]
    return (
        f"--- symbol context: {name} (definitions and callers outside the diff) ---\n"
        + "\n".join(rows)
    )
