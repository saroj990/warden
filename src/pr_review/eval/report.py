"""Render an evaluation score as Markdown or JSON."""

from __future__ import annotations

from pr_review.eval.runner import EvalReport
from pr_review.eval.score import CaseScore


def render_eval_report(report: EvalReport, report_format: str) -> str:
    if report_format == "json":
        return report.model_dump_json(indent=2) + "\n"
    if report_format == "markdown":
        return render_eval_markdown(report)
    raise ValueError(f"unsupported report format: {report_format}")


def render_eval_markdown(report: EvalReport) -> str:
    defect_total = report.count("defect")
    clean_total = report.count("clean")
    suppress_total = report.count("suppress")
    lines = [
        "# Evaluation",
        "",
        f"- Provider: {report.provider}",
        f"- Model: {report.model}",
        (
            "- Defects caught: "
            f"{report.count('defect', only_passed=True)}/{defect_total}"
        ),
        (
            "- Clean cases quiet: "
            f"{report.count('clean', only_passed=True)}/{clean_total}"
        ),
        (
            "- Suppressed cases quiet: "
            f"{report.count('suppress', only_passed=True)}/{suppress_total}"
        ),
        f"- Result: {'passed' if report.passed else 'failed'}",
        "",
    ]
    for note in report.notes:
        lines.append(note)
        lines.append("")
    for case in report.cases:
        lines.extend(_case_section(case))
    return "\n".join(lines).rstrip() + "\n"


def _case_section(case: CaseScore) -> list[str]:
    lines = [
        f"## {case.case_id}",
        "",
        case.summary,
        "",
        f"- Kind: {case.kind}",
        f"- Result: {_result_label(case)}",
        f"- Expected matches: {case.matched}/{case.expected}",
        f"- Published findings: {case.published}",
    ]
    for item in case.missed:
        lines.append(f"- Missed: {item}")
    for item in case.unexpected:
        lines.append(f"- Unexpected: {item}")
    for note in case.notes:
        lines.append(f"- Note: {note}")
    lines.append("")
    return lines


def _result_label(case: CaseScore) -> str:
    if case.notes and not case.passed and case.published == 0 and not case.missed:
        return "error"
    if case.kind == "defect":
        return "caught" if case.passed else "missed"
    return "quiet" if case.passed else "flagged"
