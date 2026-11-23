"""Household-local 'today'.

Streamlit Cloud runs in UTC, so date.today() is wrong in the evening for the
US (and early morning elsewhere). Everything that needs 'today' goes through here.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.errors import ValidationError

logger = logging.getLogger(__name__)

# Fallback when APP_TZ is not configured; override via the APP_TZ secret.
DEFAULT_TZ = "Australia/Sydney"


def get_zone(name: str | None = None) -> ZoneInfo:
    """Validate an IANA zone name (needs the tzdata package on Windows)."""
    zone_name = (name or DEFAULT_TZ).strip()
    try:
        return ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"unknown timezone {zone_name!r}") from exc


def today(tz_name: str | None = None) -> date:
    return datetime.now(UTC).astimezone(get_zone(tz_name)).date()
