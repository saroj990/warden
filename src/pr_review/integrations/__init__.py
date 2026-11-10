"""Host adapters. Publishing stays outside the review engine."""

from pr_review.integrations.comments import GitHubReviewPlan, build_review_plan
from pr_review.integrations.github import GitHubClient, GitHubError, PullRequestInfo

__all__ = [
    "GitHubClient",
    "GitHubError",
    "GitHubReviewPlan",
    "PullRequestInfo",
    "build_review_plan",
]
