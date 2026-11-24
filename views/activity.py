"""Activity feed: who did what, grouped by day."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from core import clock
from core.repo import Activity, Repository
from ui import state, theme
from ui.common import load, now_local, show_flash, today

LIMIT = 100
ICONS = {"task": ":material/checklist:", "grocery": ":material/shopping_cart:",
         "expense": ":material/payments:", "note": ":material/sticky_note_2:",
         "goal": ":material/savings:", "event": ":material/event:"}


def day_label(day: date, now: date) -> str:
    gap = (now - day).days
    if gap == 0:
        return "Today"
    if gap == 1:
        return "Yesterday"
    return f"{day:%A %d %b}"


def activity_line(item: Activity) -> str:
    who = item.person.title() if item.person else "Someone"
    return f"**{who}** {item.verb} {item.title}"


def feed(repo: Repository, limit: int, days: int = 30) -> list[Activity]:
    since = now_local() - timedelta(days=days)
    return load(lambda: repo.list_activity(since, limit=limit))


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Activity")
    show_flash()
    items = feed(repo, LIMIT)
    if not items:
        theme.empty("Nothing yet", "Things you both do will show up here.")
        return
    zone = clock.get_zone(state.secret("APP_TZ") or None)
    now = today()
    current = None
    for n, item in enumerate(items):
        day = item.at.astimezone(zone).date()
        if day != current:
            current = day
            theme.html_block(f'<div class="hh-day">{theme.esc(day_label(day, now))}</div>')
        with st.container(key=f"card_act_{n}"):
            st.markdown(f"{ICONS.get(item.kind, ':material/circle:')} {activity_line(item)}")
