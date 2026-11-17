"""Unit tests for deterministic regression checks (Phase 1.2)."""

from __future__ import annotations

from pr_review.checks.regression import regression_finding_payloads
from pr_review.git.diff import parse_unified_diff
from pr_review.models import finding_with_fingerprint
from pr_review.review.validator import validate_findings

DISCOUNT_PATCH = """\
diff --git a/src/billing.py b/src/billing.py
--- a/src/billing.py
+++ b/src/billing.py
@@ -6,8 +6,7 @@
 def apply_discount(amount_cents: int, percent: float) -> int:
     \"\"\"Apply a percentage discount to an amount in cents.\"\"\"
-    discount = amount_cents * (percent / 100.0)
-    return int(round(amount_cents - discount))
+    return int(round(amount_cents * (1 - percent)))
"""

MONEY_PATCH = """\
diff --git a/src/billing.py b/src/billing.py
--- a/src/billing.py
+++ b/src/billing.py
@@ -10,6 +10,5 @@
 def format_cents(cents: int) -> str:
     \"\"\"Format cents as a dollar string.\"\"\"
-    dollars = cents / 100.0
-    return f"${dollars:.2f}"
+    return f"${cents}"
"""

SHELL_PATCH = """\
diff --git a/src/hooks.py b/src/hooks.py
--- a/src/hooks.py
+++ b/src/hooks.py
@@ -8,5 +8,4 @@
 def run_post_review_hook(command: str) -> int:
-    completed = subprocess.run(command, check=False, shell=False, capture_output=True)
+    completed = subprocess.run(command, check=False, shell=True, capture_output=True)
     return completed.returncode
"""

SECRET_PATCH = """\
diff --git a/src/config.py b/src/config.py
--- a/src/config.py
+++ b/src/config.py
@@ -2,6 +2,5 @@
 
-import os
-
+WEBHOOK_TOKEN = "whsec_test"
 
 def webhook_token() -> str:
"""

PATH_PATCH = """\
diff --git a/src/export.py b/src/export.py
--- a/src/export.py
+++ b/src/export.py
@@ -6,8 +6,5 @@
 def read_export_file(repo_root: str | Path, user_path: str) -> str:
-    base = Path(repo_root).resolve()
-    target = (base / user_path).resolve()
-    if not str(target).startswith(str(base)):
-        raise ValueError("path escapes repository root")
-    return target.read_text(encoding="utf-8")
+    path = Path(repo_root) / user_path
+    return path.read_text(encoding="utf-8")
"""


def test_detects_percent_scaling_regression() -> None:
    parsed = parse_unified_diff(DISCOUNT_PATCH)
    payloads = regression_finding_payloads(parsed)
    assert any("Percent discount scaling" in p["title"] for p in payloads)


def test_detects_money_display_regression() -> None:
    parsed = parse_unified_diff(MONEY_PATCH)
    payloads = regression_finding_payloads(parsed)
    assert any("Money display" in p["title"] for p in payloads)


def test_detects_shell_true() -> None:
    parsed = parse_unified_diff(SHELL_PATCH)
    payloads = regression_finding_payloads(parsed)
    assert any("shell=True" in p["title"] for p in payloads)


def test_detects_hardcoded_secret() -> None:
    parsed = parse_unified_diff(SECRET_PATCH)
    payloads = regression_finding_payloads(parsed)
    assert any("Hardcoded secret" in p["title"] for p in payloads)


def test_detects_path_escape_regression() -> None:
    parsed = parse_unified_diff(PATH_PATCH)
    payloads = regression_finding_payloads(parsed)
    assert any("Path escape" in p["title"] for p in payloads)


def test_regression_payloads_validate_against_their_diff() -> None:
    parsed = parse_unified_diff(DISCOUNT_PATCH)
    payloads = regression_finding_payloads(parsed)
    findings = [finding_with_fingerprint(raw) for raw in payloads]
    result = validate_findings(findings, parsed)
    assert result.accepted
    assert not result.rejected