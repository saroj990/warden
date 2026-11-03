"""Deterministic validation of review findings against a parsed diff."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field

from pr_review.git.diff import FileDiff, ParsedDiff, is_inline_commentable
from pr_review.models import Finding, LocationKind


class RejectedFinding(BaseModel):
    finding: Finding
    reasons: list[str] = Field(min_length=1)


class ValidationResult(BaseModel):
    accepted: list[Finding] = Field(default_factory=list)
    rejected: list[RejectedFinding] = Field(default_factory=list)


def validate_findings(
    findings: list[Finding],
    parsed_diff: ParsedDiff,
    *,
    repo_root: str | Path | None = None,
) -> ValidationResult:
    """Validate findings; duplicates (by fingerprint) are rejected after the first."""
    accepted: list[Finding] = []
    rejected: list[RejectedFinding] = []
    seen_fingerprints: set[str] = set()

    for finding in findings:
        if finding.fingerprint in seen_fingerprints:
            rejected.append(
                RejectedFinding(
                    finding=finding,
                    reasons=[f"duplicate fingerprint: {finding.fingerprint}"],
                )
            )
            continue

        reasons = _validation_reasons(finding, parsed_diff, repo_root=repo_root)
        if reasons:
            rejected.append(RejectedFinding(finding=finding, reasons=reasons))
            continue

        seen_fingerprints.add(finding.fingerprint)
        accepted.append(finding)

    return ValidationResult(accepted=accepted, rejected=rejected)


def validate_finding(
    finding: Finding,
    parsed_diff: ParsedDiff,
    *,
    repo_root: str | Path | None = None,
) -> list[str]:
    """Return rejection reasons for a single finding (empty means accepted)."""
    return _validation_reasons(finding, parsed_diff, repo_root=repo_root)


def _validation_reasons(
    finding: Finding,
    parsed_diff: ParsedDiff,
    *,
    repo_root: str | Path | None,
) -> list[str]:
    reasons: list[str] = []

    if _path_escapes_repo(finding.file, repo_root=repo_root):
        reasons.append(f"file path escapes repository root: {finding.file}")

    for evidence in finding.evidence:
        if _path_escapes_repo(evidence.file, repo_root=repo_root):
            reasons.append(
                f"evidence path escapes repository root: {evidence.file}"
            )
        if not evidence.excerpt.strip():
            reasons.append("evidence excerpt is empty")

    if not finding.problem.strip():
        reasons.append("problem is empty")
    if not finding.scenario.strip():
        reasons.append("scenario is empty")
    if not finding.suggestion.strip():
        reasons.append("suggestion is empty")

    file_diff = _find_file_diff(parsed_diff, finding.file)
    if file_diff is None:
        reasons.append(f"file not present in diff: {finding.file}")
        return reasons

    if finding.location_kind == LocationKind.INLINE:
        if finding.line is None:
            reasons.append("inline finding is missing line")
        elif not is_inline_commentable(file_diff, finding.line):
            reasons.append(
                f"line {finding.line} is not an inline-commentable location "
                f"in {finding.file}"
            )
    # File-level findings are allowed without a line; they must not be
    # published as inline comments by reporters (enforced later).

    return reasons


def _find_file_diff(parsed_diff: ParsedDiff, path: str) -> FileDiff | None:
    normalized = _normalize_rel_path(path)
    for file_diff in parsed_diff.files:
        candidates = {
            _normalize_rel_path(p)
            for p in (file_diff.path, file_diff.old_path, file_diff.new_path)
            if p and p != "/dev/null"
        }
        if normalized in candidates:
            return file_diff
    return None


def _normalize_rel_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _path_escapes_repo(path: str, *, repo_root: str | Path | None) -> bool:
    normalized = _normalize_rel_path(path)
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        return True

    if repo_root is None:
        return False

    root = Path(repo_root).resolve()
    try:
        (root / normalized).resolve().relative_to(root)
    except ValueError:
        return True
    return False
