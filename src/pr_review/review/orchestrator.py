"""Run one local review pass per diff chunk and validate the results."""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from pr_review.config import DEFAULT_EXCLUDE_GLOBS, ConfigError
from pr_review.context.loader import gather_surrounding_context
from pr_review.context.search import gather_symbol_context
from pr_review.git.diff import FileDiff, parse_unified_diff
from pr_review.models import (
    ContextInspection,
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
    "Only the diff was sent to the model. No extra repository context was loaded."
)
_FINDINGS_REQUIRE_DIFF = (
    "Published findings must cite evidence from the diff, not repository context alone."
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
    context_enabled: bool = True
    context_surrounding_lines: int = Field(default=15, ge=0)
    context_max_bytes: int = Field(default=50_000, ge=0)
    context_symbol_search: bool = True


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

    limitations = [_FINDINGS_REQUIRE_DIFF]
    context_inspected: list[ContextInspection] = []
    if options.context_enabled and options.repo_root:
        limitations.append(
            "Repository context slices were loaded where available; "
            "see scope.context_inspected."
        )
    else:
        limitations.append(_DIFF_ONLY)

    if options.include_untracked_limitation:
        limitations.append(_UNTRACKED)
    for skipped in prepared.skipped:
        limitations.append(f"Skipped {skipped.path}: {skipped.reason}")

    summaries: list[str] = []
    candidates: list[Finding] = []
    files_by_path = {
        file_diff.path: file_diff
        for file_diff in prepared.parsed.files
        if file_diff.path
    }

    if not prepared.chunks:
        limitations.append("No reviewable textual changes were sent to the model.")
    else:
        for index, chunk in enumerate(prepared.chunks, start=1):
            chunk_files = [
                files_by_path[path]
                for path in chunk.paths
                if path in files_by_path
            ]
            document = _review_chunk(
                provider,
                options,
                chunk_text=chunk.text,
                chunk_files=chunk_files,
                chunk_index=index,
                chunk_count=len(prepared.chunks),
            )
            context_inspected.extend(document.context_inspected)
            for note in document.context_notes:
                limitations.append(note)
            parsed_document = document.document
            if parsed_document.summary:
                summaries.append(parsed_document.summary)
            if parsed_document.skipped_non_objects:
                limitations.append(
                    f"Chunk {index}: skipped "
                    f"{parsed_document.skipped_non_objects} non-object findings"
                )
            if parsed_document.truncated_findings:
                limitations.append(
                    f"Chunk {index}: ignored {parsed_document.truncated_findings} "
                    "findings beyond the per-chunk cap"
                )
            for raw_index, raw in enumerate(parsed_document.findings, start=1):
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
        context_inspected=_dedupe_inspections(context_inspected),
    )
    return ReviewReport(
        summary=summary,
        findings=validation.accepted,
        checks=[],
        limitations=limitations,
        scope=scope,
    )


class _ChunkReviewResult:
    __slots__ = (
        "context_inspected",
        "context_notes",
        "document",
    )

    def __init__(
        self,
        *,
        document,
        context_inspected: list[ContextInspection],
        context_notes: list[str],
    ) -> None:
        self.document = document
        self.context_inspected = context_inspected
        self.context_notes = context_notes


def _dedupe_inspections(
    inspected: list[ContextInspection],
) -> list[ContextInspection]:
    seen: set[tuple[str, int, int, str]] = set()
    unique: list[ContextInspection] = []
    for item in inspected:
        key = (item.path, item.start_line, item.end_line, item.reason)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _review_chunk(
    provider: LLMProvider,
    options: ReviewOptions,
    *,
    chunk_text: str,
    chunk_files: list[FileDiff],
    chunk_index: int,
    chunk_count: int,
) -> _ChunkReviewResult:
    context_text = ""
    context_inspected: list[ContextInspection] = []
    context_notes: list[str] = []
    if options.context_enabled and options.repo_root and chunk_files:
        gathered = gather_surrounding_context(
            repo_root=options.repo_root,
            file_diffs=chunk_files,
            exclude_globs=options.exclude_globs,
            surrounding_lines=options.context_surrounding_lines,
            max_bytes=options.context_max_bytes,
        )
        context_parts = [gathered.prompt_text] if gathered.prompt_text else []
        context_inspected = list(gathered.inspected)
        context_notes = [
            f"Chunk {chunk_index}: {note}" for note in gathered.notes if note
        ]
        if options.context_symbol_search:
            symbols = gather_symbol_context(
                repo_root=options.repo_root,
                file_diffs=chunk_files,
                exclude_globs=options.exclude_globs,
                max_bytes=options.context_max_bytes,
            )
            if symbols.prompt_text:
                context_parts.append(symbols.prompt_text)
            context_inspected.extend(symbols.inspected)
            context_notes.extend(
                f"Chunk {chunk_index}: {note}" for note in symbols.notes if note
            )
        context_text = "\n\n".join(context_parts)

    messages = build_messages(
        comparison=options.comparison,
        chunk_text=chunk_text,
        context_text=context_text,
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
            document = parse_model_document(response.content)
            return _ChunkReviewResult(
                document=document,
                context_inspected=context_inspected,
                context_notes=context_notes,
            )
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
