"""Unit tests for the labeled evaluation harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from pr_review.eval import load_cases, score_case
from pr_review.eval.cases import EvalError
from pr_review.eval.runner import run_evaluation
from pr_review.models import ReviewReport, ReviewScope, finding_with_fingerprint
from tests.unit.test_orchestrator import ScriptedProvider, _document, _finding_payload

FIXTURES = Path(__file__).parents[1] / "fixtures" / "eval"


def _report(*payloads: dict) -> ReviewReport:
    return ReviewReport(
        summary="Checked",
        findings=[finding_with_fingerprint(payload) for payload in payloads],
        scope=ReviewScope(diff_source="eval", comparison="eval"),
    )


def test_loads_builtin_cases_in_stable_order() -> None:
    cases = load_cases(FIXTURES)
    assert [case.id for case in cases] == [
        "none-deref",
        "prompt-injection",
        "rename-local",
    ]
    assert cases[0].kind == "defect"
    assert cases[1].kind == "suppress"
    assert cases[2].kind == "clean"


def test_missing_suite_raises(tmp_path: Path) -> None:
    with pytest.raises(EvalError, match="not found"):
        load_cases(tmp_path / "missing")


def test_defect_case_passes_when_file_category_and_line_match() -> None:
    case = load_cases(FIXTURES)[0]
    score = score_case(case, _report(_finding_payload()))
    assert score.passed
    assert score.matched == 1
    assert score.missed == []


def test_defect_case_records_a_miss() -> None:
    case = load_cases(FIXTURES)[0]
    score = score_case(case, _report())
    assert not score.passed
    assert "src/example.py:2 (correctness)" in score.missed


def test_extra_finding_does_not_fail_a_caught_defect() -> None:
    case = load_cases(FIXTURES)[0]
    extra = _finding_payload(
        line=3,
        title="Second issue",
        problem="another problem",
    )
    score = score_case(case, _report(_finding_payload(), extra))
    assert score.passed
    assert score.unexpected


def test_clean_case_fails_when_a_finding_is_published() -> None:
    cases = {case.id: case for case in load_cases(FIXTURES)}
    payload = _finding_payload(
        file="src/labels.py",
        line=2,
        title="Renamed local",
        problem="heading replaced label",
    )
    score = score_case(cases["rename-local"], _report(payload))
    assert not score.passed
    assert score.unexpected


def test_runner_scores_a_correct_reviewer() -> None:
    cases = load_cases(FIXTURES)
    provider = ScriptedProvider(
        [
            _document([_finding_payload()]),
            _document(),
            _document(),
        ]
    )
    report = run_evaluation(
        cases,
        provider,
        model="test-model",
        timeout_seconds=5,
    )
    assert report.passed
    assert report.count("defect", only_passed=True) == 1
    assert report.count("clean", only_passed=True) == 1
    assert report.count("suppress", only_passed=True) == 1
    assert "for reasoning only" not in provider.prompts[0]


def test_runner_records_unreadable_model_output() -> None:
    cases = load_cases(FIXTURES)
    provider = ScriptedProvider(["not json", "still not json"])
    report = run_evaluation(
        [cases[0]],
        provider,
        model="test-model",
        timeout_seconds=5,
    )
    assert not report.passed
    assert report.cases[0].notes
    assert "JSON" in report.cases[0].notes[0]
