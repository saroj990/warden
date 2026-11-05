"""Unit tests for parsing model review JSON."""

from __future__ import annotations

import json

import pytest

from pr_review.review.parse_output import ModelOutputError, parse_model_document


def test_parses_fenced_json() -> None:
    payload = {"summary": "ok", "findings": [{"title": "One"}]}
    content = "Here is the review:\n```json\n" + json.dumps(payload) + "\n```\n"
    parsed = parse_model_document(content)
    assert parsed.summary == "ok"
    assert parsed.findings == [{"title": "One"}]


def test_parses_json_wrapped_in_prose() -> None:
    content = 'Notes before {"summary": "x", "findings": []} trailing'
    parsed = parse_model_document(content)
    assert parsed.summary == "x"
    assert parsed.findings == []


def test_parses_bare_finding_array() -> None:
    parsed = parse_model_document('[{"title": "Only"}]')
    assert parsed.summary == ""
    assert parsed.findings == [{"title": "Only"}]


def test_counts_non_objects_and_truncates() -> None:
    findings = [{"title": str(index)} for index in range(55)]
    findings.insert(0, "not-an-object")
    parsed = parse_model_document(json.dumps({"findings": findings}))
    assert parsed.skipped_non_objects == 1
    assert parsed.truncated_findings == 5
    assert len(parsed.findings) == 50


def test_missing_findings_raises() -> None:
    with pytest.raises(ModelOutputError, match="findings"):
        parse_model_document('{"summary": "no list"}')


def test_empty_response_raises() -> None:
    with pytest.raises(ModelOutputError, match="empty"):
        parse_model_document("   ")
