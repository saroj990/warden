"""Unit tests for the GitHub adapter. HTTP is mocked."""

from __future__ import annotations

import json

import httpx
import pytest

from pr_review.git.diff import parse_unified_diff
from pr_review.integrations.comments import build_review_plan
from pr_review.integrations.github import GitHubClient, GitHubError, parse_repository
from pr_review.integrations.review_pr import render_github_review, run_github_review
from pr_review.models import ReviewReport, ReviewScope, finding_with_fingerprint
from tests.unit.test_orchestrator import ScriptedProvider, _document, _finding_payload

DIFF = """\
diff --git a/src/example.py b/src/example.py
index 1111111..2222222 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1,3 +1,4 @@
 def run(cfg):
-    return cfg['x'].strip()
+    value = cfg.get('x')
+    return value.strip()
     return None
"""

TOKEN = "github-token-value"


def _report(*payloads: dict) -> ReviewReport:
    return ReviewReport(
        summary="Checked the pull request",
        findings=[finding_with_fingerprint(payload) for payload in payloads],
        scope=ReviewScope(diff_source="github", comparison="https://example.test/pr/7"),
    )


def test_repository_slug_must_be_owner_and_name() -> None:
    assert parse_repository("acme/app") == ("acme", "app")
    with pytest.raises(GitHubError, match="owner/name"):
        parse_repository("acme")


def test_plan_keeps_commentable_lines_and_skips_the_rest() -> None:
    parsed = parse_unified_diff(DIFF)
    finding = finding_with_fingerprint(_finding_payload())
    off_diff = finding_with_fingerprint(
        _finding_payload(line=40, title="Wrong line", problem="not in the diff")
    )
    file_level = finding_with_fingerprint(
        _finding_payload(
            line=None,
            location_kind="file",
            title="File note",
            problem="applies to the whole file",
        )
    )
    plan = build_review_plan(
        _report(finding, off_diff, file_level),
        parsed,
        existing_comment_bodies=[],
        existing_review_bodies=[],
    )

    assert plan.post
    assert [comment.line for comment in plan.comments] == [2]
    assert "<!-- warden:" in plan.comments[0].body
    assert any("not commentable" in item.reason for item in plan.skipped)
    assert any("summary" in item.reason for item in plan.skipped)
    assert "File note" in plan.summary


def test_plan_skips_a_fingerprint_that_was_already_posted() -> None:
    parsed = parse_unified_diff(DIFF)
    finding = finding_with_fingerprint(_finding_payload())
    first = build_review_plan(
        _report(finding),
        parsed,
        existing_comment_bodies=[],
        existing_review_bodies=[],
    )
    second = build_review_plan(
        _report(finding),
        parsed,
        existing_comment_bodies=[first.comments[0].body],
        existing_review_bodies=[first.summary],
    )
    assert second.comments == []
    assert second.post is False
    assert any(item.reason == "already posted" for item in second.skipped)


def test_client_dry_run_requests_do_not_post() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if request.method == "POST":
            return httpx.Response(500, json={"message": "should not post"})
        if request.url.path.endswith("/comments") or request.url.path.endswith(
            "/reviews"
        ):
            return httpx.Response(200, json=[])
        if request.headers["Accept"] == "application/vnd.github.diff":
            return httpx.Response(200, text=DIFF)
        return httpx.Response(
            200,
            json={
                "title": "Fix strip",
                "html_url": "https://github.com/acme/app/pull/7",
                "head": {"sha": "abc123"},
            },
        )

    client = GitHubClient(
        token=TOKEN,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.test",
        ),
    )
    provider = ScriptedProvider([_document([_finding_payload()])])
    result = run_github_review(
        client=client,
        provider=provider,
        repository="acme/app",
        pull_number=7,
        model="test-model",
        timeout_seconds=5,
        publish=False,
    )
    rendered = render_github_review(result, "markdown")

    assert "POST" not in seen
    assert result.posted is False
    assert result.mode == "dry-run"
    assert "would publish" in rendered
    assert "`src/example.py:2`" in rendered
    assert TOKEN not in rendered


def test_publish_posts_a_comment_review_only() -> None:
    posted: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={"html_url": "https://github.com/acme/app/pull/7#review"},
            )
        if request.url.path.endswith("/comments") or request.url.path.endswith(
            "/reviews"
        ):
            return httpx.Response(200, json=[])
        if request.headers["Accept"] == "application/vnd.github.diff":
            return httpx.Response(200, text=DIFF)
        return httpx.Response(
            200,
            json={
                "html_url": "https://github.com/acme/app/pull/7",
                "head": {"sha": "abc123"},
            },
        )

    client = GitHubClient(
        token=TOKEN,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.test",
        ),
    )
    result = run_github_review(
        client=client,
        provider=ScriptedProvider([_document([_finding_payload()])]),
        repository="acme/app",
        pull_number=7,
        model="test-model",
        timeout_seconds=5,
        publish=True,
    )

    assert result.posted is True
    assert posted["body"]["event"] == "COMMENT"
    assert posted["body"]["commit_id"] == "abc123"
    comment = posted["body"]["comments"][0]
    assert comment["path"] == "src/example.py"
    assert comment["line"] == 2
    assert comment["side"] == "RIGHT"
    assert TOKEN not in json.dumps(posted["body"])


def test_create_review_refuses_approval() -> None:
    client = GitHubClient(
        token=TOKEN,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(500, json={"message": "no"})
            ),
            base_url="https://api.github.test",
        ),
    )
    with pytest.raises(GitHubError, match="COMMENT"):
        client.create_review(
            "acme",
            "app",
            7,
            commit_id="abc123",
            body="no",
            comments=[],
            event="APPROVE",
        )


def test_error_text_redacts_the_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": f"bad {TOKEN}"})

    client = GitHubClient(
        token=TOKEN,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.test",
        ),
    )
    with pytest.raises(GitHubError, match="redacted") as exc:
        client.get_pull("acme", "app", 7)
    assert TOKEN not in str(exc.value)


def test_missing_token_raises_before_a_request() -> None:
    with pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        GitHubClient(token="  ")
