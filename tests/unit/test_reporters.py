"""Unit tests for Markdown and JSON reports."""

from __future__ import annotations

from pr_review.models import ReviewScope, SkippedFile, parse_review_report
from pr_review.reporters import exceeds_fail_threshold, render_report
from pr_review.review import run_review
from tests.unit.test_orchestrator import (
    SAMPLE_DIFF,
    ScriptedProvider,
    _document,
    _finding_payload,
    _options,
)


def _report():
    provider = ScriptedProvider([_document([_finding_payload()], summary="One defect")])
    return run_review(SAMPLE_DIFF, provider, _options())


def test_markdown_includes_finding_and_scope() -> None:
    rendered = render_report(_report(), "markdown")
    assert "# Review report" in rendered
    assert "[high] Possible None dereference" in rendered
    assert "`src/example.py:2`" in rendered
    assert "When key x is missing" in rendered
    assert "value = cfg.get('x')" in rendered
    assert "Provider: scripted" in rendered
    assert "Model: test-model" in rendered
    assert "No deterministic checks were run." in rendered
    assert "heuristic only" in rendered


def test_clean_report_does_not_claim_the_change_is_defect_free() -> None:
    provider = ScriptedProvider([_document()])
    report = run_review(SAMPLE_DIFF, provider, _options())
    rendered = render_report(report, "markdown")

    assert report.summary == "No actionable findings identified."
    assert "No actionable findings identified." in rendered
    assert "defect-free" not in rendered
    assert "free of defects" in rendered


def test_json_report_round_trips_through_the_schema() -> None:
    report = _report()
    rendered = render_report(report, "json")
    parsed = parse_review_report(rendered)
    assert parsed.schema_version == "1.0"
    assert parsed.findings[0].fingerprint == report.findings[0].fingerprint
    assert parsed.scope is not None
    assert parsed.scope.files == ["src/example.py"]


def test_fail_threshold_uses_published_findings_only() -> None:
    report = _report()
    assert exceeds_fail_threshold(report, "high") is True
    assert exceeds_fail_threshold(report, "critical") is False
    assert exceeds_fail_threshold(report, "none") is False

    clean = run_review(SAMPLE_DIFF, ScriptedProvider([_document()]), _options())
    assert exceeds_fail_threshold(clean, "low") is False


def test_markdown_lists_skipped_files() -> None:
    report = _report()
    assert report.scope is not None
    report.scope = ReviewScope(
        diff_source=report.scope.diff_source,
        comparison=report.scope.comparison,
        provider=report.scope.provider,
        model=report.scope.model,
        files=report.scope.files,
        skipped=[SkippedFile(path="notes.bin", reason="binary file")],
    )
    rendered = render_report(report, "markdown")
    assert "`notes.bin`: binary file" in rendered
