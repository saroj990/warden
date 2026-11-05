"""Unit tests for exclude globs."""

from __future__ import annotations

import pytest

from pr_review.config import DEFAULT_EXCLUDE_GLOBS
from pr_review.review.filters import path_is_excluded

_EXCLUDED = [
    ".env",
    ".env.local",
    ".env.example",
    "certs/server.pem",
    "secrets/key",
    "pkg/secrets/token.txt",
    "node_modules/left-pad/index.js",
    ".git/config",
    "src/.git/objects/ab",
]


@pytest.mark.parametrize("path", _EXCLUDED)
def test_default_globs_exclude_sensitive_paths(path: str) -> None:
    assert path_is_excluded(path, DEFAULT_EXCLUDE_GLOBS)


@pytest.mark.parametrize("path", ["src/app.py", "README.md", "tests/unit/test_cli.py"])
def test_default_globs_keep_source_paths(path: str) -> None:
    assert not path_is_excluded(path, DEFAULT_EXCLUDE_GLOBS)
