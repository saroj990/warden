"""Review pipeline components."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pr_review.review.validator import (
    RejectedFinding,
    ValidationResult,
    validate_finding,
    validate_findings,
)

if TYPE_CHECKING:
    from pr_review.review.orchestrator import (
        ReviewOptions,
        ReviewOutputError,
        run_review,
    )

__all__ = [
    "RejectedFinding",
    "ReviewOptions",
    "ReviewOutputError",
    "ValidationResult",
    "run_review",
    "validate_finding",
    "validate_findings",
]


def __getattr__(name: str):
    if name in {"ReviewOptions", "ReviewOutputError", "run_review"}:
        from pr_review.review.orchestrator import (
            ReviewOptions,
            ReviewOutputError,
            run_review,
        )

        exports = {
            "ReviewOptions": ReviewOptions,
            "ReviewOutputError": ReviewOutputError,
            "run_review": run_review,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
