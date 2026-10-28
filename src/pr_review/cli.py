"""Command-line entry point for pr-review."""

from __future__ import annotations

import argparse
import sys

from pr_review import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-review",
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
        help="Check local installation and report scaffold status.",
    )
    doctor.set_defaults(func=cmd_doctor)

    return parser


def cmd_doctor(_args: argparse.Namespace) -> int:
    print(f"pr-review {__version__}")
    print("Status: scaffold only — review pipeline not implemented yet.")
    print("Python package import: ok")
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
