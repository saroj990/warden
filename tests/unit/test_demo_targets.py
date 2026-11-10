"""Smoke tests for the intentional review-demo modules.

These modules exist only on ``demo/review-targets`` for manual ``warden review``.
They are not meant to merge to master.
"""

from __future__ import annotations

from pathlib import Path

from pr_review.billing import apply_discount, format_cents
from pr_review.ingest import WEBHOOK_TOKEN, read_export_file


def test_apply_discount_demo_behavior() -> None:
    assert apply_discount(1000, 10) == -9000


def test_format_cents_demo_behavior() -> None:
    assert format_cents(199) == "$199"


def test_read_export_file_reads_under_repo(tmp_path: Path) -> None:
    sample = tmp_path / "report.txt"
    sample.write_text("ok", encoding="utf-8")
    assert read_export_file("report.txt", tmp_path) == "ok"


def test_webhook_token_is_present_for_demo() -> None:
    assert WEBHOOK_TOKEN.startswith("wh_")
