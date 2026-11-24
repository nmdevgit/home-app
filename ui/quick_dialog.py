"""Global quick-add sheet (the "+" in the tab bar): Task / Grocery / Expense / Event."""
from __future__ import annotations

from datetime import date

import streamlit as st

from core.errors import RepositoryError
from core.quickadd import parse_quick_grocery, parse_quick_task
from core.repo import Repository
from ui.common import LABELS, flash, friendly, run, today
from ui.money import parse_cents

KINDS = ("Task", "Grocery", "Expense", "Event")


def _close(message: str) -> None:
    flash(message, "ok")
    st.rerun()


def _task(repo: Repository) -> None:
    text = st.text_input("Task", key="qa_task", placeholder="vacuum friday for natalie !high",
                         label_visibility="collapsed")
    if st.button("Add task", key="qa_task_go", type="primary", width="stretch"):
        try:
            q = parse_quick_task(text, today())
        except (RepositoryError, ValueError) as exc:
            st.error(f"Could not read that: {exc}")
            return
        if run(repo.add_task, q.title, q.assignee, q.due_date, q.recurrence, "", q.priority,
               False):
            _close(f"Added {q.title}.")


def _grocery(repo: Repository) -> None:
    text = st.text_input("Item", key="qa_gro", placeholder="2 milk, bread",
                         label_visibility="collapsed")
    if st.button("Add item", key="qa_gro_go", type="primary", width="stretch"):
        try:
            q = parse_quick_grocery(text)
        except (RepositoryError, ValueError) as exc:
            st.error(f"Could not read that: {exc}")
            return
        if run(repo.add_grocery, q.name, q.quantity, q.category):
            _close(f"Added {q.name}.")


def _expense(repo: Repository, me: str) -> None:
    st.text_input("What for?", key="qa_exp_d", placeholder="Groceries")
    st.text_input("Amount ($)", key="qa_exp_a", placeholder="45.20")
    payers = ("nick", "natalie")
    st.segmented_control("Who paid?", payers, default=me if me in payers else "nick",
                         format_func=LABELS.get, key="qa_exp_p", width="stretch")
    if st.button("Add expense", key="qa_exp_go", type="primary", width="stretch"):
        try:
            cents = parse_cents(str(st.session_state.get("qa_exp_a", "")))
        except ValueError as exc:
            st.error(str(exc))
            return
        paid_by = st.session_state.get("qa_exp_p") or me
        if run(repo.add_expense, today(), st.session_state.get("qa_exp_d", ""), cents, paid_by):
            _close("Expense added.")


def _event(repo: Repository) -> None:
    st.text_input("Title", key="qa_ev_t", placeholder="Dinner with friends")
    st.date_input("Day", value=today(), format="YYYY-MM-DD", key="qa_ev_d")
    st.segmented_control("Who", ("both", "nick", "natalie"), default="both",
                         format_func=str.title, key="qa_ev_w", width="stretch")
    if st.button("Add event", key="qa_ev_go", type="primary", width="stretch"):
        day = st.session_state.get("qa_ev_d")
        if not isinstance(day, date):
            st.error("Pick a day.")
            return
        if run(repo.add_event, st.session_state.get("qa_ev_t", ""), day,
               st.session_state.get("qa_ev_w") or "both"):
            _close("Event added.")


@st.dialog("Quick add")
def quick_add(repo: Repository, me: str) -> None:
    kind = st.segmented_control("Type", KINDS, default="Task", key="qa_kind",
                                width="stretch", label_visibility="collapsed") or "Task"
    try:
        if kind == "Task":
            _task(repo)
        elif kind == "Grocery":
            _grocery(repo)
        elif kind == "Expense":
            _expense(repo, me)
        else:
            _event(repo)
    except RepositoryError as exc:
        st.error(friendly(exc))
