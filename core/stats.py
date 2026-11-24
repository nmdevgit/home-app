"""Pure chore statistics over Task.completed_by / completed_at (no I/O)."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from core import clock
from core.repo import Person, Task

POINTS: dict[str, int] = {"high": 3, "normal": 2, "low": 1}

PEOPLE: tuple[Person, ...] = ("nick", "natalie")


def _person(task: Task, members: Mapping[str, Person]) -> Person | None:
    if task.status != "done" or task.completed_by is None:
        return None
    return members.get(task.completed_by)


def chores_by_person(tasks: Iterable[Task], members: Mapping[str, Person]) -> dict[Person, int]:
    """Done tasks per person (via completed_by -> members). Both people always present."""
    counts: dict[Person, int] = {p: 0 for p in PEOPLE}
    for task in tasks:
        person = _person(task, members)
        if person is not None:
            counts[person] += 1
    return counts


def week_start(day: date) -> date:
    """Monday of the ISO week containing `day`."""
    return day - timedelta(days=day.weekday())


def weekly_counts(
    tasks: Iterable[Task],
    members: Mapping[str, Person],
    today: date,
    weeks: int = 4,
    tz_name: str | None = None,
) -> list[tuple[date, dict[Person, int]]]:
    """Per ISO week (Monday start, oldest first) chores done per person.

    The last entry is the week containing `today`; `weeks` is clamped to 1..52.
    completed_at is converted to APP_TZ before bucketing; tasks outside the window,
    without completed_at/completed_by, or by unknown users are ignored.
    """
    n = max(1, min(52, int(weeks)))
    zone = clock.get_zone(tz_name)
    first = week_start(today) - timedelta(weeks=n - 1)
    buckets: dict[date, dict[Person, int]] = {
        first + timedelta(weeks=i): {p: 0 for p in PEOPLE} for i in range(n)
    }
    for task in tasks:
        person = _person(task, members)
        if person is None or task.completed_at is None:
            continue
        day = task.completed_at.astimezone(zone).date()
        bucket = buckets.get(week_start(day))
        if bucket is not None:
            bucket[person] += 1
    return list(buckets.items())


def points_by_person(
    tasks: Iterable[Task],
    members: Mapping[str, Person],
    since: date,
    tz_name: str | None = None,
) -> dict[Person, int]:
    """Points (high 3, normal 2, low 1) per person for tasks completed on/after `since`
    (a local APP_TZ calendar day). Both people always present."""
    zone = clock.get_zone(tz_name)
    totals: dict[Person, int] = {p: 0 for p in PEOPLE}
    for task in tasks:
        person = _person(task, members)
        if person is None or task.completed_at is None:
            continue
        if task.completed_at.astimezone(zone).date() >= since:
            totals[person] += POINTS.get(task.priority, 2)
    return totals


def _completion_days(
    tasks: Iterable[Task], members: Mapping[str, Person], person: Person, zone: ZoneInfo
) -> set[date]:
    return {
        t.completed_at.astimezone(zone).date()
        for t in tasks
        if t.completed_at is not None and _person(t, members) == person
    }


def streak_days(
    tasks: Iterable[Task],
    members: Mapping[str, Person],
    person: Person,
    today: date,
    tz_name: str | None = None,
) -> int:
    """Consecutive local days (APP_TZ) ending today with at least one completion by
    `person`. Today is optional: with nothing yet today the streak counts back from
    yesterday, so it does not read 0 first thing in the morning."""
    days = _completion_days(tasks, members, person, clock.get_zone(tz_name))
    day = today if today in days else today - timedelta(days=1)
    count = 0
    while day in days:
        count += 1
        day -= timedelta(days=1)
    return count


def weekly_leader(
    tasks: Iterable[Task],
    members: Mapping[str, Person],
    today: date,
    tz_name: str | None = None,
) -> Person | None:
    """Person with more points in the ISO week containing `today`; None on a tie
    (including 0-0)."""
    pts = points_by_person(list(tasks), members, week_start(today), tz_name)
    if pts["nick"] == pts["natalie"]:
        return None
    return "nick" if pts["nick"] > pts["natalie"] else "natalie"
