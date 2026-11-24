"""Savings goals: progress cards, quick contribution chips, history, delete."""
from __future__ import annotations

from datetime import date

import streamlit as st

from core.repo import GOAL_ICONS, Goal, GoalMove, Repository
from ui import state, theme
from ui.common import confirm_delete, flash, load, run, show_flash
from ui.money import format_cents, parse_cents

LIMIT = 50
CHIPS = (1000, 5000, 10000)


def percent(goal: Goal) -> float:
    return 100 * goal.saved_cents / goal.target_cents if goal.target_cents else 0.0


def _add_goal(repo: Repository) -> None:
    get = st.session_state.get
    try:
        cents = parse_cents(str(get("go_target", "")))
    except ValueError as exc:
        flash(str(exc))
        return
    due = get("go_due")
    if run(repo.add_goal, get("go_name", ""), cents, due if isinstance(due, date) else None,
           get("go_icon", "savings"), ok="Goal added."):
        for key in ("go_name", "go_target"):
            st.session_state[key] = ""


def _contribute(repo: Repository, goal_id: str, person: str, cents: int) -> None:
    run(repo.add_goal_move, goal_id, cents, person, ok=f"Added {format_cents(abs(cents))}.")


def _custom(repo: Repository, goal_id: str, person: str, sign: int) -> None:
    key = f"go_{goal_id}_amt"
    try:
        cents = parse_cents(str(st.session_state.get(key, "")))
    except ValueError as exc:
        flash(str(exc))
        return
    if run(repo.add_goal_move, goal_id, sign * cents, person, ok="Saved."):
        st.session_state[key] = ""


def _delete_move(repo: Repository, move_id: str) -> None:
    run(repo.delete_goal_move, move_id, ok="Entry removed.")


def _history(repo: Repository, goal: Goal) -> None:
    moves: list[GoalMove] = load(lambda: repo.list_goal_moves(goal.id, limit=30))
    if not moves:
        st.caption("No contributions yet.")
    for move in moves:
        left, right = st.columns([6, 1], vertical_alignment="center", gap="small")
        sign = "+" if move.amount_cents >= 0 else "-"
        left.caption(f"{move.person.title()} {sign}{format_cents(abs(move.amount_cents))} "
                     f"on {move.day:%d %b}")
        right.button("", icon=":material/close:", key=f"go_mv_{move.id}", help="Remove entry",
                     on_click=_delete_move, args=(repo, move.id))


def _card(repo: Repository, goal: Goal, me: str) -> None:
    pct = percent(goal)
    with st.container(key=f"card_goal_{goal.id}"):
        st.markdown(f"**{goal.name}**")
        theme.html_block(theme.bar(pct))
        theme.pills(
            theme.badge(f"{format_cents(goal.saved_cents)} of {format_cents(goal.target_cents)}",
                        "accent"),
            theme.badge(f"{pct:.0f}%", "ok" if pct >= 100 else "neutral"),
            theme.badge(f"By {goal.due_date:%d %b %Y}") if goal.due_date else "",
        )
        with st.container(horizontal=True, key=f"chips_goal_{goal.id}"):
            for cents in CHIPS:
                st.button(f"+${cents // 100}", key=f"go_{goal.id}_{cents}", width="content",
                          on_click=_contribute, args=(repo, goal.id, me, cents))
            with st.popover("Custom", width="content"):
                st.text_input("Amount ($)", key=f"go_{goal.id}_amt", placeholder="25")
                st.button("Add", key=f"go_{goal.id}_add", type="primary", width="stretch",
                          on_click=_custom, args=(repo, goal.id, me, 1))
                st.button("Withdraw", key=f"go_{goal.id}_wd", width="stretch",
                          on_click=_custom, args=(repo, goal.id, me, -1))
        with st.expander("History", icon=":material/history:"):
            _history(repo, goal)
            confirm_delete(f"goal_{goal.id}", repo.delete_goal, goal.id,
                           what="this goal and its history", ok="Goal deleted.")


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    st.title("Goals")
    show_flash()
    with st.expander("New goal", icon=":material/add:"):
        st.text_input("Name", key="go_name", placeholder="Holiday fund")
        st.text_input("Target ($)", key="go_target", placeholder="3000")
        st.date_input("Target date (optional)", value=None, format="YYYY-MM-DD", key="go_due")
        st.selectbox("Icon", GOAL_ICONS, format_func=str.title, key="go_icon")
        st.button("Create goal", type="primary", width="stretch", on_click=_add_goal,
                  args=(repo,), key="go_add")
    goals: list[Goal] = load(lambda: repo.list_goals(limit=LIMIT))
    if not goals:
        theme.empty("No goals yet", "Save towards a holiday, a car or a rainy day.")
    for goal in goals:
        _card(repo, goal, me)
