"""Expenses: who paid, running balance, settle up, history, archive."""
from __future__ import annotations

from datetime import date

import streamlit as st

from core.repo import Expense, Repository
from core.rules import expense_balance_cents
from ui import state, theme
from ui.common import LABELS, flash, load, run, show_flash, today
from ui.grouping import partner_of
from ui.money import format_cents, parse_cents

LIMIT = 500
SPLITS = {
    "equal": "Split equally",
    "payer_only": "Only for the payer (no debt)",
    "other_only": "Other person owes all of it",
}
PAYERS = ("nick", "natalie")


def balance_text(balance: int) -> tuple[str, str]:
    """(headline amount, who owes whom). Positive balance = Natalie owes Nick."""
    if balance == 0:
        return "All square", "Nobody owes anything"
    debtor, creditor = ("Natalie", "Nick") if balance > 0 else ("Nick", "Natalie")
    return format_cents(abs(balance)), f"{debtor} owes {creditor}"


def _add(repo: Repository) -> None:
    get = st.session_state.get
    try:
        cents = parse_cents(str(get("x_amt", "")))
    except ValueError as exc:
        flash(str(exc))
        return
    day = get("x_day")
    if not isinstance(day, date):
        flash("Pick a day.")
        return
    if run(repo.add_expense, day, get("x_desc", ""), cents, get("x_payer", "nick"),
           get("x_split", "equal"), ok="Expense added."):
        st.session_state["x_desc"] = ""
        st.session_state["x_amt"] = ""


def _settle(repo: Repository, balance: int) -> None:
    if balance == 0:
        return
    debtor = "natalie" if balance > 0 else "nick"
    run(repo.add_expense, today(), "Settle up", abs(balance), debtor, "equal", "settlement",
        ok="Settled up. Balance is now zero.")


def _archive(repo: Repository, expense_id: str) -> None:
    run(repo.archive_expense, expense_id, ok="Entry archived.")


def _balance_card(repo: Repository, expenses: list[Expense]) -> None:
    balance = expense_balance_cents(expenses)
    amount, who = balance_text(balance)
    with st.container(key="card_balance"):
        theme.html_block(
            f'<div class="hh-balance"><div class="hh-amt">{theme.esc(amount)}</div>'
            f'<div class="hh-who">{theme.esc(who)}</div></div>'
        )
        if balance != 0:
            st.button("Settle up", type="primary", icon=":material/handshake:",
                      key="x_settle", on_click=_settle, args=(repo, balance),
                      use_container_width=True)


def _add_form(repo: Repository, me: str) -> None:
    with st.expander("Add an expense", icon=":material/add:"):
        st.text_input("What was it for?", key="x_desc", placeholder="Groceries")
        st.text_input("Amount ($)", key="x_amt", placeholder="45.20")
        st.selectbox("Who paid?", PAYERS, index=PAYERS.index(me), format_func=LABELS.get,
                     key="x_payer")
        st.selectbox("How is it split?", list(SPLITS), format_func=SPLITS.get, key="x_split")
        st.date_input("Day", value=today(), format="YYYY-MM-DD", key="x_day")
        st.button("Add expense", type="primary", use_container_width=True, on_click=_add,
                  args=(repo,), key="x_add")


def _entry(repo: Repository, exp: Expense) -> None:
    with st.container(key=f"card_exp_{exp.id}"):
        title = "Settlement" if exp.kind == "settlement" else exp.description
        st.write(f"**{title}**  {format_cents(exp.amount_cents)}")
        paid = f"{LABELS[exp.paid_by]} paid" if exp.kind == "expense" else (
            f"{LABELS[exp.paid_by]} paid {LABELS[partner_of(exp.paid_by)]} back")
        theme.pills(theme.person_badge(exp.paid_by), theme.badge(paid),
                    theme.badge(f"{exp.day:%d %b}"),
                    theme.badge(SPLITS[exp.split], "neutral") if exp.kind == "expense" else "")
        with st.popover("Archive", icon=":material/inventory_2:", use_container_width=True):
            st.write("Archive this entry? The balance updates and the entry is kept.")
            st.button("Yes, archive", key=f"xa_{exp.id}", on_click=_archive,
                      args=(repo, exp.id), use_container_width=True)


def render() -> None:
    repo, me = state.current_repo(), state.current_user()
    if repo is None or me is None:
        return
    st.title("Expenses")
    show_flash()
    expenses: list[Expense] = load(lambda: repo.list_expenses(limit=LIMIT))
    _balance_card(repo, expenses)
    _add_form(repo, me)
    theme.section("History", len(expenses))
    if not expenses:
        theme.empty("No expenses yet", "Add one when either of you pays for something shared.")
    for exp in expenses:
        _entry(repo, exp)
