"""Stats: chores completed per person (this week and the last 4 weeks)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core.errors import RepositoryError
from core.repo import Person, Repository, Task
from core.stats import (
    chores_by_person,
    points_by_person,
    streak_days,
    weekly_counts,
    weekly_leader,
)
from ui import state, theme
from ui.common import friendly, load, now_local, show_flash, today
from ui.grouping import week_start

WEEKS = 4
LIMIT = 500
FAIR_SHARE = 0.65
COLORS = ["#4263eb", "#d6336c"]


def fairness_note(totals: dict[Person, int]) -> str:
    """A gentle sentence about how evenly the chores were shared."""
    total = sum(totals.values())
    if total < 4:
        return "Not enough completed chores yet to say. Tick a few off and check back."
    top, bottom = sorted(totals, key=lambda p: totals[p], reverse=True)[:2]
    if totals[top] / total > FAIR_SHARE:
        return (f"{top.title()} did {totals[top]} of {total} chores. "
                f"{bottom.title()} could take the next few.")
    return "Chores are shared fairly evenly. Nice teamwork."


def weekly_frame(rows: list[tuple[date, dict[Person, int]]]) -> pd.DataFrame:
    data = {
        "Nick": [counts.get("nick", 0) for _, counts in rows],
        "Natalie": [counts.get("natalie", 0) for _, counts in rows],
    }
    return pd.DataFrame(data, index=[f"{monday:%d %b}" for monday, _ in rows])


def _totals_cards(totals: dict[Person, int]) -> None:
    left, right = st.columns(2)
    left.metric("Nick", totals.get("nick", 0))
    right.metric("Natalie", totals.get("natalie", 0))


def _load_done(repo: Repository) -> list[Task]:
    since = now_local() - timedelta(days=7 * WEEKS + 7)
    return load(lambda: repo.list_done_tasks(since, limit=LIMIT))


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Stats")
    show_flash()
    now = today()
    try:
        members = repo.list_members()
    except RepositoryError as exc:
        st.error(friendly(exc))
        return
    done = _load_done(repo)
    rows = weekly_counts(done, members, now, weeks=WEEKS, tz_name=state.secret("APP_TZ") or None)
    this_week = rows[-1][1] if rows else {}
    tz = state.secret("APP_TZ") or None
    pts = points_by_person(done, members, week_start(now), tz)
    leader = weekly_leader(done, members, now, tz)
    theme.section("Points and streaks")
    theme.tiles([
        (f"{pts['nick']}", "Nick pts this week", "accent"),
        (f"{pts['natalie']}", "Natalie pts this week", "accent"),
        (f"{streak_days(done, members, 'nick', now, tz)}d", "Nick streak", "ok"),
        (f"{streak_days(done, members, 'natalie', now, tz)}d", "Natalie streak", "ok"),
    ])
    if leader:
        theme.pills(theme.person_badge(leader), theme.badge("leads this week", "ok"))
    else:
        theme.pills(theme.badge("All square this week", "neutral"))
    theme.section("Chores done this week")
    _totals_cards(this_week)
    theme.section(f"Last {WEEKS} weeks")
    last = chores_by_person(done, members)
    if sum(last.values()) == 0:
        theme.empty("No completed chores yet", "Finished tasks are counted by who ticked them.")
        return
    st.bar_chart(weekly_frame(rows), color=COLORS, stack=False)
    _totals_cards(last)
    with st.container(key="card_fairness"):
        st.write(fairness_note(last))
