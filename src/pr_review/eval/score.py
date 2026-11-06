"""Score a review report against one labeled evaluation case."""

from __future__ import annotations

from pydantic import BaseModel, Field

from pr_review.eval.cases import EvalCase, ExpectedHit
from pr_review.models import Finding, ReviewReport


class CaseScore(BaseModel):
    """How one case compared with the published findings."""

    case_id: str
    kind: str
    summary: str
    passed: bool
    expected: int = 0
    matched: int = 0
    published: int = 0
    missed: list[str] = Field(default_factory=list)
    unexpected: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def score_case(case: EvalCase, report: ReviewReport) -> CaseScore:
    """Match published findings to the case label.

    A defect case passes when every expected file, category, and line is
    published. A clean or suppress case passes when nothing is published.
    Extra findings on a defect case are recorded and do not fail the case.
    """
    findings = list(report.findings)
    used: set[int] = set()
    missed: list[str] = []
    matched = 0
    for expected in case.expect:
        index = _find_match(findings, used, expected)
        if index is None:
            missed.append(_expected_label(expected))
            continue
        used.add(index)
        matched += 1

    unexpected = [
        _finding_label(finding)
        for index, finding in enumerate(findings)
        if index not in used
    ]
    if case.kind == "defect":
        passed = not missed
    else:
        passed = not findings

    return CaseScore(
        case_id=case.id,
        kind=case.kind,
        summary=case.summary,
        passed=passed,
        expected=len(case.expect),
        matched=matched,
        published=len(findings),
        missed=missed,
        unexpected=unexpected,
    )


def _find_match(
    findings: list[Finding],
    used: set[int],
    expected: ExpectedHit,
) -> int | None:
    for index, finding in enumerate(findings):
        if index in used:
            continue
        if _normalize(finding.file) != _normalize(expected.file):
            continue
        if finding.category != expected.category:
            continue
        if expected.line is not None and finding.line != expected.line:
            continue
        return index
    return None


def _expected_label(expected: ExpectedHit) -> str:
    location = expected.file
    if expected.line is not None:
        location = f"{expected.file}:{expected.line}"
    return f"{location} ({expected.category.value})"


def _finding_label(finding: Finding) -> str:
    location = finding.file
    if finding.line is not None:
        location = f"{finding.file}:{finding.line}"
    return f"{location} [{finding.category.value}] {finding.title}"


def _normalize(path: str) -> str:
    return path.strip().replace("\\", "/").removeprefix("./")
