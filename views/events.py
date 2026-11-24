"""Calendar: shared events and countdowns (week or month list), add / edit / delete."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

import streamlit as st

from core.repo import EventOccurrence, Repository
from ui import state, theme
from ui.common import archive_item, confirm_delete, load, run, show_flash, today
from ui.grouping import week_start

KEY = "ev_anchor"
WHO = ("both", "nick", "natalie")
RECURRENCES = ("none", "weekly", "monthly", "yearly")
LIMIT = 300


def countdown(day: date, now: date) -> str:
    gap = (day - now).days
    if gap < 0:
        return f"{-gap}d ago"
    if gap == 0:
        return "Today"
    if gap == 1:
        return "Tomorrow"
    return f"In {gap} days"


def month_bounds(anchor: date) -> tuple[date, date]:
    last = calendar.monthrange(anchor.year, anchor.month)[1]
    return anchor.replace(day=1), anchor.replace(day=last)


def _shift(view: str, direction: int) -> None:
    anchor: date = st.session_state[KEY]
    if view == "Week":
        st.session_state[KEY] = anchor + timedelta(days=7 * direction)
    else:
        first = anchor.replace(day=1)
        st.session_state[KEY] = (first + timedelta(days=32 if direction > 0 else -1)).replace(day=1)


def _reset() -> None:
    st.session_state[KEY] = today()


def _add(repo: Repository) -> None:
    get = st.session_state.get
    day = get("ev_day")
    if not isinstance(day, date):
        st.session_state["_flash"] = [("error", "Pick a day.")]
        return
    if run(repo.add_event, get("ev_title", ""), day, get("ev_who") or "both", None, "",
           get("ev_rec", "none"), int(get("ev_remind", 0) or 0), ok="Event added."):
        st.session_state["ev_title"] = ""


def _save(repo: Repository, event_id: str) -> None:
    get = st.session_state.get
    day = get(f"ee_{event_id}_d")
    fields: dict[str, object] = {
        "title": get(f"ee_{event_id}_t", ""), "who": get(f"ee_{event_id}_w") or "both",
        "notes": get(f"ee_{event_id}_n", ""), "recurrence": get(f"ee_{event_id}_r", "none"),
        "remind_days": int(get(f"ee_{event_id}_m", 0) or 0),
    }
    if isinstance(day, date):
        fields["day"] = day
    run(repo.update_event, event_id, ok="Event saved.", **fields)


def _archive(repo: Repository, event_id: str, title: str) -> None:
    archive_item("event", repo.archive_event, event_id, title, "Event archived.")


def _card(repo: Repository, occ: EventOccurrence, now: date) -> None:
    ev = occ.event
    soon = "warn" if 0 <= (occ.on - now).days <= 3 else "neutral"
    with st.container(key=f"card_ev_{ev.id}_{occ.on.isoformat()}"):
        st.markdown(f"**{ev.title}**")
        theme.pills(
            theme.badge(f"{occ.on:%a %d %b}", "accent" if occ.on == now else "neutral"),
            theme.badge(countdown(occ.on, now), soon),
            theme.badge(ev.who.title(), ev.who if ev.who != "both" else "either"),
            theme.badge(f"{ev.start_time:%H:%M}") if ev.start_time else "",
            theme.badge(f"Repeats {ev.recurrence}") if ev.recurrence != "none" else "",
        )
        if ev.notes:
            st.caption(ev.notes[:160])
        with st.expander("Edit", icon=":material/more_horiz:"):
            k = f"ee_{ev.id}"
            st.text_input("Title", value=ev.title, key=f"{k}_t")
            st.date_input("First day", value=ev.day, format="YYYY-MM-DD", key=f"{k}_d")
            st.segmented_control("Who", WHO, default=ev.who, format_func=str.title,
                                 key=f"{k}_w", width="stretch")
            st.selectbox("Repeats", RECURRENCES, index=RECURRENCES.index(ev.recurrence),
                         key=f"{k}_r")
            st.number_input("Countdown chip (days ahead)", 0, 60, ev.remind_days, key=f"{k}_m")
            st.text_area("Notes", value=ev.notes, key=f"{k}_n", height=80)
            st.button("Save", key=f"{k}_s", type="primary", width="stretch", on_click=_save,
                      args=(repo, ev.id))
            with st.container(horizontal=True, key=f"chips_{k}"):
                st.button("Archive", key=f"{k}_a", icon=":material/inventory_2:",
                          width="content", on_click=_archive, args=(repo, ev.id, ev.title))
                confirm_delete(f"ev_{ev.id}_{occ.on.isoformat()}", repo.delete_event, ev.id,
                               what="this event (all repeats)", ok="Event deleted.", block=False)


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Calendar")
    show_flash()
    now = today()
    st.session_state.setdefault(KEY, now)
    view = st.segmented_control("View", ["Week", "Month"], default="Week", key="ev_view",
                                width="stretch", label_visibility="collapsed") or "Week"
    anchor: date = st.session_state[KEY]
    if view == "Week":
        start = week_start(anchor)
        end = start + timedelta(days=6)
        label = theme.week_label(start)
    else:
        start, end = month_bounds(anchor)
        label = f"{anchor:%B %Y}"
    with st.container(key="navrow_events"):
        prev_col, mid_col, next_col = st.columns(3)
        prev_col.button("", icon=":material/chevron_left:", key="ev_prev", width="stretch",
                        on_click=_shift, args=(view, -1), help="Previous")
        mid_col.button("Today", key="ev_now", width="stretch", on_click=_reset)
        next_col.button("", icon=":material/chevron_right:", key="ev_next", width="stretch",
                        on_click=_shift, args=(view, 1), help="Next")
    st.caption(label)
    with st.expander("Add an event", icon=":material/add:"):
        st.text_input("Title", key="ev_title", placeholder="Anniversary dinner")
        st.date_input("Day", value=now, format="YYYY-MM-DD", key="ev_day")
        st.segmented_control("Who", WHO, default="both", format_func=str.title, key="ev_who",
                             width="stretch")
        st.selectbox("Repeats", RECURRENCES, key="ev_rec")
        st.number_input("Countdown chip (days ahead)", 0, 60, 0, key="ev_remind")
        st.button("Add event", type="primary", width="stretch", on_click=_add, args=(repo,),
                  key="ev_add")
    occurrences: list[EventOccurrence] = load(lambda: repo.list_events(start, end, limit=LIMIT))
    if not occurrences:
        theme.empty("Nothing on this " + view.lower(), "Add birthdays, trips and dinners.")
    for occ in occurrences:
        _card(repo, occ, now)
