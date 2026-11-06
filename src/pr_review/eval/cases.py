"""Load labeled evaluation cases from a directory of fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from pr_review.models import Category

CaseKind = Literal["defect", "clean", "suppress"]


class EvalError(Exception):
    """The evaluation suite could not be loaded."""


class ExpectedHit(BaseModel):
    """A finding the reviewer should publish for a defect case."""

    file: str = Field(min_length=1)
    category: Category
    line: int | None = Field(default=None, ge=1)


class EvalCase(BaseModel):
    """One labeled diff and the review result it should produce."""

    id: str = Field(min_length=1)
    kind: CaseKind
    summary: str = Field(min_length=1)
    diff: str = Field(min_length=1)
    expect: list[ExpectedHit] = Field(default_factory=list)

    @model_validator(mode="after")
    def expectations_match_kind(self) -> EvalCase:
        if self.kind == "defect" and not self.expect:
            raise ValueError("defect cases need at least one expected finding")
        if self.kind != "defect" and self.expect:
            raise ValueError("only defect cases can list expected findings")
        return self


def load_cases(root: str | Path) -> list[EvalCase]:
    """Load ``*/case.json`` plus ``diff.patch`` from ``root``."""
    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise EvalError(f"evaluation directory not found: {directory}")

    loaded: list[EvalCase] = []
    for case_path in sorted(directory.glob("*/case.json")):
        folder = case_path.parent
        diff_path = folder / "diff.patch"
        if not diff_path.is_file():
            raise EvalError(f"missing diff.patch in {folder}")
        try:
            meta = json.loads(case_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise EvalError(f"invalid case file {case_path}: {exc}") from exc
        if not isinstance(meta, dict):
            raise EvalError(f"invalid case file {case_path}: expected an object")
        meta["diff"] = diff_path.read_text(encoding="utf-8")
        try:
            case = EvalCase.model_validate(meta)
        except ValidationError as exc:
            raise EvalError(f"invalid case file {case_path}: {exc}") from exc
        if case.id != folder.name:
            raise EvalError(
                f"case id {case.id!r} does not match directory {folder.name!r}"
            )
        loaded.append(case)

    if not loaded:
        raise EvalError(f"no evaluation cases found in {directory}")
    return loaded
