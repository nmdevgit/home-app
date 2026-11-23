from datetime import UTC, date, datetime, timedelta

from core.repo import Task
from ui.grouping import bucket_of, filter_tasks, group_by_owner

TODAY = date(2026, 1, 10)


def make(title: str, due: date | None, assignee: str = "either", status: str = "open") -> Task:
    return Task(title, title, "", assignee, due, "none", status, "nick",  # type: ignore[arg-type]
                datetime.now(UTC), None)


def test_buckets() -> None:
    assert bucket_of(make("a", TODAY - timedelta(days=1)), TODAY) == "overdue"
    assert bucket_of(make("a", TODAY), TODAY) == "today"
    assert bucket_of(make("a", TODAY + timedelta(days=7)), TODAY) == "upcoming"
    assert bucket_of(make("a", TODAY + timedelta(days=8)), TODAY) is None
    assert bucket_of(make("a", None), TODAY) is None
    assert bucket_of(make("a", TODAY, status="done"), TODAY) is None


def test_grouping_and_filter() -> None:
    tasks = [make("1", TODAY, "nick"), make("2", TODAY, "natalie"), make("3", TODAY, "either")]
    groups = group_by_owner(tasks, "nick")
    assert [len(groups[k]) for k in ("mine", "partner", "either")] == [1, 1, 1]
    assert len(filter_tasks(tasks, "nick", True, False)) == 2
    assert len(filter_tasks(tasks, "nick", False, False)) == 3
    assert filter_tasks(tasks, "nick", False, True) == []
