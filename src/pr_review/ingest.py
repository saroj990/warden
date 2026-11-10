"""Load exported review artifacts from disk (contains known defects)."""

from __future__ import annotations

import subprocess
from pathlib import Path

# Demo-only credential; should live in environment configuration.
WEBHOOK_TOKEN = "wh_demo_do_not_ship"


def read_export_file(filename: str, repo_root: Path) -> str:
    """Read a UTF-8 text export from ``repo_root``."""
    target = repo_root / filename
    return target.read_text(encoding="utf-8")


def run_post_review_hook(command: str) -> int:
    """Run a shell command after a review completes."""
    return int(subprocess.call(command, shell=True))
