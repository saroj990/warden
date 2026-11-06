"""Run the review pipeline over labeled cases and score the results."""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field

from pr_review.eval.cases import EvalCase
from pr_review.eval.score import CaseScore, score_case
from pr_review.providers.base import LLMProvider
from pr_review.review.orchestrator import ReviewOptions, ReviewOutputError, run_review

_CONTEXT_NOTE = (
    "Results depend on the model and configuration. "
    "Repository context was not loaded for these fixture diffs."
)


class EvalReport(BaseModel):
    """Aggregate score for one evaluation run."""

    provider: str
    model: str
    cases: list[CaseScore] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def passed(self) -> bool:
        return bool(self.cases) and all(case.passed for case in self.cases)

    def count(self, kind: str, *, only_passed: bool = False) -> int:
        return sum(
            1
            for case in self.cases
            if case.kind == kind and (case.passed or not only_passed)
        )


def run_evaluation(
    cases: list[EvalCase],
    provider: LLMProvider,
    *,
    model: str,
    timeout_seconds: float,
) -> EvalReport:
    """Review each fixture diff and score it against its label."""
    scores: list[CaseScore] = []
    for case in cases:
        options = ReviewOptions(
            model=model,
            provider_name=provider.name,
            comparison=f"eval:{case.id}",
            diff_source=case.id,
            timeout_seconds=timeout_seconds,
            context_enabled=False,
            context_symbol_search=False,
        )
        try:
            report = run_review(case.diff, provider, options)
        except ReviewOutputError as exc:
            scores.append(_error_score(case, str(exc)))
            continue
        scores.append(score_case(case, report))

    return EvalReport(
        provider=provider.name,
        model=model,
        cases=scores,
        notes=[_CONTEXT_NOTE],
    )


def _error_score(case: EvalCase, message: str) -> CaseScore:
    return CaseScore(
        case_id=case.id,
        kind=case.kind,
        summary=case.summary,
        passed=False,
        expected=len(case.expect),
        notes=[message],
    )
