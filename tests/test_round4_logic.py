"""Round 4 pure logic: points/streaks, search sanitiser, event expansion, goal pace, prefs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest

from core import rules, stats
from core.errors import ValidationError
from core.repo import Goal, Task

MEMBERS = {"n": "nick", "t": "natalie"}


def _task(by: str, when: datetime, prio: str = "normal") -> Task:
    return Task("i", "x", "", "either", None, "none", "done", by, when, when, prio, False, by)


def _utc(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


def test_points_by_person_weights_and_since() -> None:
    tasks = [
        _task("n", _utc(2025, 3, 5), "high"), _task("n", _utc(2025, 3, 5), "low"),
        _task("t", _utc(2025, 3, 5)), _task("t", _utc(2025, 2, 1), "high"),
        _task("zz", _utc(2025, 3, 5)),
    ]
    assert stats.points_by_person(tasks, MEMBERS, date(2025, 3, 1)) == {"nick": 4, "natalie": 2}


def test_streak_uses_app_timezone_across_midnight() -> None:
    # 2025-03-05 23:30 UTC is already 03-06 in Sydney (UTC+11): counts as the 6th there.
    tasks = [_task("n", _utc(2025, 3, 5, 23)), _task("n", _utc(2025, 3, 5, 1))]
    assert stats.streak_days(tasks, MEMBERS, "nick", date(2025, 3, 6), "Australia/Sydney") == 2
    assert stats.streak_days(tasks, MEMBERS, "nick", date(2025, 3, 5), "UTC") == 1


def test_streak_today_optional_and_gaps() -> None:
    tasks = [_task("n", _utc(2025, 3, d)) for d in (3, 4, 5)] + [_task("n", _utc(2025, 3, 1))]
    assert stats.streak_days(tasks, MEMBERS, "nick", date(2025, 3, 5), "UTC") == 3
    assert stats.streak_days(tasks, MEMBERS, "nick", date(2025, 3, 6), "UTC") == 3  # not yet today
    assert stats.streak_days(tasks, MEMBERS, "nick", date(2025, 3, 7), "UTC") == 0
    assert stats.streak_days(tasks, MEMBERS, "natalie", date(2025, 3, 5), "UTC") == 0


def test_weekly_leader() -> None:
    mon = date(2025, 3, 3)
    assert stats.weekly_leader([], MEMBERS, mon, "UTC") is None
    t = [_task("t", _utc(2025, 3, 4), "high"), _task("n", _utc(2025, 3, 5))]
    assert stats.weekly_leader(t, MEMBERS, date(2025, 3, 7), "UTC") == "natalie"
    t.append(_task("n", _utc(2025, 3, 5), "low"))
    assert stats.weekly_leader(t, MEMBERS, date(2025, 3, 7), "UTC") is None  # 3-3 tie
    assert stats.weekly_leader(t, MEMBERS, date(2025, 3, 12), "UTC") is None  # next week empty


@pytest.mark.parametrize("bad", ["", " a ", "a", "x" * 61, ",,", "()*%_\\", 5, None])
def test_sanitize_search_rejects(bad: object) -> None:
    with pytest.raises(ValidationError):
        rules.sanitize_search(bad)


def test_sanitize_search_strips_filter_chars() -> None:
    assert rules.sanitize_search("  a,b(c)d*e%f_g\\h\"i  ") == "abcdefghi"
    assert rules.sanitize_search("title.ilike.x),or(id.neq.0") == "title.ilike.xorid.neq.0"


@dataclass
class Ev:
    day: date
    recurrence: str


def test_event_occurrences_basic() -> None:
    assert rules.event_occurrences(Ev(date(2025, 5, 1), "none"), date(2025, 5, 1),
                                   date(2025, 5, 1)) == [date(2025, 5, 1)]
    assert rules.event_occurrences(Ev(date(2025, 5, 1), "none"), date(2025, 5, 2),
                                   date(2025, 6, 1)) == []
    # never before the anchor
    assert rules.event_occurrences(Ev(date(2025, 5, 10), "weekly"), date(2025, 5, 1),
                                   date(2025, 5, 20)) == [date(2025, 5, 10), date(2025, 5, 17)]


def test_event_weekly_and_monthly_expansion() -> None:
    wk = rules.event_occurrences(Ev(date(2020, 1, 1), "weekly"), date(2025, 1, 1),
                                 date(2025, 1, 31))
    assert wk[0] == date(2025, 1, 1) and all((d - date(2020, 1, 1)).days % 7 == 0 for d in wk)
    mo = rules.event_occurrences(Ev(date(2024, 1, 31), "monthly"), date(2025, 1, 15),
                                 date(2025, 4, 30))
    assert mo == [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31), date(2025, 4, 30)]


def test_event_yearly_feb29() -> None:
    ev = Ev(date(2024, 2, 29), "yearly")
    assert rules.event_occurrences(ev, date(2025, 1, 1), date(2028, 12, 31)) == [
        date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29)]
    assert rules.event_occurrences(ev, date(2023, 1, 1), date(2024, 12, 31)) == [date(2024, 2, 29)]


def test_event_expansion_is_bounded() -> None:
    out = rules.event_occurrences(Ev(date(2000, 1, 1), "weekly"), date(2000, 1, 1),
                                  date(9000, 1, 1))
    assert len(out) == rules.MAX_OCCURRENCES
    daily_like = rules.event_occurrences(Ev(date(2000, 1, 1), "yearly"), date(2000, 1, 1),
                                         date(9000, 1, 1))
    assert len(daily_like) == rules.MAX_OCCURRENCES


def _goal(target: int, saved: int, due: date | None) -> Goal:
    return Goal("g", "n", target, due, "savings", saved, "u", _utc(2025, 1, 1))


def test_goal_pace() -> None:
    today = date(2025, 1, 1)
    assert rules.goal_pace(_goal(10_000, 0, date(2025, 1, 29)), today) == 2500  # 4 weeks
    assert rules.goal_pace(_goal(10_000, 0, date(2025, 1, 30)), today) == 2000  # 5 weeks (ceil)
    assert rules.goal_pace(_goal(10_000, 10_000, date(2025, 3, 1)), today) == 0
    assert rules.goal_pace(_goal(10_000, 0, None), today) == 0
    assert rules.goal_pace(_goal(10_000, 4_000, date(2024, 12, 1)), today) == 6000
    assert rules.goal_pace(_goal(100, 0, date(2025, 1, 4)), today) == 100


def test_validate_prefs() -> None:
    ok = rules.validate_prefs({"accent": "rose", "pinned": ["tasks", "tasks", "goals"],
                               "start_page": "tasks", "compact": True})
    assert ok["pinned"] == ("tasks", "goals")
    for bad in ({"accent": "red"}, {"pinned": "tasks"}, {"pinned": ["nope"]},
                {"pinned": ["today", "tasks", "grocery", "agenda", "meals", "bills", "notes"]},
                {"start_page": "x"}, {"compact": 1}, {"other": 1}):
        with pytest.raises(ValidationError):
            rules.validate_prefs(bad)


def test_bulk_ids_and_fields() -> None:
    assert rules.clean_bulk_ids(["a", "b", "a"]) == ["a", "b"]
    with pytest.raises(ValidationError):
        rules.clean_bulk_ids([str(i) for i in range(51)])
    with pytest.raises(ValidationError):
        rules.clean_bulk_ids("abc")
    with pytest.raises(ValidationError):
        rules.validate_bulk_task_fields({"title": "x"})
    with pytest.raises(ValidationError):
        rules.validate_bulk_task_fields({})
