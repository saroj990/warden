"""Run one local review pass per diff chunk and validate the results."""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from pr_review.config import DEFAULT_EXCLUDE_GLOBS, ConfigError
from pr_review.git.diff import parse_unified_diff
from pr_review.models import (
    Finding,
    ReviewReport,
    ReviewScope,
    finding_with_fingerprint,
)
from pr_review.providers.base import ChatMessage, ChatRole, LLMProvider
from pr_review.review.chunking import prepare_diff
from pr_review.review.parse_output import ModelOutputError, parse_model_document
from pr_review.review.prompts import build_messages
from pr_review.review.validator import validate_findings

_NO_FINDINGS = "No actionable findings identified."
_DIFF_ONLY = (
    "Only the diff was sent to the model. Other repository files were not read."
)
_UNTRACKED = "Untracked files are not included in a git diff."
_SUMMARY_LIMIT = 1000
_RETRY_ECHO_LIMIT = 2000


class ReviewOptions(BaseModel):
    model: str
    provider_name: str = "ollama"
    comparison: str
    diff_source: str
    max_diff_bytes: int = Field(default=200_000, ge=1)
    max_files: int = Field(default=0, ge=0)
    parse_retries: int = Field(default=1, ge=0)
    timeout_seconds: float | None = Field(default=None, gt=0)
    exclude_globs: list[str] = Field(
        default_factory=lambda: list(DEFAULT_EXCLUDE_GLOBS)
    )
    repo_root: str | None = None
    include_untracked_limitation: bool = False


class ReviewOutputError(Exception):
    """The model did not return readable findings after the allowed retries."""


def run_review(
    diff_text: str,
    provider: LLMProvider,
    options: ReviewOptions,
) -> ReviewReport:
    """Review ``diff_text`` and return a schema-valid report.

    Provider transport errors propagate to the caller. A chunk that is still
    unreadable after retries raises ``ReviewOutputError``.
    """
    if not options.model.strip():
        raise ConfigError(
            "model is required (pass --model or set OLLAMA_MODEL)"
        )

    parsed = parse_unified_diff(diff_text)
    prepared = prepare_diff(
        parsed,
        max_diff_bytes=options.max_diff_bytes,
        max_files=options.max_files,
        exclude_globs=options.exclude_globs,
    )

    limitations = [_DIFF_ONLY]
    if options.include_untracked_limitation:
        limitations.append(_UNTRACKED)
    for skipped in prepared.skipped:
        limitations.append(f"Skipped {skipped.path}: {skipped.reason}")

    summaries: list[str] = []
    candidates: list[Finding] = []

    if not prepared.chunks:
        limitations.append("No reviewable textual changes were sent to the model.")
    else:
        for index, chunk in enumerate(prepared.chunks, start=1):
            document = _review_chunk(
                provider,
                options,
                chunk_text=chunk.text,
                chunk_index=index,
                chunk_count=len(prepared.chunks),
            )
            if document.summary:
                summaries.append(document.summary)
            if document.skipped_non_objects:
                limitations.append(
                    f"Chunk {index}: skipped "
                    f"{document.skipped_non_objects} non-object findings"
                )
            if document.truncated_findings:
                limitations.append(
                    f"Chunk {index}: ignored {document.truncated_findings} "
                    "findings beyond the per-chunk cap"
                )
            for raw_index, raw in enumerate(document.findings, start=1):
                try:
                    candidates.append(finding_with_fingerprint(raw))
                except ValidationError as exc:
                    message = exc.errors()[0]["msg"]
                    limitations.append(
                        f"Chunk {index}: skipped finding {raw_index}: {message}"
                    )

    validation = validate_findings(
        candidates,
        prepared.parsed,
        repo_root=options.repo_root,
    )
    for rejected in validation.rejected:
        title = rejected.finding.title.strip() or "(untitled)"
        reasons = "; ".join(rejected.reasons)
        limitations.append(f'Rejected "{title}": {reasons}')

    if validation.accepted:
        summary = " ".join(summaries).strip()
        if not summary:
            count = len(validation.accepted)
            summary = f"Review identified {count} findings."
        summary = summary[:_SUMMARY_LIMIT]
    else:
        summary = _NO_FINDINGS

    scope = ReviewScope(
        diff_source=options.diff_source,
        comparison=options.comparison,
        provider=options.provider_name,
        model=options.model,
        files=[file_diff.path or "(unknown)" for file_diff in prepared.parsed.files],
        skipped=prepared.skipped,
    )
    return ReviewReport(
        summary=summary,
        findings=validation.accepted,
        checks=[],
        limitations=limitations,
        scope=scope,
    )


def _review_chunk(
    provider: LLMProvider,
    options: ReviewOptions,
    *,
    chunk_text: str,
    chunk_index: int,
    chunk_count: int,
):
    messages = build_messages(
        comparison=options.comparison,
        chunk_text=chunk_text,
    )
    attempts = options.parse_retries + 1
    last_error = "model response was empty"
    for attempt in range(attempts):
        response = provider.chat(
            messages,
            model=options.model,
            timeout_seconds=options.timeout_seconds,
        )
        try:
            return parse_model_document(response.content)
        except ModelOutputError as exc:
            last_error = str(exc)
            if attempt + 1 >= attempts:
                break
            echo = response.content.strip()[:_RETRY_ECHO_LIMIT] or "(empty)"
            messages = [
                *messages,
                ChatMessage(role=ChatRole.ASSISTANT, content=echo),
                ChatMessage(
                    role=ChatRole.USER,
                    content=(
                        "That response was not valid review JSON "
                        f"({last_error}). Return only the JSON object."
                    ),
                ),
            ]

    raise ReviewOutputError(
        f"Chunk {chunk_index} of {chunk_count} was not valid JSON "
        f"after {attempts} attempts: {last_error}"
    )
