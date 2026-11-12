"""Command-line entry point for warden."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from pr_review import __version__
from pr_review.config import ConfigError, Settings, load_settings
from pr_review.eval.cases import EvalError, load_cases
from pr_review.eval.report import render_eval_report
from pr_review.eval.runner import run_evaluation
from pr_review.git.repository import GitCommandError, collect_diff
from pr_review.integrations.github import GitHubClient, GitHubError
from pr_review.integrations.review_pr import render_github_review, run_github_review
from pr_review.providers.base import LLMProvider, ProviderError
from pr_review.providers.ollama import OllamaProvider
from pr_review.reporters import exceeds_fail_threshold, render_report
from pr_review.review import ReviewOptions, ReviewOutputError, run_review

_SEVERITY_CHOICES = ("critical", "high", "medium", "low", "none")
_FORMAT_CHOICES = ("markdown", "json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="warden",
        description="Local-first, evidence-backed pull request review agent.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    doctor = subparsers.add_parser(
        "doctor",
        help="Check the local installation.",
    )
    doctor.set_defaults(func=cmd_doctor)

    review = subparsers.add_parser(
        "review",
        help="Review a local diff and write a Markdown or JSON report.",
    )
    review.add_argument(
        "--repo",
        default=".",
        help="Repository root used for git diffs and path checks (default: .).",
    )
    review.add_argument(
        "--base",
        default=None,
        help="Base revision. Default: review.base from config, otherwise main.",
    )
    review.add_argument(
        "--head",
        default=None,
        help="Head revision. With --base, reviews the merge-base range base...head.",
    )
    review.add_argument(
        "--diff",
        default=None,
        help="Review this unified diff file instead of running git. Use - for stdin.",
    )
    review.add_argument(
        "--provider",
        default=None,
        help="LLM provider. Only ollama is implemented.",
    )
    review.add_argument(
        "--model",
        default=None,
        help="Model name passed to the provider.",
    )
    review.add_argument(
        "--base-url",
        default=None,
        help="Provider base URL. Default: OLLAMA_BASE_URL or the local Ollama URL.",
    )
    review.add_argument(
        "--format",
        dest="report_format",
        choices=_FORMAT_CHOICES,
        default=None,
        help="Report format (default: markdown).",
    )
    review.add_argument(
        "--output",
        default=None,
        help="Write the report to this path instead of stdout.",
    )
    review.add_argument(
        "--fail-on",
        dest="fail_on_severity",
        choices=_SEVERITY_CHOICES,
        default=None,
        help="Exit 1 when a finding is at or above this severity (default: none).",
    )
    review.add_argument(
        "--config",
        default=None,
        help="TOML config file. Default: ./config.toml when that file exists.",
    )
    review.add_argument(
        "--max-diff-bytes",
        type=int,
        default=None,
        help="Maximum bytes of diff text sent in one model chunk.",
    )
    review.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Provider timeout in seconds.",
    )
    review.add_argument(
        "--stream",
        action="store_true",
        help="Stream model output to stderr while Ollama generates (review report still on stdout).",
    )
    review.set_defaults(func=cmd_review)

    evaluate = subparsers.add_parser(
        "eval",
        help="Score the reviewer against labeled fixture diffs.",
    )
    evaluate.add_argument(
        "--cases",
        default="tests/fixtures/eval",
        help="Directory of labeled cases (default: tests/fixtures/eval).",
    )
    evaluate.add_argument(
        "--provider",
        default=None,
        help="LLM provider. Only ollama is implemented.",
    )
    evaluate.add_argument(
        "--model",
        default=None,
        help="Model name passed to the provider.",
    )
    evaluate.add_argument(
        "--base-url",
        default=None,
        help="Provider base URL. Default: OLLAMA_BASE_URL or the local Ollama URL.",
    )
    evaluate.add_argument(
        "--format",
        dest="report_format",
        choices=_FORMAT_CHOICES,
        default=None,
        help="Report format (default: markdown).",
    )
    evaluate.add_argument(
        "--output",
        default=None,
        help="Write the report to this path instead of stdout.",
    )
    evaluate.add_argument(
        "--config",
        default=None,
        help="TOML config file. Default: ./config.toml when that file exists.",
    )
    evaluate.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Provider timeout in seconds.",
    )
    evaluate.set_defaults(func=cmd_eval)

    github = subparsers.add_parser(
        "github",
        help="Review a GitHub pull request. Dry-run unless --publish is set.",
    )
    github_commands = github.add_subparsers(dest="github_command")
    github_review = github_commands.add_parser(
        "review",
        help="Review a pull request and preview or post a COMMENT review.",
    )
    github_review.add_argument(
        "--repository",
        required=True,
        help="GitHub repository as owner/name.",
    )
    github_review.add_argument(
        "--pr",
        type=int,
        required=True,
        help="Pull request number.",
    )
    github_review.add_argument(
        "--provider",
        default=None,
        help="LLM provider. Only ollama is implemented.",
    )
    github_review.add_argument(
        "--model",
        default=None,
        help="Model name passed to the provider.",
    )
    github_review.add_argument(
        "--base-url",
        default=None,
        help="Model provider base URL. Default: OLLAMA_BASE_URL or local Ollama.",
    )
    github_review.add_argument(
        "--format",
        dest="report_format",
        choices=_FORMAT_CHOICES,
        default=None,
        help="Report format (default: markdown).",
    )
    github_review.add_argument(
        "--output",
        default=None,
        help="Write the preview or publish result to this path instead of stdout.",
    )
    github_review.add_argument(
        "--config",
        default=None,
        help="TOML config file. Default: ./config.toml when that file exists.",
    )
    github_review.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Provider timeout in seconds.",
    )
    github_review.add_argument(
        "--stream",
        action="store_true",
        help="Stream model output to stderr while Ollama generates.",
    )
    github_review.add_argument(
        "--publish",
        action="store_true",
        help="Post a COMMENT review. Omit this flag to preview only.",
    )
    github_review.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview comments without posting. This is the default.",
    )
    github_review.set_defaults(func=cmd_github_review)
    github.set_defaults(func=cmd_github)
    return parser


def cmd_doctor(_args: argparse.Namespace) -> int:
    print(f"warden {__version__}")
    print("Status: local review pipeline available (warden review).")
    print("GitHub: dry-run by default (warden github review --publish to post).")
    print("Python package import: ok")
    return 0


def build_provider(settings: Settings) -> LLMProvider:
    """Construct the configured provider. Only Ollama is implemented."""
    if settings.provider_name != "ollama":
        raise ConfigError(
            f"provider {settings.provider_name!r} is not implemented; use ollama"
        )
    return OllamaProvider(
        base_url=settings.base_url,
        default_timeout_seconds=settings.timeout_seconds,
    )


def cmd_review(args: argparse.Namespace) -> int:
    try:
        settings = _settings_from_args(args)
        _validate_report_settings(settings)
        diff_text, comparison, diff_source, untracked = _load_diff(args, settings)
    except (ConfigError, GitCommandError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
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
            repo_root=str(Path(args.repo).expanduser().resolve()),
            include_untracked_limitation=untracked,
            context_enabled=settings.context_enabled,
            context_surrounding_lines=settings.context_surrounding_lines,
            context_max_bytes=settings.context_max_bytes,
            context_symbol_search=settings.context_symbol_search,
            stream_model_output=bool(getattr(args, "stream", False)),
        )
    except ValidationError as exc:
        print(f"error: invalid review options: {exc}", file=sys.stderr)
        return 2

    try:
        provider = build_provider(settings)
        report = run_review(diff_text, provider, options)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ProviderError, ReviewOutputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rendered = render_report(report, settings.report_format)
    try:
        _write_report(rendered, args.output)
    except OSError as exc:
        print(f"error: could not write report: {exc}", file=sys.stderr)
        return 2

    if exceeds_fail_threshold(report, settings.fail_on_severity):
        return 1
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(args.config)
        updates: dict[str, object] = {}
        if args.provider:
            updates["provider_name"] = args.provider
        if args.model:
            updates["model"] = args.model
        if args.base_url:
            updates["base_url"] = args.base_url
        if args.report_format:
            updates["report_format"] = args.report_format
        if args.timeout is not None:
            updates["timeout_seconds"] = args.timeout
        if updates:
            settings = settings.model_copy(update=updates)
        _validate_report_settings(settings)
        if not settings.model.strip():
            raise ConfigError("model is required (pass --model or set OLLAMA_MODEL)")
        cases = load_cases(args.cases)
    except (ConfigError, EvalError, OSError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        provider = build_provider(settings)
        report = run_evaluation(
            cases,
            provider,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rendered = render_eval_report(report, settings.report_format)
    try:
        _write_report(rendered, args.output)
    except OSError as exc:
        print(f"error: could not write report: {exc}", file=sys.stderr)
        return 2
    return 0 if report.passed else 1


def _validate_report_settings(settings: Settings) -> None:
    if settings.report_format not in _FORMAT_CHOICES:
        raise ConfigError(f"unsupported report format: {settings.report_format}")
    if settings.fail_on_severity not in _SEVERITY_CHOICES:
        raise ConfigError(
            f"unsupported severity threshold: {settings.fail_on_severity}"
        )


def _settings_from_args(args: argparse.Namespace) -> Settings:
    settings = load_settings(args.config)
    updates: dict[str, object] = {}
    if args.base:
        updates["base"] = args.base
    if args.provider:
        updates["provider_name"] = args.provider
    if args.model:
        updates["model"] = args.model
    if args.base_url:
        updates["base_url"] = args.base_url
    if args.report_format:
        updates["report_format"] = args.report_format
    if args.fail_on_severity:
        updates["fail_on_severity"] = args.fail_on_severity
    if args.max_diff_bytes is not None:
        updates["max_diff_bytes"] = args.max_diff_bytes
    if args.timeout is not None:
        updates["timeout_seconds"] = args.timeout
    if updates:
        settings = settings.model_copy(update=updates)
    return settings


def _load_diff(
    args: argparse.Namespace,
    settings: Settings,
) -> tuple[str, str, str, bool]:
    """Return diff text, comparison label, source label, and untracked note."""
    if args.diff and (args.base or args.head):
        raise ConfigError("use either --diff or --base/--head, not both")

    if args.diff:
        if args.diff == "-":
            return sys.stdin.read(), "supplied diff", "stdin", False
        path = Path(args.diff)
        if not path.is_file():
            raise ConfigError(f"diff file not found: {path}")
        return (
            path.read_text(encoding="utf-8"),
            f"supplied diff {path}",
            str(path),
            False,
        )

    base = args.base or settings.base
    diff_text, comparison = collect_diff(repo=args.repo, base=base, head=args.head)
    source = f"git diff in {Path(args.repo).expanduser().resolve()}"
    untracked = not (args.head and args.head.strip())
    return diff_text, comparison, source, untracked


def _write_report(rendered: str, output: str | None) -> None:
    if output:
        Path(output).write_text(rendered, encoding="utf-8")
        return
    sys.stdout.write(rendered)


def cmd_github(args: argparse.Namespace) -> int:
    if not getattr(args, "github_command", None):
        print("error: github requires a subcommand (review)", file=sys.stderr)
        return 2
    return cmd_github_review(args)


def cmd_github_review(args: argparse.Namespace) -> int:
    if args.publish and args.dry_run:
        print("error: use either --publish or --dry-run, not both", file=sys.stderr)
        return 2
    try:
        settings = load_settings(args.config)
        updates: dict[str, object] = {}
        if args.provider:
            updates["provider_name"] = args.provider
        if args.model:
            updates["model"] = args.model
        if args.base_url:
            updates["base_url"] = args.base_url
        if args.report_format:
            updates["report_format"] = args.report_format
        if args.timeout is not None:
            updates["timeout_seconds"] = args.timeout
        if updates:
            settings = settings.model_copy(update=updates)
        _validate_report_settings(settings)
        if not settings.model.strip():
            raise ConfigError("model is required (pass --model or set OLLAMA_MODEL)")
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if not token:
            raise GitHubError("GITHUB_TOKEN is required")
        api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").strip()
        provider = build_provider(settings)
        github = GitHubClient(
            token=token,
            base_url=api_url or "https://api.github.com",
        )
        with github as client:
            result = run_github_review(
                client=client,
                provider=provider,
                repository=args.repository,
                pull_number=args.pr,
                model=settings.model,
                timeout_seconds=settings.timeout_seconds,
                publish=args.publish,
                stream_model_output=bool(getattr(args, "stream", False)),
            )
        rendered = render_github_review(result, settings.report_format)
        _write_report(rendered, args.output)
    except (ConfigError, GitHubError, OSError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ProviderError, ReviewOutputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
