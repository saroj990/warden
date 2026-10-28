"""Unit tests for finding/report schemas."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pr_review.models import (
    Category,
    Finding,
    LocationKind,
    Severity,
    compute_fingerprint,
    finding_with_fingerprint,
    parse_finding,
    parse_review_report,
)


def _valid_finding_dict(**overrides: object) -> dict:
    data: dict = {
        "fingerprint": "abc123",
        "severity": "high",
        "category": "correctness",
        "file": "src/example.py",
        "line": 10,
        "title": "Null check missing",
        "problem": "value may be None before use",
        "scenario": "call with missing config key",
        "evidence": [
            {
                "file": "src/example.py",
                "start_line": 8,
                "end_line": 12,
                "excerpt": "value = cfg.get('x')\nreturn value.strip()",
            }
        ],
        "suggestion": "Guard against None before calling strip()",
        "confidence": 0.8,
        "location_kind": "inline",
    }
    data.update(overrides)
    return data


def test_parse_valid_finding() -> None:
    finding = parse_finding(_valid_finding_dict())
    assert finding.severity == Severity.HIGH
    assert finding.category == Category.CORRECTNESS
    assert finding.location_kind == LocationKind.INLINE
    assert finding.line == 10
    assert len(finding.evidence) == 1


def test_parse_review_report_from_json_string() -> None:
    payload = {
        "schema_version": "1.0",
        "summary": "One issue found",
        "findings": [_valid_finding_dict()],
        "checks": [],
        "limitations": ["No tests were executed"],
    }
    report = parse_review_report(json.dumps(payload))
    assert report.summary == "One issue found"
    assert len(report.findings) == 1
    assert report.limitations == ["No tests were executed"]


def test_inline_finding_requires_line() -> None:
    with pytest.raises(ValidationError):
        parse_finding(_valid_finding_dict(line=None))


def test_file_level_finding_allows_missing_line() -> None:
    finding = parse_finding(
        _valid_finding_dict(line=None, location_kind="file")
    )
    assert finding.location_kind == LocationKind.FILE
    assert finding.line is None


def test_evidence_requires_excerpt_and_ordered_lines() -> None:
    with pytest.raises(ValidationError):
        parse_finding(
            _valid_finding_dict(
                evidence=[
                    {
                        "file": "src/example.py",
                        "start_line": 10,
                        "end_line": 8,
                        "excerpt": "x",
                    }
                ]
            )
        )
    with pytest.raises(ValidationError):
        parse_finding(
            _valid_finding_dict(
                evidence=[
                    {
                        "file": "src/example.py",
                        "start_line": 1,
                        "end_line": 1,
                        "excerpt": "",
                    }
                ]
            )
        )


def test_invalid_severity_and_category_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_finding(_valid_finding_dict(severity="urgent"))
    with pytest.raises(ValidationError):
        parse_finding(_valid_finding_dict(category="style"))


def test_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        parse_finding(_valid_finding_dict(confidence=1.5))
    with pytest.raises(ValidationError):
        parse_finding(_valid_finding_dict(confidence=-0.1))


def test_compute_fingerprint_is_stable() -> None:
    a = compute_fingerprint(
        file="a.py",
        line=1,
        category=Category.SECURITY,
        title="Auth missing",
        problem="No check",
    )
    b = compute_fingerprint(
        file="a.py",
        line=1,
        category="security",
        title="Auth missing",
        problem="No check",
    )
    c = compute_fingerprint(
        file="a.py",
        line=2,
        category=Category.SECURITY,
        title="Auth missing",
        problem="No check",
    )
    assert a == b
    assert a != c
    assert len(a) == 16


def test_finding_with_fingerprint_fills_missing() -> None:
    data = _valid_finding_dict()
    data.pop("fingerprint")
    finding = finding_with_fingerprint(data)
    assert finding.fingerprint
    assert Finding.model_validate(finding.model_dump())
