"""expense_balance_cents, stats and quick-add parsers."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from core import rules, stats
from core.quickadd import guess_category, parse_quick_grocery, parse_quick_task
from core.repo import Expense, Task


def _e(paid_by: str, cents: int, split: str = "equal", kind: str = "expense") -> Expense:
    return Expense(
        id="i", day=date(2025, 1, 1), description="d", amount_cents=cents, paid_by=paid_by,  # type: ignore[arg-type]
        split=split, kind=kind, created_by="u", created_at=datetime(2025, 1, 1, tzinfo=UTC),  # type: ignore[arg-type]
    )  # fmt: skip


@pytest.mark.parametrize(
    ("expenses", "expected"),
    [
        ([], 0),
        ([_e("nick", 1000)], 500),
        ([_e("natalie", 1000)], -500),
        ([_e("nick", 1001)], 501),  # half rounds up, payer's favour
        ([_e("natalie", 1001)], -501),  # symmetric
        ([_e("nick", 1)], 1),
        ([_e("nick", 1000, "payer_only")], 0),
        ([_e("nick", 1000, "other_only")], 1000),
        ([_e("natalie", 1000, "other_only")], -1000),
        ([_e("nick", 1000, kind="settlement")], 1000),
        ([_e("natalie", 700, kind="settlement")], -700),
        ([_e("nick", 1000, "payer_only", kind="settlement")], 1000),  # split ignored
        ([_e("nick", 1000), _e("natalie", 1000)], 0),
        ([_e("nick", 1000), _e("natalie", 500, "other_only"), _e("nick", 99, "payer_only")], 0),
        ([_e("nick", 2000), _e("natalie", 1000, kind="settlement")], 1000 - 1000),
    ],
)
def test_expense_balance(expenses: list[Expense], expected: int) -> None:
    assert rules.expense_balance_cents(expenses) == expected


def test_balance_settles_to_zero() -> None:
    exps = [_e("nick", 3000), _e("natalie", 1000, "other_only")]
    owed = rules.expense_balance_cents(exps)
    assert owed == 500  # natalie owes nick 1500 - 1000
    assert rules.expense_balance_cents([*exps, _e("natalie", owed, kind="settlement")]) == 0


# ---- stats ----------------------------------------------------------------------

MEMBERS = {"u-nick": "nick", "u-nat": "natalie"}


def _t(by: str | None, at: datetime | None, status: str = "done") -> Task:
    return Task(
        id="t", title="t", notes="", assignee="either", due_date=None, recurrence="none",
        status=status, created_by="u", created_at=datetime(2025, 1, 1, tzinfo=UTC),  # type: ignore[arg-type]
        completed_at=at, completed_by=by,
    )  # fmt: skip


def test_chores_by_person() -> None:
    at = datetime(2025, 1, 6, tzinfo=UTC)
    tasks = [_t("u-nick", at), _t("u-nick", at), _t("u-nat", at), _t(None, at),
             _t("stranger", at), _t("u-nat", None, status="open")]  # fmt: skip
    assert stats.chores_by_person(tasks, MEMBERS) == {"nick": 2, "natalie": 1}
    assert stats.chores_by_person([], MEMBERS) == {"nick": 0, "natalie": 0}
    assert stats.chores_by_person(tasks, {}) == {"nick": 0, "natalie": 0}


def test_weekly_counts_buckets_in_app_tz() -> None:
    today = date(2025, 1, 15)  # Wednesday; ISO week starts Mon 13 Jan
    tasks = [
        _t("u-nick", datetime(2025, 1, 14, 3, tzinfo=UTC)),
        _t("u-nat", datetime(2025, 1, 7, 12, tzinfo=UTC)),
        # 2025-01-12 23:30 UTC is already Mon 13th 10:30 in Sydney -> current week
        _t("u-nat", datetime(2025, 1, 12, 23, 30, tzinfo=UTC)),
        _t("u-nick", datetime(2024, 12, 1, tzinfo=UTC)),  # outside the window
        _t("u-nick", None),
    ]
    weeks = stats.weekly_counts(tasks, MEMBERS, today, weeks=4, tz_name="Australia/Sydney")
    assert [w for w, _ in weeks] == [
        date(2024, 12, 23), date(2024, 12, 30), date(2025, 1, 6), date(2025, 1, 13),
    ]  # fmt: skip
    assert weeks[-1][1] == {"nick": 1, "natalie": 1}
    assert weeks[-2][1] == {"nick": 0, "natalie": 1}
    assert weeks[0][1] == {"nick": 0, "natalie": 0}


def test_weekly_counts_year_rollover_and_clamp() -> None:
    weeks = stats.weekly_counts([], MEMBERS, date(2025, 1, 1), weeks=0, tz_name="UTC")
    assert weeks == [(date(2024, 12, 30), {"nick": 0, "natalie": 0})]
    assert len(stats.weekly_counts([], MEMBERS, date(2025, 1, 1), weeks=999)) == 52


# ---- quick task -----------------------------------------------------------------

TODAY = date(2025, 1, 1)  # a Wednesday


@pytest.mark.parametrize(
    ("text", "title", "due"),
    [
        ("buy milk", "buy milk", None),
        ("bins today", "bins", TODAY),
        ("bins tomorrow", "bins", date(2025, 1, 2)),
        ("Tomorrow: call mum", "call mum", date(2025, 1, 2)),
        ("bins mon", "bins", date(2025, 1, 6)),
        ("bins on Monday", "bins", date(2025, 1, 6)),
        ("bins wed", "bins", date(2025, 1, 8)),  # today is Wed -> next Wed
        ("bins thu", "bins", date(2025, 1, 2)),
        ("bins fri", "bins", date(2025, 1, 3)),
        ("bins SAT", "bins", date(2025, 1, 4)),
        ("bins sunday", "bins", date(2025, 1, 5)),
        ("bins next tuesday", "bins", date(2025, 1, 7)),
        ("bins next week", "bins", date(2025, 1, 8)),
        ("bins next month", "bins", date(2025, 2, 1)),
        ("bins in 3 days", "bins", date(2025, 1, 4)),
        ("bins in 1 day", "bins", date(2025, 1, 2)),
        ("bins in 2 weeks", "bins", date(2025, 1, 15)),
        ("bins in 30 days", "bins", date(2025, 1, 31)),
        ("bins in 45 days", "bins", date(2025, 2, 15)),
        ("bins 15/03", "bins", date(2025, 3, 15)),
        ("bins 5/1", "bins", date(2025, 1, 5)),
        ("bins 1/1", "bins", TODAY),
        ("bins 31/12", "bins", date(2025, 12, 31)),
        ("bins 31/12/2026", "bins", date(2026, 12, 31)),
        ("bins 1/2/26", "bins", date(2026, 2, 1)),
        ("bins 29/02", "bins", date(2028, 2, 29)),  # next leap year
        ("bins 31/04", "bins 31/04", None),
        ("bins 0/5", "bins 0/5", None),
        ("bins 13/13", "bins 13/13", None),
    ],
)
def test_quick_task_dates(text: str, title: str, due: date | None) -> None:
    q = parse_quick_task(text, TODAY)
    assert (q.title, q.due_date) == (title, due)


def test_quick_task_date_rollover_next_year() -> None:
    late = date(2025, 12, 30)
    assert parse_quick_task("x 2/1", late).due_date == date(2026, 1, 2)  # past -> next year
    assert parse_quick_task("x 30/12", late).due_date == late  # today stays this year
    assert parse_quick_task("x in 3 days", late).due_date == date(2026, 1, 2)
    assert parse_quick_task("x tomorrow", date(2025, 12, 31)).due_date == date(2026, 1, 1)
    assert parse_quick_task("x next month", date(2025, 12, 31)).due_date == date(2026, 1, 31)
    assert parse_quick_task("x next month", date(2025, 1, 31)).due_date == date(2025, 2, 28)
    assert parse_quick_task("x 29/2", date(2027, 3, 1)).due_date == date(2028, 2, 29)


def test_quick_task_leap_day() -> None:
    assert parse_quick_task("x 29/02", date(2024, 1, 1)).due_date == date(2024, 2, 29)
    assert parse_quick_task("x tomorrow", date(2024, 2, 28)).due_date == date(2024, 2, 29)
    assert parse_quick_task("x tomorrow", date(2024, 2, 29)).due_date == date(2024, 3, 1)


@pytest.mark.parametrize(
    ("text", "assignee"),
    [("do it for natalie", "natalie"), ("do it FOR Nick", "nick"), ("for natalie do it", "natalie"),
     ("do it", "either"), ("format nickname", "either")],
)  # fmt: skip
def test_quick_task_assignee(text: str, assignee: str) -> None:
    assert parse_quick_task(text, TODAY).assignee == assignee


@pytest.mark.parametrize(
    ("text", "priority"),
    [("a !high", "high"), ("a !urgent", "high"), ("!HIGH a", "high"), ("a !low", "low"),
     ("a !normal", "normal"), ("a", "normal"), ("wow!high", "normal")],
)  # fmt: skip
def test_quick_task_priority(text: str, priority: str) -> None:
    assert parse_quick_task(text, TODAY).priority == priority


@pytest.mark.parametrize(
    ("text", "rec"),
    [("water plants every day", "daily"), ("bins every week", "weekly"),
     ("rent every month", "monthly"), ("Bins EVERY Week", "weekly"), ("weekly shop", "none")],
)  # fmt: skip
def test_quick_task_recurrence(text: str, rec: str) -> None:
    assert parse_quick_task(text, TODAY).recurrence == rec


def test_quick_task_combined() -> None:
    q = parse_quick_task("Take out bins fri for natalie !high every week", TODAY)
    assert q.title == "Take out bins"
    assert (q.assignee, q.priority, q.recurrence) == ("natalie", "high", "weekly")
    assert q.due_date == date(2025, 1, 3)


@pytest.mark.parametrize(
    "text", ["", "   ", "!!!", "today", "tomorrow !high", "for nick", "every day", "\n\t",
             "🙂 emoji", "a" * 5000, "'; DROP TABLE tasks;--", "99999/99/99999", "in 999 days",
             "in 99999999999 days", "1/1/99999", "\x00"],
)  # fmt: skip
def test_quick_task_total(text: str) -> None:
    q = parse_quick_task(text, TODAY)
    assert isinstance(q.title, str) and len(q.title) <= 200


def test_quick_task_empty_after_extraction_keeps_text() -> None:
    assert parse_quick_task("tomorrow", TODAY).title == "tomorrow"
    assert parse_quick_task("tomorrow", TODAY).due_date == date(2025, 1, 2)
    assert parse_quick_task("for nick", TODAY).title == "for nick"
    assert parse_quick_task("", TODAY).title == ""
    assert parse_quick_task(None, TODAY).title == ""  # type: ignore[arg-type]
    assert parse_quick_task("x", None).due_date is None  # type: ignore[arg-type]


def test_quick_task_title_truncated_to_200() -> None:
    assert len(parse_quick_task("a" * 500, TODAY).title) == 200


# ---- quick grocery ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "name", "qty", "cat"),
    [
        ("milk", "milk", "", "dairy"),
        ("2 x milk", "milk", "2", "dairy"),
        ("2x milk", "milk", "2", "dairy"),
        ("milk 2L", "milk", "2l", "dairy"),
        ("milk 2 l", "milk", "2l", "dairy"),
        ("milk x2", "milk", "2", "dairy"),
        ("milk 2", "milk", "2", "dairy"),
        ("3 eggs", "eggs", "3", "dairy"),
        ("2kg apples", "apples", "2kg", "produce"),
        ("500g mince", "mince", "500g", "meat"),
        ("1 dozen eggs", "eggs", "1dozen", "dairy"),
        ("2 packs of pasta", "pasta", "2packs", "pantry"),
        ("1.5L orange juice", "orange juice", "1.5l", "drinks"),
        ("ice cream", "ice cream", "", "frozen"),
        ("peanut butter", "peanut butter", "", "pantry"),
        ("bread", "bread", "", "bakery"),
        ("toilet paper", "toilet paper", "", "household"),
        ("chicken breast", "chicken breast", "", "meat"),
        ("Bananas", "Bananas", "", "produce"),
        ("strawberries", "strawberries", "", "produce"),
        ("frozen peas", "frozen peas", "", "frozen"),
        ("beer", "beer", "", "drinks"),
        ("dragon fruit", "dragon fruit", "", "produce"),
        ("widgets", "widgets", "", "other"),
        ("7up", "7up", "", "other"),
        ("5", "5", "", "other"),
    ],
)
def test_quick_grocery(text: str, name: str, qty: str, cat: str) -> None:
    g = parse_quick_grocery(text)
    assert (g.name, g.quantity, g.category) == (name, qty, cat)


@pytest.mark.parametrize(
    "text", ["", "  ", "x", "2 x", "x2", "2", "-", "🙂", "a" * 1000, "1 " + "b" * 1000, "\x00",
             "99999999999999999999 x y", "1.2.3 milk"],
)  # fmt: skip
def test_quick_grocery_total(text: str) -> None:
    g = parse_quick_grocery(text)
    assert len(g.name) <= 200 and len(g.quantity) <= 100
    assert g.category in rules.GROCERY_CATEGORIES


def test_quick_grocery_non_string() -> None:
    assert parse_quick_grocery(None).name == ""  # type: ignore[arg-type]


def test_guess_category_plurals_and_phrases() -> None:
    assert guess_category("Tomatoes") == "produce"
    assert guess_category("cream cheese") == "dairy"
    assert guess_category("olive oil") == "pantry"
