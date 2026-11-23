"""Meals page: Mon-Sun week view, add/edit/archive, ingredients to grocery."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from core.repo import Meal, Repository
from ui import state
from ui.common import load, run, run_value, show_flash, today
from ui.grouping import week_start

SLOTS = ("breakfast", "lunch", "dinner")
LIMIT = 100


def _shift_week(days: int) -> None:
    st.session_state["m_week"] = st.session_state["m_week"] + timedelta(days=days)


def _this_week() -> None:
    st.session_state["m_week"] = week_start(today())


def _add(repo: Repository) -> None:
    get = st.session_state.get
    day = get("m_day")
    if not isinstance(day, date):
        st.session_state["_flash"] = [("error", "Pick a day.")]
        return
    ok = run(repo.add_meal, day, get("m_title", ""), get("m_ing", ""), get("m_slot", "dinner"),
             ok="Meal added.")
    if ok:
        st.session_state["m_title"] = ""
        st.session_state["m_ing"] = ""


def _save(repo: Repository, meal_id: str) -> None:
    get = st.session_state.get
    run(repo.update_meal, meal_id, title=get(f"me_{meal_id}_t", ""),
        ingredients=get(f"me_{meal_id}_i", ""), slot=get(f"me_{meal_id}_s", "dinner"),
        ok="Meal saved.")


def _archive(repo: Repository, meal_id: str) -> None:
    run(repo.archive_meal, meal_id, ok="Meal archived.")


def _to_grocery(repo: Repository, meal_id: str) -> None:
    count = run_value(repo.meal_to_grocery, meal_id)
    if count is not None:
        st.toast(f"Added {count} ingredient(s) to the grocery list.")


def _meal(repo: Repository, meal: Meal) -> None:
    st.write(f"**{meal.slot.title()}**: {meal.title}")
    with st.expander("Details / edit"):
        key = f"me_{meal.id}"
        st.text_input("Title", value=meal.title, key=f"{key}_t")
        st.selectbox("Slot", SLOTS, index=SLOTS.index(meal.slot), format_func=str.title,
                     key=f"{key}_s")
        st.text_area("Ingredients (one per line)", value=meal.ingredients, key=f"{key}_i")
        st.button("Save", key=f"{key}_save", type="primary", on_click=_save,
                  args=(repo, meal.id), use_container_width=True)
        if meal.ingredients.strip():
            st.button("Add ingredients to grocery", key=f"{key}_g", on_click=_to_grocery,
                      args=(repo, meal.id), use_container_width=True)
        with st.popover("Archive", use_container_width=True):
            st.write("Archive this meal? It is hidden but kept.")
            st.button("Yes, archive", key=f"{key}_a", on_click=_archive,
                      args=(repo, meal.id), use_container_width=True)


def _add_form(week: date) -> None:
    repo = state.current_repo()
    with st.expander("Add a meal"):
        now = today()
        default = now if week <= now <= week + timedelta(days=6) else week
        st.date_input("Day", value=default, format="YYYY-MM-DD", key="m_day")
        st.selectbox("Meal", SLOTS, index=2, format_func=str.title, key="m_slot")
        st.text_input("Title", key="m_title")
        st.text_area("Ingredients (one per line)", key="m_ing")
        st.button("Add meal", type="primary", use_container_width=True, on_click=_add,
                  args=(repo,), key="m_add")


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Meals")
    show_flash()
    st.session_state.setdefault("m_week", week_start(today()))
    week: date = st.session_state["m_week"]
    prev_col, mid_col, next_col = st.columns(3)
    prev_col.button("Prev", on_click=_shift_week, args=(-7,), use_container_width=True)
    mid_col.button("This week", on_click=_this_week, use_container_width=True)
    next_col.button("Next", on_click=_shift_week, args=(7,), use_container_width=True)
    end = week + timedelta(days=6)
    st.caption(f"{week:%d %b} - {end:%d %b %Y}")
    _add_form(week)
    meals: list[Meal] = load(lambda: repo.list_meals(week, end, limit=LIMIT))
    slot_rank = {s: n for n, s in enumerate(SLOTS)}
    for offset in range(7):
        day = week + timedelta(days=offset)
        st.subheader(f"{day:%A %d %b}")
        todays = sorted((m for m in meals if m.day == day), key=lambda m: slot_rank[m.slot])
        if not todays:
            st.caption("Nothing planned.")
        for meal in todays:
            _meal(repo, meal)
