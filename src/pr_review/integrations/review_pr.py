"""Fetch a GitHub pull request, review its diff, and optionally publish."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pr_review.git.diff import parse_unified_diff
from pr_review.integrations.comments import (
    PlannedComment,
    SkippedComment,
    build_review_plan,
)
from pr_review.integrations.github import GitHubClient, parse_repository
from pr_review.providers.base import LLMProvider
from pr_review.review.orchestrator import ReviewOptions, run_review

Mode = Literal["dry-run", "publish"]


class GitHubReviewResult(BaseModel):
    repository: str
    pull_number: int
    commit_id: str
    html_url: str
    mode: Mode
    posted: bool
    post: bool
    review_url: str = ""
    summary: str
    comments: list[PlannedComment] = Field(default_factory=list)
    skipped: list[SkippedComment] = Field(default_factory=list)


def run_github_review(
    *,
    client: GitHubClient,
    provider: LLMProvider,
    repository: str,
    pull_number: int,
    model: str,
    timeout_seconds: float,
    publish: bool,
    stream_model_output: bool = False,
) -> GitHubReviewResult:
    """Review one pull request. Publishing happens only when ``publish`` is set."""
    owner, name = parse_repository(repository)
    pull = client.get_pull(owner, name, pull_number)
    diff_text = client.get_diff(owner, name, pull_number)
    parsed = parse_unified_diff(diff_text)
    report = run_review(
        diff_text,
        provider,
        ReviewOptions(
            model=model,
            provider_name=provider.name,
            comparison=pull.html_url,
            diff_source=f"github:{repository}#{pull_number}",
            timeout_seconds=timeout_seconds,
            context_enabled=False,
            context_symbol_search=False,
            stream_model_output=stream_model_output,
        ),
    )
    plan = build_review_plan(
        report,
        parsed,
        existing_comment_bodies=client.list_comment_bodies(owner, name, pull_number),
        existing_review_bodies=client.list_review_bodies(owner, name, pull_number),
    )
    mode: Mode = "publish" if publish else "dry-run"
    review_url = ""
    posted = False
    if publish and plan.post:
        review_url = client.create_review(
            owner,
            name,
            pull_number,
            commit_id=pull.head_sha,
            body=plan.summary,
            comments=[
                {
                    "path": comment.path,
                    "line": comment.line,
                    "side": "RIGHT",
                    "body": comment.body,
                }
                for comment in plan.comments
            ],
        )
        posted = True
    return GitHubReviewResult(
        repository=repository,
        pull_number=pull_number,
        commit_id=pull.head_sha,
        html_url=pull.html_url,
        mode=mode,
        posted=posted,
        post=plan.post,
        review_url=review_url,
        summary=plan.summary,
        comments=plan.comments,
        skipped=plan.skipped,
    )


def render_github_review(result: GitHubReviewResult, report_format: str) -> str:
    if report_format == "json":
        return result.model_dump_json(indent=2) + "\n"
    if report_format == "markdown":
        return _markdown(result)
    raise ValueError(f"unsupported report format: {report_format}")


def _markdown(result: GitHubReviewResult) -> str:
    if result.mode == "dry-run":
        action = "would publish" if result.post else "nothing new to publish"
    elif result.posted:
        action = "posted a COMMENT review"
    else:
        action = "nothing new to publish"
    lines = [
        "# GitHub review",
        "",
        f"- Repository: {result.repository}",
        f"- Pull request: {result.pull_number}",
        f"- URL: {result.html_url}",
        f"- Commit: {result.commit_id}",
        f"- Mode: {result.mode}",
        f"- Action: {action}",
        "",
        "## Summary",
        "",
        result.summary.rstrip(),
        "",
        "## Inline comments",
        "",
    ]
    if result.comments:
        for comment in result.comments:
            lines.append(f"- `{comment.path}:{comment.line}`")
    else:
        lines.append("None.")
    lines.extend(["", "## Skipped", ""])
    if result.skipped:
        for skipped in result.skipped:
            location = skipped.path
            if skipped.line is not None:
                location = f"{skipped.path}:{skipped.line}"
            lines.append(f"- `{location}`: {skipped.reason}")
    else:
        lines.append("None.")
    if result.review_url:
        lines.extend(["", f"Review: {result.review_url}"])
    lines.append("")
    return "\n".join(lines)
