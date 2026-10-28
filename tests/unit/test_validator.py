"""Unit tests for finding validation against parsed diffs."""

from __future__ import annotations

from pr_review.git import parse_unified_diff
from pr_review.models import Finding, LocationKind, finding_with_fingerprint
from pr_review.review import validate_finding, validate_findings

SAMPLE_DIFF = """\
diff --git a/src/example.py b/src/example.py
index 1111111..2222222 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1,3 +1,4 @@
 def run(cfg):
-    return cfg['x'].strip()
+    value = cfg.get('x')
+    return value.strip()
     return None
"""


def _finding(**overrides: object) -> Finding:
    data: dict = {
        "fingerprint": "fp-1",
        "severity": "high",
        "category": "correctness",
        "file": "src/example.py",
        "line": 2,
        "title": "Possible None dereference",
        "problem": "cfg.get('x') may return None",
        "scenario": "When key x is missing, strip() raises AttributeError",
        "evidence": [
            {
                "file": "src/example.py",
                "start_line": 2,
                "end_line": 3,
                "excerpt": "value = cfg.get('x')\nreturn value.strip()",
            }
        ],
        "suggestion": "Check for None before calling strip()",
        "confidence": 0.9,
        "location_kind": "inline",
    }
    data.update(overrides)
    return Finding.model_validate(data)


def test_accepts_valid_inline_finding() -> None:
    parsed = parse_unified_diff(SAMPLE_DIFF)
    result = validate_findings([_finding(line=2)], parsed)
    assert len(result.accepted) == 1
    assert result.rejected == []


def test_rejects_non_commentable_line() -> None:
    parsed = parse_unified_diff(SAMPLE_DIFF)
    reasons = validate_finding(_finding(line=99), parsed)
    assert any("not an inline-commentable location" in r for r in reasons)


def test_rejects_unknown_file() -> None:
    parsed = parse_unified_diff(SAMPLE_DIFF)
    reasons = validate_finding(_finding(file="src/missing.py"), parsed)
    assert any("not present in diff" in r for r in reasons)


def test_rejects_path_escape() -> None:
    parsed = parse_unified_diff(SAMPLE_DIFF)
    reasons = validate_finding(_finding(file="../outside.py"), parsed)
    assert any("escapes repository root" in r for r in reasons)


def test_rejects_duplicate_fingerprints() -> None:
    parsed = parse_unified_diff(SAMPLE_DIFF)
    first = _finding(fingerprint="same")
    second = _finding(fingerprint="same", title="Other title")
    result = validate_findings([first, second], parsed)
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert "duplicate fingerprint" in result.rejected[0].reasons[0]


def test_file_level_finding_does_not_require_line() -> None:
    parsed = parse_unified_diff(SAMPLE_DIFF)
    finding = _finding(line=None, location_kind=LocationKind.FILE)
    result = validate_findings([finding], parsed)
    assert len(result.accepted) == 1


def test_rejects_empty_scenario_even_if_schema_bypassed_via_spaces() -> None:
    # Schema requires min_length=1; validator also strips whitespace.
    parsed = parse_unified_diff(SAMPLE_DIFF)
    finding = _finding(scenario="   ")
    reasons = validate_finding(finding, parsed)
    assert any("scenario is empty" in r for r in reasons)


def test_accepts_finding_built_with_auto_fingerprint() -> None:
    parsed = parse_unified_diff(SAMPLE_DIFF)
    finding = finding_with_fingerprint(
        {
            "severity": "medium",
            "category": "reliability",
            "file": "src/example.py",
            "line": 3,
            "title": "Unchecked optional",
            "problem": "value may be None",
            "scenario": "missing key",
            "evidence": [
                {
                    "file": "src/example.py",
                    "start_line": 2,
                    "end_line": 3,
                    "excerpt": "return value.strip()",
                }
            ],
            "suggestion": "Add a guard",
            "location_kind": "inline",
        }
    )
    result = validate_findings([finding], parsed)
    assert len(result.accepted) == 1
