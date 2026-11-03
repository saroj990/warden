"""Strict schemas for review findings and reports."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Category(StrEnum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    DATA_INTEGRITY = "data_integrity"
    RELIABILITY = "reliability"
    PERFORMANCE = "performance"
    TESTING = "testing"


class LocationKind(StrEnum):
    INLINE = "inline"
    FILE = "file"


class Evidence(BaseModel):
    file: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    excerpt: str = Field(min_length=1)

    @model_validator(mode="after")
    def end_line_not_before_start(self) -> Evidence:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class Finding(BaseModel):
    fingerprint: str = Field(min_length=1)
    severity: Severity
    category: Category
    file: str = Field(min_length=1)
    line: int | None = None
    title: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    suggestion: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    location_kind: LocationKind = LocationKind.INLINE

    @model_validator(mode="after")
    def inline_requires_line(self) -> Finding:
        if self.location_kind == LocationKind.INLINE and self.line is None:
            raise ValueError("inline findings require a line number")
        if self.line is not None and self.line < 1:
            raise ValueError("line must be >= 1 when set")
        return self


class CheckResult(BaseModel):
    name: str
    status: str
    summary: str = ""
    command: list[str] = Field(default_factory=list)


class ReviewReport(BaseModel):
    schema_version: str = "1.0"
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def parse_review_report(data: dict[str, Any] | str) -> ReviewReport:
    """Parse and validate a review report from a dict or JSON string."""
    if isinstance(data, str):
        payload: Any = json.loads(data)
    else:
        payload = data
    return ReviewReport.model_validate(payload)


def parse_finding(data: dict[str, Any] | str) -> Finding:
    if isinstance(data, str):
        payload: Any = json.loads(data)
    else:
        payload = data
    return Finding.model_validate(payload)


def compute_fingerprint(
    *,
    file: str,
    line: int | None,
    category: Category | str,
    title: str,
    problem: str,
) -> str:
    """Stable content-derived fingerprint for deduplication."""
    payload = {
        "file": file,
        "line": line,
        "category": str(category),
        "title": title.strip().lower(),
        "problem": problem.strip().lower(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def finding_with_fingerprint(data: dict[str, Any]) -> Finding:
    """Build a Finding, filling fingerprint from content when omitted."""
    payload = dict(data)
    if not payload.get("fingerprint"):
        payload["fingerprint"] = compute_fingerprint(
            file=str(payload.get("file", "")),
            line=payload.get("line"),
            category=str(payload.get("category", "")),
            title=str(payload.get("title", "")),
            problem=str(payload.get("problem", "")),
        )
    return Finding.model_validate(payload)


# Keep validator import surface tidy for callers that only need enums.
__all__ = [
    "Category",
    "CheckResult",
    "Evidence",
    "Finding",
    "LocationKind",
    "ReviewReport",
    "Severity",
    "compute_fingerprint",
    "finding_with_fingerprint",
    "parse_finding",
    "parse_review_report",
]
