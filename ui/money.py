"""Money helpers: safe dollars <-> integer cents (no Streamlit imports)."""
from __future__ import annotations

import re
from decimal import Decimal

MAX_CENTS = 100_000_000
_AMOUNT = re.compile(r"^\d{1,9}(\.\d{1,2})?$")


def parse_cents(text: str) -> int:
    """Parse '12', '12.5', '$1,234.50' into cents. Raises ValueError on bad input."""
    cleaned = text.strip().removeprefix("$").replace(",", "").strip()
    if not _AMOUNT.match(cleaned):
        raise ValueError("Enter an amount like 45 or 45.20 (no negatives or letters).")
    cents = int(Decimal(cleaned) * 100)
    if cents > MAX_CENTS:
        raise ValueError("That amount is too large.")
    return cents


def format_cents(cents: int) -> str:
    return f"${cents / 100:,.2f}"
