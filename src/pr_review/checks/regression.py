"""Heuristic regression checks on parsed diffs (high precision, narrow rules)."""

from __future__ import annotations

import re
from typing import Any

from pr_review.git.diff import FileDiff, Hunk, LineKind, ParsedDiff

_PERCENT_SCALE_RE = re.compile(
    r"/\s*100|percent\s*/\s*100|\(\s*percent\s*/\s*100",
    re.IGNORECASE,
)
_PERCENT_UNSCALED_RE = re.compile(
    r"\(\s*1\s*-\s*percent\s*\)|\(\s*1\s*-\s*pct\s*\)",
    re.IGNORECASE,
)
_SHELL_TRUE_RE = re.compile(r"shell\s*=\s*True")
_HARDCODED_SECRET_RE = re.compile(
    r"(WEBHOOK_TOKEN|API_KEY|SECRET_TOKEN|PASSWORD)\s*=\s*[\"'][^\"']+[\"']",
    re.IGNORECASE,
)
_RAW_CENTS_DISPLAY_RE = re.compile(
    r'return\s+f["\']\$\{?\s*\w+\s*\}?["\']',
    re.IGNORECASE,
)
_SCALED_MONEY_RE = re.compile(r"/\s*100|\.2f", re.IGNORECASE)


def regression_finding_payloads(parsed: ParsedDiff) -> list[dict[str, Any]]:
    """Return raw finding dicts suitable for ``finding_with_fingerprint``."""
    findings: list[dict[str, Any]] = []
    for file_diff in parsed.files:
        path = file_diff.path
        if not path:
            continue
        for hunk in file_diff.hunks:
            findings.extend(_check_hunk(path, hunk))
    return findings


def _check_hunk(path: str, hunk: Hunk) -> list[dict[str, Any]]:
    deleted_text = "\n".join(
        line.content for line in hunk.lines if line.kind == LineKind.DELETE
    )
    added = [
        line
        for line in hunk.lines
        if line.kind == LineKind.ADD and line.new_lineno is not None
    ]
    results: list[dict[str, Any]] = []

    if _PERCENT_SCALE_RE.search(deleted_text):
        for line in added:
            if _PERCENT_UNSCALED_RE.search(line.content):
                results.append(
                    _payload(
                        path=path,
                        line=line.new_lineno,
                        title="Percent discount scaling regression",
                        problem=(
                            "Removed code scaled percent by 100 but new code "
                            "uses (1 - percent) without dividing percent by 100."
                        ),
                        scenario=(
                            "Caller passes percent=20 meaning 20%; new formula "
                            "treats 20 as a fractional multiplier instead of 20%."
                        ),
                        excerpt=line.content,
                        category="correctness",
                        severity="high",
                    )
                )
                break

    if _SCALED_MONEY_RE.search(deleted_text):
        for line in added:
            if _RAW_CENTS_DISPLAY_RE.search(line.content) and "/ 100" not in line.content:
                results.append(
                    _payload(
                        path=path,
                        line=line.new_lineno,
                        title="Money display unit regression",
                        problem=(
                            "Removed code divided minor units before display; "
                            "new code prints raw minor units as whole dollars."
                        ),
                        scenario=(
                            "199 cents is shown as $199 instead of $1.99."
                        ),
                        excerpt=line.content,
                        category="correctness",
                        severity="medium",
                    )
                )
                break

    for line in added:
        if line.new_lineno is None:
            continue
        if _SHELL_TRUE_RE.search(line.content):
            results.append(
                _payload(
                    path=path,
                    line=line.new_lineno,
                    title="subprocess with shell=True",
                    problem="shell=True allows shell metacharacter injection.",
                    scenario="Untrusted input in the command string runs arbitrary shell commands.",
                    excerpt=line.content,
                    category="security",
                    severity="high",
                )
            )
        if _HARDCODED_SECRET_RE.search(line.content):
            results.append(
                _payload(
                    path=path,
                    line=line.new_lineno,
                    title="Hardcoded secret in source",
                    problem="Sensitive credential is embedded in source code.",
                    scenario="Source leak exposes the credential to anyone with repo access.",
                    excerpt=line.content,
                    category="security",
                    severity="high",
                )
            )

    path_escape_removed = "escapes repository" in deleted_text or ".resolve()" in deleted_text
    for line in added:
        if line.new_lineno is None:
            continue
        if path_escape_removed and "read_text" in line.content and "resolve()" not in line.content:
            results.append(
                _payload(
                    path=path,
                    line=line.new_lineno,
                    title="Path escape check removed",
                    problem="File read no longer validates that user_path stays under repo_root.",
                    scenario=(
                        "user_path ../../../etc/passwd resolves outside the repo."
                    ),
                    excerpt=line.content,
                    category="security",
                    severity="high",
                )
            )
            break

    return results


def _payload(
    *,
    path: str,
    line: int | None,
    title: str,
    problem: str,
    scenario: str,
    excerpt: str,
    category: str,
    severity: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": category,
        "file": path,
        "line": line,
        "location_kind": "inline",
        "title": title,
        "problem": problem,
        "scenario": scenario,
        "evidence": [
            {
                "file": path,
                "start_line": line,
                "end_line": line,
                "excerpt": excerpt,
            }
        ],
        "suggestion": "Restore the prior invariant or add equivalent validation.",
        "confidence": 0.85,
    }