"""Machine-readable review reports."""

from __future__ import annotations

import json

from pr_review.models import ReviewReport


def render_json(report: ReviewReport) -> str:
    payload = report.model_dump(mode="json")
    return json.dumps(payload, indent=2) + "\n"
