"""Unit tests for the CLI scaffold."""

from __future__ import annotations

from pathlib import Path

import pytest

from pr_review import __version__
from pr_review.cli import build_parser, main
from pr_review.models import parse_review_report
from pr_review.providers.base import ProviderConnectionError
from tests.unit.test_orchestrator import (
    SAMPLE_DIFF,
    ScriptedProvider,
    _document,
    _finding_payload,
)


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
    assert "warden" in captured.out
    assert __version__ in captured.out
    assert "local review pipeline" in captured.out


def test_main_without_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])
    captured = capsys.readouterr()
    assert code == 0
    assert "usage:" in captured.out.lower() or "warden" in captured.out


def test_review_diff_writes_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    diff_path = tmp_path / "changes.diff"
    diff_path.write_text(SAMPLE_DIFF, encoding="utf-8")
    output_path = tmp_path / "review.json"
    monkeypatch.setattr(
        "pr_review.cli.build_provider",
        lambda _settings: ScriptedProvider([_document([_finding_payload()])]),
    )

    code = main(
        [
            "review",
            "--diff",
            str(diff_path),
            "--model",
            "test-model",
            "--format",
            "json",
            "--output",
            str(output_path),
            "--fail-on",
            "critical",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    report = parse_review_report(output_path.read_text(encoding="utf-8"))
    assert report.findings[0].title == "Possible None dereference"
    assert report.scope is not None
    assert report.scope.model == "test-model"


def test_review_fail_on_high_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    diff_path = tmp_path / "changes.diff"
    diff_path.write_text(SAMPLE_DIFF, encoding="utf-8")
    monkeypatch.setattr(
        "pr_review.cli.build_provider",
        lambda _settings: ScriptedProvider([_document([_finding_payload()])]),
    )

    code = main(
        [
            "review",
            "--diff",
            str(diff_path),
            "--model",
            "test-model",
            "--format",
            "json",
            "--fail-on",
            "high",
        ]
    )

    assert code == 1
    report = parse_review_report(capsys.readouterr().out)
    assert len(report.findings) == 1


def test_review_provider_failure_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    diff_path = tmp_path / "changes.diff"
    diff_path.write_text(SAMPLE_DIFF, encoding="utf-8")

    class FailingProvider(ScriptedProvider):
        def chat(self, messages, *, model, timeout_seconds=None):
            raise ProviderConnectionError("Ollama is down")

    monkeypatch.setattr(
        "pr_review.cli.build_provider",
        lambda _settings: FailingProvider([]),
    )
    code = main(["review", "--diff", str(diff_path), "--model", "test-model"])
    captured = capsys.readouterr()
    assert code == 1
    assert "Ollama is down" in captured.err
    assert captured.out == ""


def test_review_requires_a_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    diff_path = tmp_path / "changes.diff"
    diff_path.write_text(SAMPLE_DIFF, encoding="utf-8")
    code = main(["review", "--diff", str(diff_path)])
    captured = capsys.readouterr()
    assert code == 2
    assert "model is required" in captured.err


def test_review_rejects_unimplemented_provider(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    diff_path = tmp_path / "changes.diff"
    diff_path.write_text(SAMPLE_DIFF, encoding="utf-8")
    code = main(
        [
            "review",
            "--diff",
            str(diff_path),
            "--model",
            "test-model",
            "--provider",
            "openai_compatible",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "not implemented" in captured.err


def test_review_refuses_diff_combined_with_base(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    diff_path = tmp_path / "changes.diff"
    diff_path.write_text(SAMPLE_DIFF, encoding="utf-8")
    code = main(
        [
            "review",
            "--diff",
            str(diff_path),
            "--base",
            "main",
            "--model",
            "test-model",
        ]
    )
    assert code == 2
    assert "--diff" in capsys.readouterr().err


def test_eval_passes_when_labels_match(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "pr_review.cli.build_provider",
        lambda _settings: ScriptedProvider(
            [
                _document([_finding_payload()]),
                _document(),
                _document(),
            ]
        ),
    )
    code = main(["eval", "--model", "test-model"])
    captured = capsys.readouterr()
    assert code == 0
    assert "Defects caught: 1/1" in captured.out
    assert "Result: passed" in captured.out


def test_eval_exits_one_when_a_defect_is_missed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "pr_review.cli.build_provider",
        lambda _settings: ScriptedProvider(
            [_document(), _document(), _document()]
        ),
    )
    code = main(["eval", "--model", "test-model"])
    captured = capsys.readouterr()
    assert code == 1
    assert "Defects caught: 0/1" in captured.out
    assert "none-deref" in captured.out


def test_eval_missing_cases_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["eval", "--model", "test-model", "--cases", "missing-eval-dir"])
    captured = capsys.readouterr()
    assert code == 2
    assert "not found" in captured.err


def test_github_review_defaults_to_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from pr_review.integrations.review_pr import GitHubReviewResult

    seen: dict[str, object] = {}

    def fake_run(**kwargs: object) -> GitHubReviewResult:
        seen.update(kwargs)
        return GitHubReviewResult(
            repository="acme/app",
            pull_number=7,
            commit_id="abc123",
            html_url="https://github.com/acme/app/pull/7",
            mode="dry-run",
            posted=False,
            post=True,
            summary="Checked the pull request",
        )

    monkeypatch.setenv("GITHUB_TOKEN", "cli-token-value")
    monkeypatch.setattr("pr_review.cli.run_github_review", fake_run)
    monkeypatch.setattr(
        "pr_review.cli.build_provider",
        lambda _settings: ScriptedProvider([]),
    )
    code = main(
        [
            "github",
            "review",
            "--repository",
            "acme/app",
            "--pr",
            "7",
            "--model",
            "test-model",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert seen["publish"] is False
    assert "Mode: dry-run" in captured.out
    assert "cli-token-value" not in captured.out
    assert "cli-token-value" not in captured.err


def test_github_review_requires_a_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    code = main(
        [
            "github",
            "review",
            "--repository",
            "acme/app",
            "--pr",
            "7",
            "--model",
            "test-model",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "GITHUB_TOKEN" in captured.err


def test_github_review_rejects_publish_and_dry_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "github",
            "review",
            "--repository",
            "acme/app",
            "--pr",
            "7",
            "--model",
            "test-model",
            "--publish",
            "--dry-run",
        ]
    )
    assert code == 2
    assert "--publish" in capsys.readouterr().err


def test_github_without_subcommand_exits_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["github"])
    assert code == 2
    assert "subcommand" in capsys.readouterr().err


def test_review_help_lists_diff_flag(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["review", "--help"])
    assert exc.value.code == 0
    assert "--diff" in capsys.readouterr().out
