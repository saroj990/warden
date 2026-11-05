"""Read-only Git commands used to select a review diff."""

from __future__ import annotations

import subprocess
from pathlib import Path

_GIT_TIMEOUT_SECONDS = 30


class GitCommandError(Exception):
    """A read-only git command failed or timed out."""


def collect_diff(
    *,
    repo: str | Path,
    base: str,
    head: str | None = None,
) -> tuple[str, str]:
    """Return ``(diff_text, comparison_label)`` without changing the work tree.

    With ``head``, the comparison is ``base...head`` (merge base to head).
    Without ``head``, the comparison is the working tree, including staged
    and unstaged changes, against ``base``. Untracked files are not included.
    """
    if not base.strip():
        raise GitCommandError("base revision is required")

    root = Path(repo).expanduser().resolve()
    if not root.is_dir():
        raise GitCommandError(f"repository path is not a directory: {root}")

    inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"], check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise GitCommandError(f"not a git work tree: {root}")

    toplevel = _run_git(root, ["rev-parse", "--show-toplevel"])
    if Path(toplevel.stdout.strip()).resolve() != root:
        raise GitCommandError(
            f"repository path is not the git work tree root: {root}"
        )

    if head is not None and head.strip():
        comparison = f"{base}...{head}"
        label = f"{base}...{head} (merge base to head)"
    else:
        comparison = base
        label = f"working tree vs {base}"

    diff = _run_git(
        root,
        [
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--unified=3",
            comparison,
        ],
    )
    return diff.stdout, label


def _run_git(
    repo: Path,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(repo), *args]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitCommandError("git command timed out") from exc
    except OSError as exc:
        raise GitCommandError(f"could not run git: {exc}") from exc

    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip()
        raise GitCommandError(detail[:500])
    return result
