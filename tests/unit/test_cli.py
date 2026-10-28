"""Unit tests for the CLI scaffold."""

from __future__ import annotations

import pytest

from pr_review import __version__
from pr_review.cli import build_parser, main


def test_package_version_is_semver_like() -> None:
    assert __version__
    parts = __version__.split(".")
    assert len(parts) >= 2
    assert all(part.isdigit() for part in parts[:2])


def test_build_parser_accepts_doctor() -> None:
    parser = build_parser()
    args = parser.parse_args(["doctor"])
    assert args.command == "doctor"


def test_main_doctor_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["doctor"])
    captured = capsys.readouterr()
    assert code == 0
    assert "pr-review" in captured.out
    assert __version__ in captured.out


def test_main_without_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])
    captured = capsys.readouterr()
    assert code == 0
    assert "usage:" in captured.out.lower() or "pr-review" in captured.out
