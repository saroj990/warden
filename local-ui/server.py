#!/usr/bin/env python3
"""Minimal browser UI for local ``warden review`` (Ollama). Binds to 127.0.0.1 only."""

from __future__ import annotations

import json
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlparse

from repo_source import (
    ResolvedRepo,
    ensure_refs_fetched,
    list_branches,
    resolve_git_ref,
    resolve_repo,
)

UI_DIR = Path(__file__).resolve().parent
REPORTS_DIR = UI_DIR / "reports"
PREFS_PATH = UI_DIR / "form.json"
HOST = "127.0.0.1"
PORT = 8765

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")

JobStatus = Literal["queued", "running", "done", "error"]


@dataclass
class ReviewJob:
    status: JobStatus = "queued"
    markdown: str = ""
    error: str = ""
    message: str = ""
    started_at: float = field(default_factory=time.time)


_jobs: dict[str, ReviewJob] = {}
_jobs_lock = threading.Lock()
_MAX_JOBS = 32


def _ollama_model_names(base_url: str) -> list[str]:
    """List installed models from Ollama ``GET /api/tags``."""
    from pr_review.providers.ollama import OllamaProvider

    url = base_url.strip().rstrip("/")
    if not url:
        raise ValueError("Ollama host URL is required")
    if not url.startswith(("http://", "https://")):
        raise ValueError("Ollama host URL must start with http:// or https://")

    provider = OllamaProvider(base_url=url)
    try:
        result = provider.check_connection()
    finally:
        provider.close()
    if not result.ok:
        raise RuntimeError(result.message)
    models = result.details.get("models")
    if not isinstance(models, list):
        return []
    names = [str(name).strip() for name in models if str(name).strip()]
    names.sort()
    return names


def _prune_jobs() -> None:
    with _jobs_lock:
        if len(_jobs) <= _MAX_JOBS:
            return
        oldest = sorted(_jobs.items(), key=lambda item: item[1].started_at)
        for job_id, _ in oldest[: len(_jobs) - _MAX_JOBS]:
            del _jobs[job_id]


def _start_review_job(payload: dict[str, object]) -> str:
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = ReviewJob(status="queued")
    thread = threading.Thread(
        target=_review_worker,
        args=(job_id, dict(payload)),
        daemon=True,
        name=f"review-{job_id[:8]}",
    )
    thread.start()
    return job_id


def _review_worker(job_id: str, payload: dict[str, object]) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.status = "running"
    try:
        markdown = _run_review(payload)
    except ValueError as exc:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job:
                job.status = "error"
                job.error = str(exc)
        return
    except RuntimeError as exc:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job:
                job.status = "error"
                job.error = str(exc)
        return
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.status = "done"
            job.markdown = markdown
            job.message = "Review finished."
    _prune_jobs()


def _job_payload(job_id: str) -> dict[str, object] | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {
            "jobId": job_id,
            "status": job.status,
            "markdown": job.markdown if job.status == "done" else "",
            "error": job.error,
            "message": job.message,
        }


def _repo_from_payload(data: dict[str, object]) -> ResolvedRepo:
    source = str(data.get("source", "local")).strip().lower() or "local"
    repo = str(data.get("repo", "")).strip()
    if not repo:
        raise ValueError("repo is required")
    token = str(data.get("githubToken", "")).strip() or None
    return resolve_repo(source=source, repo=repo, github_token=token)


def _default_prefs() -> dict[str, object]:
    return {
        "source": "local",
        "repo": str(UI_DIR.parent),
        "base": "main",
        "baseUrl": "http://127.0.0.1:11434",
        "timeout": 900,
    }


def _read_prefs() -> dict[str, object]:
    merged = _default_prefs()
    if not PREFS_PATH.is_file():
        return merged
    try:
        data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return merged
    if isinstance(data, dict):
        merged.update(data)
    return merged


def _write_prefs(data: dict[str, object]) -> None:
    PREFS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _run_review(payload: dict[str, object]) -> str:
    base = str(payload.get("base", "main")).strip() or "main"
    head = str(payload.get("head", "")).strip()
    base_url = str(payload.get("baseUrl", "http://127.0.0.1:11434")).strip()
    model = str(payload.get("model", "")).strip()
    try:
        timeout = float(payload.get("timeout", 600) or 600)
    except (TypeError, ValueError):
        timeout = 600.0
    timeout = max(60.0, min(timeout, 7200.0))
    stream = bool(payload.get("stream"))
    sys.stderr.write(
        f"Review: model={model!r} timeout={timeout}s stream={stream}\n"
    )

    if not model:
        raise ValueError("model is required")

    try:
        resolved = _repo_from_payload(payload)
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    root = resolved.root

    from pr_review.cli import build_provider
    from pr_review.config import load_settings
    from pr_review.git.repository import GitCommandError, collect_diff
    from pr_review.providers.base import ProviderError, ProviderTimeoutError
    from pr_review.reporters import render_report
    from pr_review.review import ReviewOptions, ReviewOutputError, run_review

    settings = load_settings()
    settings = settings.model_copy(
        update={
            "model": model,
            "base_url": base_url,
            "base": base,
            "timeout_seconds": timeout,
        }
    )

    head_arg: str | None = head if head else None
    try:
        if resolved.github_slug:
            ensure_refs_fetched(root, base, *( [head] if head_arg else [] ))
        base_ref = resolve_git_ref(root, base)
        head_ref = resolve_git_ref(root, head_arg) if head_arg else None
        diff_text, comparison = collect_diff(repo=root, base=base_ref, head=head_ref)
    except (GitCommandError, ValueError, RuntimeError) as exc:
        raise ValueError(str(exc)) from exc

    diff_source = (
        f"github {resolved.github_slug}"
        if resolved.github_slug
        else f"git diff in {root}"
    )
    provider = build_provider(settings)
    options = ReviewOptions(
        model=settings.model,
        provider_name=settings.provider_name,
        comparison=comparison,
        diff_source=diff_source,
        max_diff_bytes=settings.max_diff_bytes,
        max_files=settings.max_files,
        parse_retries=settings.parse_retries,
        timeout_seconds=settings.timeout_seconds,
        exclude_globs=settings.exclude_globs,
        repo_root=str(root),
        include_untracked_limitation=head_arg is None,
        context_enabled=settings.context_enabled,
        context_surrounding_lines=settings.context_surrounding_lines,
        context_max_bytes=settings.context_max_bytes,
        context_symbol_search=settings.context_symbol_search,
        stream_model_output=stream,
    )

    try:
        report = run_review(diff_text, provider, options)
    except ProviderTimeoutError as exc:
        raise RuntimeError(
            f"{exc} — raise Timeout (seconds) in the form or use a smaller diff."
        ) from exc
    except (ProviderError, ReviewOutputError) as exc:
        raise RuntimeError(str(exc)) from exc
    finally:
        provider.close()

    return render_report(report, "markdown")


class Handler(BaseHTTPRequestHandler):
    server_version = "warden-local-ui/0.1"

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            sys.stderr.write("Client disconnected before response was sent.\n")

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = (UI_DIR / "index.html").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        if path == "/api/prefs":
            self._send_json(HTTPStatus.OK, _read_prefs())
            return
        if path == "/api/branches":
            qs = parse_qs(urlparse(self.path).query)
            repo_list = qs.get("repo", [])
            if not repo_list or not repo_list[0].strip():
                self._send_json(
                    HTTPStatus.BAD_REQUEST, {"error": "repo query is required"}
                )
                return
            payload = {
                "source": (qs.get("source", ["local"])[0] or "local").strip(),
                "repo": repo_list[0].strip(),
                "githubToken": (qs.get("githubToken", [""])[0] or "").strip(),
            }
            try:
                resolved = _repo_from_payload(payload)
                branches = list_branches(resolved.root)
            except (OSError, RuntimeError, ValueError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, {"branches": branches})
            return
        if path == "/api/ollama/models":
            qs = parse_qs(urlparse(self.path).query)
            base_list = qs.get("baseUrl", [])
            if not base_list or not base_list[0].strip():
                self._send_json(
                    HTTPStatus.BAD_REQUEST, {"error": "baseUrl query is required"}
                )
                return
            try:
                models = _ollama_model_names(base_list[0])
            except (ValueError, RuntimeError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, {"models": models})
            return
        if path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/") :].strip("/")
            if not job_id or "/" in job_id:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid job id"})
                return
            payload = _job_payload(job_id)
            if payload is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "job not found"})
                return
            self._send_json(HTTPStatus.OK, payload)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            data = self._read_json()
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        if path == "/api/prefs":
            _write_prefs(data)
            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        if path == "/api/review":
            try:
                _repo_from_payload(data)
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if not str(data.get("model", "")).strip():
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "model is required"})
                return
            job_id = _start_review_job(data)
            self._send_json(
                HTTPStatus.ACCEPTED,
                {
                    "jobId": job_id,
                    "status": "queued",
                    "message": "Review started; poll /api/jobs/{jobId}.",
                },
            )
            return

        if path == "/api/save":
            content = data.get("content")
            filename = str(data.get("filename", "")).strip()
            if not isinstance(content, str) or not content:
                self._send_json(
                    HTTPStatus.BAD_REQUEST, {"error": "content is required"}
                )
                return
            if not filename:
                self._send_json(
                    HTTPStatus.BAD_REQUEST, {"error": "filename is required"}
                )
                return
            safe = _SAFE_NAME.sub("_", Path(filename).name)
            if not safe.endswith((".md", ".json", ".txt")):
                safe += ".md"
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            target = (REPORTS_DIR / safe).resolve()
            if not str(target).startswith(str(REPORTS_DIR.resolve())):
                self._send_json(
                    HTTPStatus.BAD_REQUEST, {"error": "invalid filename"}
                )
                return
            target.write_text(content, encoding="utf-8")
            self._send_json(HTTPStatus.OK, {"path": str(target)})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"Warden local UI at {url}")
    print("Press Ctrl+C to stop.")
    if stream_note := (
        "Streamed tokens appear in this terminal when stream is enabled."
    ):
        print(stream_note)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
