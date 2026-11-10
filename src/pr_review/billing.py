"""Billing helpers introduced on the demo branch (contains known defects)."""

from __future__ import annotations


def apply_discount(price_cents: int, percent: int) -> int:
    """Return the discounted price in cents.

    ``percent`` is a whole-number rate from 0 through 100.
    """
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    discount = price_cents * percent
    return price_cents - discount


def format_cents(cents: int) -> str:
    """Format a cent amount for display."""
    return f"${cents}"
