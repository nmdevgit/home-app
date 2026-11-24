"""Bills page: due-date list with markers, mark paid, edit, archive, monthly total."""
from __future__ import annotations

from datetime import date

import streamlit as st

from core.repo import Bill, BillRecurrence, Repository
from core.rules import monthly_equivalent_cents
from ui import state, theme
from ui.common import archive_item, confirm_delete, flash, load, run, show_flash, today
from ui.grouping import bill_status
from ui.money import format_cents, parse_cents

RECURRENCES: tuple[BillRecurrence, ...] = ("monthly", "weekly", "fortnightly", "yearly", "none")
TONES = {"overdue": "bad", "soon": "warn", "paid": "ok", "later": "neutral"}
STATUS_TEXT = {"overdue": "Overdue", "soon": "Due soon", "paid": "Paid", "later": ""}
LIMIT = 200


def monthly_total_cents(bills: list[Bill]) -> int:
    """Sum of monthly equivalents of recurring bills."""
    return sum(monthly_equivalent_cents(b.amount_cents, b.recurrence)
               for b in bills if b.recurrence != "none")


def _amount_or_flash(text: str) -> int | None:
    try:
        return parse_cents(text)
    except ValueError as exc:
        flash(str(exc))
        return None


def _add(repo: Repository) -> None:
    get = st.session_state.get
    cents = _amount_or_flash(get("b_amt", ""))
    due = get("b_due")
    if cents is None:
        return
    if not isinstance(due, date):
        flash("Pick a due date.")
        return
    if run(repo.add_bill, get("b_name", ""), cents, due, get("b_rec", "monthly"),
           ok="Bill added."):
        st.session_state["b_name"] = ""
        st.session_state["b_amt"] = ""


def _save(repo: Repository, bill_id: str) -> None:
    get = st.session_state.get
    cents = _amount_or_flash(get(f"be_{bill_id}_a", ""))
    due = get(f"be_{bill_id}_d")
    if cents is None or not isinstance(due, date):
        if cents is not None:
            flash("Pick a due date.")
        return
    run(repo.update_bill, bill_id, name=get(f"be_{bill_id}_n", ""), amount_cents=cents,
        due_date=due, recurrence=get(f"be_{bill_id}_r", "monthly"), ok="Bill saved.")


def _paid(repo: Repository, bill_id: str) -> None:
    run(repo.mark_bill_paid, bill_id, ok="Marked paid.")


def _archive(repo: Repository, bill_id: str, title: str) -> None:
    archive_item("bill", repo.archive_bill, bill_id, title, "Bill archived.")


def _edit(repo: Repository, bill: Bill) -> None:
    key = f"be_{bill.id}"
    st.text_input("Name", value=bill.name, key=f"{key}_n")
    st.text_input("Amount ($)", value=f"{bill.amount_cents / 100:.2f}", key=f"{key}_a")
    st.date_input("Due date", value=bill.due_date, format="YYYY-MM-DD", key=f"{key}_d")
    st.selectbox("Repeats", RECURRENCES, index=RECURRENCES.index(bill.recurrence),
                 key=f"{key}_r")
    st.button("Save", key=f"{key}_s", type="primary", on_click=_save,
              args=(repo, bill.id), width="stretch")
    with st.popover("Archive", width="stretch"):
        st.write("Archive this bill? It is hidden, and you can restore it any time.")
        st.button("Yes, archive", key=f"{key}_x", on_click=_archive,
                  args=(repo, bill.id, bill.name), width="stretch")
    confirm_delete(f"bill_{bill.id}", repo.delete_bill, bill.id, what="this bill",
                   ok="Bill deleted.")


def _bill(repo: Repository, bill: Bill, now: date) -> None:
    status = bill_status(bill.due_date, now, bill.last_paid_on)
    with st.container(key=f"card_bill_{bill.id}"):
        st.write(f"**{bill.name}**  {format_cents(bill.amount_cents)}")
        theme.pills(
            theme.badge(f"Due {bill.due_date:%a %d %b}", TONES[status]),
            theme.badge(STATUS_TEXT[status], TONES[status]) if STATUS_TEXT[status] else "",
        )
        if status != "paid":
            st.button("Mark paid", key=f"bp_{bill.id}", icon=":material/check:",
                      on_click=_paid, args=(repo, bill.id), width="stretch")
        with st.expander("Edit"):
            _edit(repo, bill)


def _add_form(repo: Repository) -> None:
    with st.expander("Add a bill"):
        st.text_input("Name", key="b_name")
        st.text_input("Amount ($)", key="b_amt", placeholder="45.20")
        st.date_input("Due date", value=today(), format="YYYY-MM-DD", key="b_due")
        st.selectbox("Repeats", RECURRENCES, key="b_rec")
        st.button("Add bill", type="primary", width="stretch", on_click=_add,
                  args=(repo,), key="b_add")


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Bills")
    show_flash()
    _add_form(repo)
    bills: list[Bill] = load(lambda: repo.list_bills(limit=LIMIT))
    total = monthly_total_cents(bills)
    st.metric("Monthly total (recurring bills)", format_cents(total))
    if not bills:
        theme.empty("No bills yet", "Add one above to see what is due and when.")
    now = today()
    for bill in sorted(bills, key=lambda b: (b.due_date, b.name.lower())):
        _bill(repo, bill, now)
