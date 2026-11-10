"""Read-only GitHub pull request access, plus opt-in COMMENT reviews."""

from __future__ import annotations

import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_API_VERSION = "2022-11-28"
_MAX_PAGES = 10


class GitHubError(Exception):
    """A GitHub request failed, or the caller asked for an unsafe action."""


class PullRequestInfo(BaseModel):
    number: int = Field(ge=1)
    title: str = ""
    html_url: str
    head_sha: str = Field(min_length=1)


def parse_repository(value: str) -> tuple[str, str]:
    """Return ``(owner, name)`` for an ``owner/name`` slug."""
    slug = value.strip()
    if not _REPO_RE.fullmatch(slug):
        raise GitHubError("repository must look like owner/name")
    owner, name = slug.split("/", 1)
    return owner, name


class GitHubClient:
    """GitHub REST client. It can post a COMMENT review and nothing else."""

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://api.github.com",
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        cleaned = token.strip()
        if not cleaned:
            raise GitHubError("GITHUB_TOKEN is required")
        self._token = cleaned
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_pull(self, owner: str, repo: str, number: int) -> PullRequestInfo:
        payload = self._request_json("GET", f"/repos/{owner}/{repo}/pulls/{number}")
        if not isinstance(payload, dict):
            raise GitHubError("GitHub pull request response was not an object")
        head = payload.get("head")
        sha = head.get("sha") if isinstance(head, dict) else None
        url = payload.get("html_url")
        if not isinstance(sha, str) or not sha.strip():
            raise GitHubError("GitHub pull request response omitted the head sha")
        if not isinstance(url, str) or not url.strip():
            raise GitHubError("GitHub pull request response omitted the URL")
        title = payload.get("title")
        return PullRequestInfo(
            number=number,
            title=title if isinstance(title, str) else "",
            html_url=url,
            head_sha=sha,
        )

    def get_diff(self, owner: str, repo: str, number: int) -> str:
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{number}",
            accept="application/vnd.github.diff",
        )
        return response.text

    def list_comment_bodies(self, owner: str, repo: str, number: int) -> list[str]:
        return self._bodies(f"/repos/{owner}/{repo}/pulls/{number}/comments")

    def list_review_bodies(self, owner: str, repo: str, number: int) -> list[str]:
        return self._bodies(f"/repos/{owner}/{repo}/pulls/{number}/reviews")

    def create_review(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        commit_id: str,
        body: str,
        comments: list[dict[str, object]],
        event: str = "COMMENT",
    ) -> str:
        if event != "COMMENT":
            raise GitHubError("only COMMENT reviews can be published")
        payload: dict[str, object] = {
            "commit_id": commit_id,
            "body": body,
            "event": "COMMENT",
        }
        if comments:
            payload["comments"] = comments
        created = self._request_json(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{number}/reviews",
            json_body=payload,
        )
        if not isinstance(created, dict):
            raise GitHubError("GitHub review response was not an object")
        url = created.get("html_url")
        if isinstance(url, str) and url.strip():
            return url
        return ""

    def _bodies(self, path: str) -> list[str]:
        bodies: list[str] = []
        for item in self._paginate(path):
            body = item.get("body")
            if isinstance(body, str):
                bodies.append(body)
        return bodies

    def _paginate(self, path: str) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for page in range(1, _MAX_PAGES + 1):
            payload = self._request_json(
                "GET",
                path,
                params={"per_page": 100, "page": page},
            )
            if not isinstance(payload, list):
                raise GitHubError("GitHub list response was not a list")
            for item in payload:
                if isinstance(item, dict):
                    collected.append(item)
            if len(payload) < 100:
                break
        return collected

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> Any:
        response = self._request(
            method,
            path,
            params=params,
            json_body=json_body,
        )
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubError("GitHub returned a non-JSON body") from exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
        accept: str = "application/vnd.github+json",
    ) -> httpx.Response:
        try:
            response = self._http().request(
                method,
                path,
                params=params,
                json=json_body,
                headers=self._headers(accept),
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise GitHubError("GitHub request timed out") from exc
        except httpx.HTTPError as exc:
            raise GitHubError(self._redact(f"GitHub request failed: {exc}")) from exc
        if response.status_code == 401:
            raise GitHubError("GitHub authentication failed. Check GITHUB_TOKEN.")
        if response.status_code == 404:
            raise GitHubError(
                "GitHub pull request was not found, or the token cannot see it."
            )
        if response.status_code >= 400:
            message = _error_message(response)
            raise GitHubError(self._redact(f"GitHub request failed: {message}"))
        return response

    def _headers(self, accept: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": "warden",
        }

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url)
        return self._client

    def _redact(self, text: str) -> str:
        if self._token and self._token in text:
            return text.replace(self._token, "[redacted]")
        return text


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:300]
    text = response.text.strip()
    return text[:300] or f"HTTP {response.status_code}"
