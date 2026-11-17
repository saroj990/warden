"""Resolve local paths or GitHub repos to a git work tree for the local UI."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_GITHUB_URL = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_CACHE_ROOT = Path(__file__).resolve().parent / "cache" / "repos"


@dataclass(frozen=True)
class ResolvedRepo:
    root: Path
    label: str
    github_slug: str | None = None


def parse_github_slug(value: str) -> tuple[str, str] | None:
    text = value.strip()
    if not text:
        return None
    match = _GITHUB_URL.match(text)
    if match:
        return match.group("owner"), match.group("repo").removesuffix(".git")
    if _SLUG.fullmatch(text):
        owner, repo = text.split("/", 1)
        return owner, repo
    return None


def _git_url(owner: str, repo: str, token: str | None) -> str:
    if token:
        return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    return f"https://github.com/{owner}/{repo}.git"


def _run_git(args: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def sync_github_repo(owner: str, repo: str, token: str | None) -> Path:
    dest = _CACHE_ROOT / f"{owner}_{repo}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = _git_url(owner, repo, token)

    if not (dest / ".git").is_dir():
        result = _run_git(
            [
                "git",
                "clone",
                "--filter=blob:none",
                url,
                str(dest),
            ],
            timeout=300.0,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "git clone failed").strip()
            raise RuntimeError(detail[:500])
        return dest

    result = _run_git(
        ["git", "-C", str(dest), "remote", "set-url", "origin", url],
        timeout=30.0,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git remote set-url failed").strip()
        raise RuntimeError(detail[:500])

    fetch = _run_git(
        ["git", "-C", str(dest), "fetch", "origin", "--prune", "--tags"],
        timeout=300.0,
    )
    if fetch.returncode != 0:
        detail = (fetch.stderr or fetch.stdout or "git fetch failed").strip()
        raise RuntimeError(detail[:500])
    return dest


def resolve_git_ref(repo: Path, ref: str) -> str:
    name = ref.strip()
    if not name:
        raise ValueError("branch/ref name is required")
    candidates = [
        name,
        f"origin/{name}",
        f"remotes/origin/{name}",
    ]
    for candidate in candidates:
        result = _run_git(
            ["git", "-C", str(repo), "rev-parse", "--verify", f"{candidate}^{{commit}}"],
            timeout=30.0,
        )
        if result.returncode == 0:
            return candidate
    raise ValueError(
        f"unknown revision {name!r} in {repo}. "
        "Refresh branches, fetch the ref, or check the name (this repo may use master, not main)."
    )


def ensure_refs_fetched(repo: Path, *refs: str) -> None:
    unique = [r.strip() for r in refs if r and r.strip()]
    if not unique:
        return
    args = ["git", "-C", str(repo), "fetch", "origin", *unique, "--depth", "200"]
    result = _run_git(args, timeout=300.0)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git fetch failed").strip()
        raise RuntimeError(detail[:500])


def resolve_repo(
    *,
    source: str,
    repo: str,
    github_token: str | None = None,
) -> ResolvedRepo:
    mode = source.strip().lower() or "local"
    token = (github_token or os.environ.get("GITHUB_TOKEN") or "").strip() or None

    if mode == "github":
        parsed = parse_github_slug(repo)
        if not parsed:
            raise ValueError(
                "GitHub source needs owner/repo or a https://github.com/owner/repo URL"
            )
        owner, name = parsed
        root = sync_github_repo(owner, name, token)
        slug = f"{owner}/{name}"
        return ResolvedRepo(root=root, label=slug, github_slug=slug)

    root = Path(repo).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    inside = _run_git(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise ValueError(f"not a git work tree: {root}")
    return ResolvedRepo(root=root, label=str(root))


def list_branches(repo: Path) -> list[str]:
    result = _run_git(
        [
            "git",
            "-C",
            str(repo),
            "branch",
            "-a",
            "--list",
            "--format=%(refname:short)",
        ],
        timeout=60.0,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git branch failed").strip()
        raise RuntimeError(detail[:500])

    seen: set[str] = set()
    names: list[str] = []
    for line in result.stdout.splitlines():
        raw = line.strip()
        if not raw or raw == "HEAD":
            continue
        if raw.startswith("origin/"):
            short = raw.removeprefix("origin/")
            if short == "HEAD":
                continue
            key = short
        else:
            key = raw
        if key in seen:
            continue
        seen.add(key)
        names.append(key)
    names.sort(key=str.lower)
    return names
