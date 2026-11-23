"""Grocery list: categories, frequent items, fast add, check off, edit, archive checked."""
from __future__ import annotations

import streamlit as st

from core.repo import GroceryItem, Repository
from ui import state
from ui.common import load, run, show_flash
from ui.grouping import CATEGORY_ORDER, group_grocery

LIMIT = 300


def _add(repo: Repository) -> None:
    name = st.session_state.get("g_name", "").strip()
    if not name:
        return
    qty = st.session_state.get("g_qty", "").strip()
    cat = st.session_state.get("g_cat", "other")
    if run(repo.add_grocery, name, qty, cat):
        st.session_state["g_name"] = ""
        st.session_state["g_qty"] = ""


def _readd(repo: Repository, name: str, category: str) -> None:
    run(repo.add_grocery, name, "", category, ok=f"Added {name}.")


def _toggle(repo: Repository, item: GroceryItem, key: str) -> None:
    run(repo.set_grocery_checked, item.id, bool(st.session_state.get(key)))


def _archive_checked(repo: Repository) -> None:
    run(repo.archive_checked_grocery, ok="Archived checked items.")


def _save(repo: Repository, item_id: str) -> None:
    get = st.session_state.get
    run(repo.update_grocery, item_id, name=get(f"ge_{item_id}_n", ""),
        quantity=get(f"ge_{item_id}_q", ""), category=get(f"ge_{item_id}_c", "other"),
        ok="Item saved.")


def _frequent(repo: Repository) -> None:
    try:
        freq = repo.frequent_grocery(limit=8)
    except Exception as exc:
        st.error(f"Could not load frequent items: {exc}")
        return
    if not freq:
        return
    st.caption("Frequent items (tap to add)")
    for name, cat in freq:
        st.button(f"+ {name}", key=f"gf_{name}", on_click=_readd, args=(repo, name, cat),
                  use_container_width=True)


def _edit(repo: Repository, item: GroceryItem) -> None:
    key = f"ge_{item.id}"
    st.text_input("Name", value=item.name, key=f"{key}_n")
    st.text_input("Quantity", value=item.quantity, key=f"{key}_q")
    st.selectbox("Category", CATEGORY_ORDER, index=CATEGORY_ORDER.index(item.category),
                 format_func=str.title, key=f"{key}_c")
    st.button("Save", key=f"{key}_s", type="primary", on_click=_save,
              args=(repo, item.id), use_container_width=True)


def _item_row(repo: Repository, item: GroceryItem) -> None:
    key = f"g_chk_{item.id}"
    label = f"{item.name} ({item.quantity})" if item.quantity else item.name
    st.checkbox(label, value=item.checked, key=key, on_change=_toggle, args=(repo, item, key))
    with st.expander("Edit", expanded=False):
        _edit(repo, item)


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
        st.selectbox("Category", CATEGORY_ORDER, index=CATEGORY_ORDER.index("other"),
                     format_func=str.title, key="g_cat")
        st.form_submit_button("Add", type="primary", use_container_width=True,
                              on_click=_add, args=(repo,))
    _frequent(repo)
    items: list[GroceryItem] = load(lambda: repo.list_grocery(limit=LIMIT))
    if not items:
        st.info("The list is empty. Add something above.")
        return
    for category, group in group_grocery(items).items():
        st.subheader(category.title())
        for item in group:
            _item_row(repo, item)
    if any(i.checked for i in items):
        st.button("Archive checked", on_click=_archive_checked, args=(repo,),
                  use_container_width=True)
