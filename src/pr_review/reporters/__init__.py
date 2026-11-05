"""Report renderers."""

from pr_review.models import ReviewReport
from pr_review.reporters.json_report import render_json
from pr_review.reporters.markdown import render_markdown

_SEVERITY_RANK = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def render_report(report: ReviewReport, report_format: str) -> str:
    if report_format == "json":
        return render_json(report)
    if report_format == "markdown":
        return render_markdown(report)
    raise ValueError(f"unsupported report format: {report_format}")


def exceeds_fail_threshold(report: ReviewReport, threshold: str) -> bool:
    """Return True when a published finding is at or above ``threshold``."""
    if threshold not in _SEVERITY_RANK:
        raise ValueError(f"unsupported severity threshold: {threshold}")
    minimum = _SEVERITY_RANK[threshold]
    if minimum == 0:
        return False
    return any(
        _SEVERITY_RANK[finding.severity.value] >= minimum
        for finding in report.findings
    )


__all__ = [
    "exceeds_fail_threshold",
    "render_json",
    "render_markdown",
    "render_report",
]
