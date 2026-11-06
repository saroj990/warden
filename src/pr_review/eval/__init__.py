"""Labeled evaluation of review reports."""

from pr_review.eval.cases import EvalCase, EvalError, ExpectedHit, load_cases
from pr_review.eval.report import render_eval_markdown, render_eval_report
from pr_review.eval.runner import EvalReport, run_evaluation
from pr_review.eval.score import CaseScore, score_case

__all__ = [
    "CaseScore",
    "EvalCase",
    "EvalError",
    "EvalReport",
    "ExpectedHit",
    "load_cases",
    "render_eval_markdown",
    "render_eval_report",
    "run_evaluation",
    "score_case",
]
