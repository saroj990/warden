"""Parse untrusted model output into finding payloads."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_MAX_FINDINGS_PER_CHUNK = 50


class ModelOutputError(Exception):
    """The model response was not a usable review JSON document."""


class ParsedModelOutput(BaseModel):
    summary: str = ""
    findings: list[dict[str, Any]] = Field(default_factory=list)
    skipped_non_objects: int = 0
    truncated_findings: int = 0


def parse_model_document(content: str) -> ParsedModelOutput:
    """Parse a model response.

    Raises ``ModelOutputError`` when the response is not a JSON object with
    a findings array, or a JSON array of findings. Individual finding objects
    are not schema-checked here.
    """
    payload = _load_json(content)
    if isinstance(payload, list):
        summary = ""
        raw_findings = payload
    elif isinstance(payload, dict):
        if "findings" not in payload:
            raise ModelOutputError("JSON object is missing 'findings'")
        summary = _summary(payload.get("summary", ""))
        raw_findings = payload["findings"]
    else:
        raise ModelOutputError("JSON value must be an object or array")

    if not isinstance(raw_findings, list):
        raise ModelOutputError("'findings' must be an array")

    findings = [item for item in raw_findings if isinstance(item, dict)]
    skipped = len(raw_findings) - len(findings)
    truncated = max(0, len(findings) - _MAX_FINDINGS_PER_CHUNK)
    return ParsedModelOutput(
        summary=summary,
        findings=findings[:_MAX_FINDINGS_PER_CHUNK],
        skipped_non_objects=skipped,
        truncated_findings=truncated,
    )


def _summary(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    raise ModelOutputError("'summary' must be a string")


def _load_json(content: str) -> Any:
    text = content.strip()
    if not text:
        raise ModelOutputError("model response was empty")

    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        sliced = _outer_json(text)
        if sliced is None:
            raise ModelOutputError("response did not contain JSON") from None
        try:
            return json.loads(sliced)
        except json.JSONDecodeError as exc:
            raise ModelOutputError("response contained malformed JSON") from exc


def _outer_json(text: str) -> str | None:
    object_span = _span(text, "{", "}")
    array_span = _span(text, "[", "]")
    if object_span is None:
        return array_span
    if array_span is None:
        return object_span
    if text.find("{") <= text.find("["):
        return object_span
    return array_span


def _span(text: str, open_char: str, close_char: str) -> str | None:
    start = text.find(open_char)
    end = text.rfind(close_char)
    if start < 0 or end <= start:
        return None
    return text[start : end + 1]
