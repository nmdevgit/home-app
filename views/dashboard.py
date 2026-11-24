"""Today page: greeting + progress, overdue, due today, bills, dinner, needs attention."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from core import clock
from core.errors import RepositoryError
from core.repo import Bill, EventOccurrence, Meal, Repository, Task
from core.rules import expense_balance_cents
from core.stats import points_by_person, streak_days, weekly_leader
from ui import nav, state, theme
from ui.common import load, now_local, show_flash, today
from ui.grouping import bill_status, bucket_of, week_start
from ui.money import format_cents
from ui.taskui import load_subtasks, task_card

ATTENTION_MAX = 5


def greeting(hour: int, name: str) -> str:
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    return f"Good {part}, {name}"


def done_today_count(done: list[Task], now: date) -> int:
    zone = clock.get_zone(state.secret("APP_TZ") or None)
    count = 0
    for task in done:
        if task.completed_at and task.completed_at.astimezone(zone).date() == now:
            count += 1
    return count


def _split(open_tasks: list[Task], now: date) -> tuple[list[Task], list[Task], list[Task]]:
    overdue, due_today, attention = [], [], []
    for task in open_tasks:
        bucket = bucket_of(task, now)
        if bucket == "overdue":
            overdue.append(task)
        elif bucket == "today":
            due_today.append(task)
        elif task.priority == "high":
            attention.append(task)
    return overdue, due_today, attention[:ATTENTION_MAX]


def _task_cards(repo: Repository, tasks: list[Task], prefix: str, now: date) -> None:
    subs = load_subtasks(repo, tasks)
    for task in sorted(tasks, key=lambda t: (t.due_date or date.max, t.title.lower())):
        task_card(repo, task, prefix, now, subs.get(task.id, []), details=False)


def _bills_card(repo: Repository, now: date) -> None:
    bills: list[Bill] = load(lambda: repo.list_bills(limit=200))
    horizon = now + timedelta(days=7)
    due = [b for b in bills if b.due_date <= horizon
           and bill_status(b.due_date, now, b.last_paid_on) != "paid"]
    if not due:
        return
    theme.section("Bills due", len(due))
    with st.container(key="card_dash_bills"):
        for bill in sorted(due, key=lambda b: b.due_date):
            st.write(f"**{bill.name}**  {format_cents(bill.amount_cents)}")
            theme.pills(theme.due_badge(bill.due_date, now))


def _dinner_card(repo: Repository, now: date) -> None:
    meals: list[Meal] = load(lambda: repo.list_meals(now, now, limit=20))
    dinners = [m for m in meals if m.slot == "dinner"]
    theme.section("Tonight's dinner")
    with st.container(key="card_dash_dinner"):
        if not dinners:
            st.caption("Nothing planned yet. Add one on the Meals page.")
        for meal in dinners:
            st.write(f"**{meal.title}**")


def _hero_stats(repo: Repository, me: str, now: date, clock_now: datetime) -> list[str]:
    """Streak, weekly points and leader for the hero card (empty list on any failure)."""
    tz = state.secret("APP_TZ") or None
    try:
        members = repo.list_members()
        since = clock_now - timedelta(days=45)
        history = repo.list_done_tasks(since, limit=500)
        person = me if me in ("nick", "natalie") else "nick"
        streak = streak_days(history, members, person, now, tz)  # type: ignore[arg-type]
        points = points_by_person(history, members, week_start(now), tz)
        leader = weekly_leader(history, members, now, tz)
    except RepositoryError:
        return []
    out = [f"{points.get(person, 0)} pts this week"]  # type: ignore[call-overload]
    if streak:
        out.insert(0, f"{streak} day streak")
    if leader:
        out.append("You lead" if leader == me else f"{leader.title()} leads")
    return out


def _tiles(repo: Repository, open_tasks: list[Task], now: date) -> None:
    left = sum(1 for t in open_tasks if t.due_date and t.due_date <= now)
    overdue = sum(1 for t in open_tasks if t.due_date and t.due_date < now)
    bills = load(lambda: repo.list_bills(limit=200))
    due = sum(1 for b in bills if b.due_date <= now + timedelta(days=7)
              and bill_status(b.due_date, now, b.last_paid_on) != "paid")
    balance = expense_balance_cents(load(lambda: repo.list_expenses(limit=500)))
    owed = "Square" if balance == 0 else format_cents(abs(balance))
    theme.tiles([(str(left), "left today", "accent"),
                 (str(overdue), "overdue", "bad" if overdue else "neutral"),
                 (str(due), "bills due", "warn" if due else "neutral"),
                 (owed, "owed" if balance else "expenses", "neutral")])


def _shortcuts() -> None:
    pages = st.session_state.get(nav.PAGES_KEY, {})
    pins = [p for p in state.prefs().pinned if p in pages]
    if not pins:
        return
    with st.container(horizontal=True, key="chips_pins"):
        for path in pins:
            page = pages[path]
            st.page_link(page, label=page.title, icon=page.icon, width="content")


def _coming_up(repo: Repository, now: date) -> None:
    bills: list[Bill] = load(lambda: repo.list_bills(limit=200))
    events: list[EventOccurrence] = load(lambda: repo.upcoming_events(now, 14, 6))
    rows: list[tuple[date, str, str, str]] = [
        (b.due_date, b.name, "Bill", "bad") for b in bills
        if now <= b.due_date <= now + timedelta(days=14)
        and bill_status(b.due_date, now, b.last_paid_on) != "paid"]
    rows += [(o.on, o.event.title, "Event", "natalie") for o in events]
    if not rows:
        return
    theme.section("Coming up", len(rows))
    with st.container(key="card_dash_coming"):
        for day, title, kind, tone in sorted(rows)[:6]:
            st.markdown(f"**{title}**")
            theme.pills(theme.badge(kind, tone), theme.due_badge(day, now))


def _recent(repo: Repository) -> None:
    from views.activity import activity_line, feed

    items = feed(repo, 5, days=7)[:5]
    if not items:
        return
    theme.section("Recently")
    with st.container(key="card_dash_recent"):
        for item in items:
            st.markdown(activity_line(item))


def _goal_tile(repo: Repository) -> None:
    goals = load(lambda: repo.list_goals(limit=5))
    if not goals:
        return
    goal = goals[0]
    pct = 100 * goal.saved_cents / goal.target_cents if goal.target_cents else 0
    theme.section("Goal")
    with st.container(key="card_dash_goal"):
        st.markdown(f"**{goal.name}**")
        theme.html_block(theme.bar(pct))
        theme.pills(theme.badge(f"{format_cents(goal.saved_cents)} of "
                                f"{format_cents(goal.target_cents)}", "accent"),
                    theme.badge(f"{pct:.0f}%"))


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    now, clock_now = today(), now_local()
    show_flash()
    open_tasks: list[Task] = load(lambda: repo.list_tasks(include_done=False, limit=300))
    start = datetime.combine(now, datetime.min.time(), tzinfo=clock_now.tzinfo)
    done = load(lambda: repo.list_done_tasks(start, limit=200))
    overdue, due_today, attention = _split(open_tasks, now)
    finished = done_today_count(done, now)
    total = finished + len(overdue) + len(due_today)
    theme.hero2(greeting(clock_now.hour, me.title()), f"{now:%A %d %B %Y}", finished, total, me,
                _hero_stats(repo, me, now, clock_now))
    _tiles(repo, open_tasks, now)
    _shortcuts()
    if overdue:
        theme.section("Overdue", len(overdue), "bad")
        _task_cards(repo, overdue, "dash_over", now)
    theme.section("Due today", len(due_today))
    if due_today:
        _task_cards(repo, due_today, "dash_today", now)
    else:
        theme.empty("Nothing due today", "Enjoy it, or pick something from Tasks.")
    _coming_up(repo, now)
    _dinner_card(repo, now)
    _goal_tile(repo)
    _recent(repo)
    if attention:
        theme.section("Needs attention", len(attention))
        _task_cards(repo, attention, "dash_attn", now)
