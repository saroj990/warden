"""Map a validated review report onto GitHub review comments."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

from pr_review.git.diff import FileDiff, ParsedDiff, is_inline_commentable
from pr_review.models import Finding, LocationKind, ReviewReport

_SUMMARY_PREFIX = "<!-- warden-summary:"
_COMMENT_PREFIX = "<!-- warden:"


class PlannedComment(BaseModel):
    path: str
    line: int = Field(ge=1)
    body: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)


class SkippedComment(BaseModel):
    path: str
    line: int | None = None
    fingerprint: str
    reason: str = Field(min_length=1)


class GitHubReviewPlan(BaseModel):
    """Comments that are safe to send, plus the ones left out."""

    summary: str
    summary_marker: str
    comments: list[PlannedComment] = Field(default_factory=list)
    skipped: list[SkippedComment] = Field(default_factory=list)
    post: bool


def build_review_plan(
    report: ReviewReport,
    parsed: ParsedDiff,
    *,
    existing_comment_bodies: list[str],
    existing_review_bodies: list[str],
) -> GitHubReviewPlan:
    """Turn published findings into a COMMENT review.

    Inline comments are limited to lines the diff can anchor. File-level
    findings stay in the summary. A fingerprint that is already on the pull
    request is not posted again.
    """
    comments: list[PlannedComment] = []
    skipped: list[SkippedComment] = []
    file_findings: list[Finding] = []
    fingerprints = [finding.fingerprint for finding in report.findings]

    for finding in report.findings:
        if finding.location_kind != LocationKind.INLINE or finding.line is None:
            file_findings.append(finding)
            skipped.append(
                SkippedComment(
                    path=finding.file,
                    line=finding.line,
                    fingerprint=finding.fingerprint,
                    reason="file-level finding is included in the summary",
                )
            )
            continue
        file_diff = _file_diff(parsed, finding.file)
        if file_diff is None or not is_inline_commentable(file_diff, finding.line):
            skipped.append(
                SkippedComment(
                    path=finding.file,
                    line=finding.line,
                    fingerprint=finding.fingerprint,
                    reason="line is not commentable on the pull request diff",
                )
            )
            continue
        marker = _comment_marker(finding.fingerprint)
        if any(marker in body for body in existing_comment_bodies):
            skipped.append(
                SkippedComment(
                    path=finding.file,
                    line=finding.line,
                    fingerprint=finding.fingerprint,
                    reason="already posted",
                )
            )
            continue
        comments.append(
            PlannedComment(
                path=finding.file,
                line=finding.line,
                body=_comment_body(finding),
                fingerprint=finding.fingerprint,
            )
        )

    marker = _summary_marker(_digest(fingerprints))
    already_posted = any(marker in body for body in existing_review_bodies)
    return GitHubReviewPlan(
        summary=_summary(report, file_findings, marker),
        summary_marker=marker,
        comments=comments,
        skipped=skipped,
        post=bool(comments) or not already_posted,
    )


def _file_diff(parsed: ParsedDiff, path: str) -> FileDiff | None:
    target = path.strip().replace("\\", "/").removeprefix("./")
    for file_diff in parsed.files:
        if file_diff.path == target:
            return file_diff
    return None


def _digest(fingerprints: list[str]) -> str:
    payload = "\n".join(sorted(fingerprints))
    if not payload:
        return "none"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _summary_marker(digest: str) -> str:
    return f"{_SUMMARY_PREFIX}{digest} -->"


def _comment_marker(fingerprint: str) -> str:
    return f"{_COMMENT_PREFIX}{fingerprint} -->"


def _summary(
    report: ReviewReport,
    file_findings: list[Finding],
    marker: str,
) -> str:
    lines = [report.summary.strip() or "No actionable findings identified.", ""]
    if file_findings:
        lines.append("File-level findings:")
        lines.append("")
        for finding in file_findings:
            lines.append(
                f"- `{finding.file}` [{finding.severity.value}] {finding.title}"
            )
            lines.append("")
            lines.append(finding.problem)
            lines.append("")
    lines.append(marker)
    return "\n".join(lines).rstrip() + "\n"


def _comment_body(finding: Finding) -> str:
    return (
        f"**[{finding.severity.value}] {finding.title}**\n\n"
        f"{finding.problem}\n\n"
        f"{finding.scenario}\n\n"
        f"{finding.suggestion}\n\n"
        f"{_comment_marker(finding.fingerprint)}\n"
    )
