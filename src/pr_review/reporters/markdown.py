"""Human-readable review reports."""

from __future__ import annotations

from pr_review.models import Finding, ReviewReport

_NO_CHECKS = "No deterministic checks were run."


def render_markdown(report: ReviewReport) -> str:
    lines: list[str] = ["# Review report", ""]
    lines.append(report.summary.strip() or "No actionable findings identified.")
    lines.append("")
    lines.extend(_scope_section(report))
    lines.extend(["## Checks", "", _NO_CHECKS, ""])
    lines.extend(_findings_section(report.findings))
    lines.extend(_limitations_section(report.limitations))
    return "\n".join(lines).rstrip() + "\n"


def _scope_section(report: ReviewReport) -> list[str]:
    scope = report.scope
    if scope is None:
        return []
    lines = ["## Scope", ""]
    lines.append(f"- Source: {scope.diff_source}")
    lines.append(f"- Comparison: {scope.comparison}")
    if scope.provider or scope.model:
        provider = scope.provider or "unspecified"
        model = scope.model or "unspecified"
        lines.append(f"- Provider: {provider}")
        lines.append(f"- Model: {model}")
    if scope.files:
        listed = ", ".join(f"`{path}`" for path in scope.files)
        lines.append(f"- Files reviewed: {listed}")
    else:
        lines.append("- Files reviewed: none")
    if scope.skipped:
        lines.append("- Files skipped:")
        for skipped in scope.skipped:
            lines.append(f"  - `{skipped.path}`: {skipped.reason}")
    if scope.context_inspected:
        lines.append("- Repository context inspected:")
        for item in scope.context_inspected:
            lines.append(
                f"  - `{item.path}` lines {item.start_line}-{item.end_line}: "
                f"{item.reason}"
            )
    lines.append("")
    return lines


def _findings_section(findings: list[Finding]) -> list[str]:
    lines = ["## Findings", ""]
    if not findings:
        lines.extend(
            [
                "No actionable findings identified.",
                "",
                "This does not mean the change is free of defects.",
                "",
            ]
        )
        return lines

    for index, finding in enumerate(findings, start=1):
        location = f"`{finding.file}`"
        if finding.line is not None:
            location = f"`{finding.file}:{finding.line}`"
        lines.append(f"### {index}. [{finding.severity.value}] {finding.title}")
        lines.append("")
        lines.append(f"- Location: {location} ({finding.location_kind.value})")
        lines.append(f"- Category: {finding.category.value}")
        lines.append(f"- Confidence: {finding.confidence:.2f} (heuristic only)")
        lines.append("")
        lines.append(f"**Problem.** {finding.problem}")
        lines.append("")
        lines.append(f"**Scenario.** {finding.scenario}")
        lines.append("")
        lines.append("**Evidence.**")
        lines.append("")
        for evidence in finding.evidence:
            lines.append(
                f"- `{evidence.file}:{evidence.start_line}-{evidence.end_line}`"
            )
            lines.append("")
            lines.append("```")
            lines.append(_cap_excerpt(evidence.excerpt))
            lines.append("```")
            lines.append("")
        lines.append(f"**Suggestion.** {finding.suggestion}")
        lines.append("")
    return lines


def _limitations_section(limitations: list[str]) -> list[str]:
    lines = ["## Limitations", ""]
    if not limitations:
        lines.extend(["None recorded.", ""])
        return lines
    for item in limitations:
        lines.append(f"- {item}")
    lines.append("")
    return lines


def _cap_excerpt(excerpt: str) -> str:
    rows = excerpt.splitlines()
    if len(rows) <= 40:
        return excerpt
    return "\n".join(rows[:40] + ["... excerpt truncated ..."])
