"""Grocery list: fast add, check off, archive checked."""
from __future__ import annotations

import streamlit as st

from core.repo import GroceryItem, Repository
from ui import state
from ui.common import load, run, show_flash


def _add(repo: Repository) -> None:
    name = st.session_state.get("g_name", "").strip()
    if not name:
        return
    qty = st.session_state.get("g_qty", "").strip()
    if run(repo.add_grocery, name, qty):
        st.session_state["g_name"] = ""
        st.session_state["g_qty"] = ""


def _toggle(repo: Repository, item: GroceryItem, key: str) -> None:
    run(repo.set_grocery_checked, item.id, bool(st.session_state.get(key)))


def _archive_checked(repo: Repository) -> None:
    run(repo.archive_checked_grocery, ok="Archived checked items.")


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Grocery")
    show_flash()
    with st.form("grocery_add", clear_on_submit=False, border=False):
        st.text_input("Add item", key="g_name", placeholder="Milk", label_visibility="collapsed")
        st.text_input("Quantity (optional)", key="g_qty", placeholder="Quantity (optional)",
                      label_visibility="collapsed")
        st.form_submit_button("Add", type="primary", use_container_width=True,
                              on_click=_add, args=(repo,))
    items: list[GroceryItem] = load(repo.list_grocery)
    if not items:
        st.info("The list is empty. Add something above.")
        return
    items.sort(key=lambda i: (i.checked, i.created_at))
    for item in items:
        key = f"g_chk_{item.id}"
        label = f"{item.name} ({item.quantity})" if item.quantity else item.name
        st.checkbox(label, value=item.checked, key=key, on_change=_toggle, args=(repo, item, key))
    if any(i.checked for i in items):
        st.button("Archive checked", on_click=_archive_checked, args=(repo,),
                  use_container_width=True)
