from __future__ import annotations

from datetime import date

import pytest

from core import clock
from core.sqlite_repo import SqliteRepository


@pytest.fixture()
def repo() -> SqliteRepository:
    return SqliteRepository(":memory:", user_id="nick-id")


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> date:
    """Pin 'today' so recurrence results do not depend on the real date."""
    day = date(2025, 1, 1)
    monkeypatch.setattr(clock, "today", lambda tz_name=None: day)
    return day
