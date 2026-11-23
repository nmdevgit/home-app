from __future__ import annotations

from datetime import date

import pytest

from core import rules
from core.errors import ValidationError


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (date(2025, 1, 31), date(2025, 2, 28)),
        (date(2024, 1, 31), date(2024, 2, 29)),  # leap year
        (date(2025, 3, 31), date(2025, 4, 30)),
        (date(2025, 12, 15), date(2026, 1, 15)),  # year rollover
        (date(2025, 5, 10), date(2025, 6, 10)),
    ],
)
def test_monthly_clamps_to_month_end(start: date, expected: date) -> None:
    assert rules.next_due_date(start, "monthly", today=date(2000, 1, 1)) == expected


def test_daily_weekly_and_today_fallback() -> None:
    long_ago = date(2000, 1, 1)
    assert rules.next_due_date(date(2025, 12, 31), "daily", long_ago) == date(2026, 1, 1)
    assert rules.next_due_date(date(2025, 1, 1), "weekly", long_ago) == date(2025, 1, 8)
    assert rules.next_due_date(None, "daily", today=date(2025, 6, 1)) == date(2025, 6, 2)


def test_no_next_for_none() -> None:
    with pytest.raises(ValidationError):
        rules.next_due_date(date(2025, 1, 1), "none")


def test_clock_zone_validation_and_today() -> None:
    from core import clock

    assert isinstance(clock.today("Pacific/Auckland"), date)
    with pytest.raises(ValidationError):
        clock.get_zone("Not/AZone")


def test_roll_forward_when_overdue() -> None:
    today = date(2025, 3, 10)
    assert rules.next_due_date(date(2025, 3, 1), "daily", today) == date(2025, 3, 10)
    assert rules.next_due_date(date(2025, 3, 1), "weekly", today) == date(2025, 3, 15)
    # Anchor day preserved across a short month: Jan 31 + k months.
    jan31 = date(2025, 1, 31)
    assert rules.next_due_date(jan31, "monthly", date(2025, 3, 1)) == date(2025, 3, 31)
    assert rules.next_due_date(jan31, "monthly", date(2025, 2, 1)) == date(2025, 2, 28)


def test_not_rolled_when_in_future() -> None:
    assert rules.next_due_date(date(2025, 3, 20), "weekly", date(2025, 3, 10)) == date(2025, 3, 27)
