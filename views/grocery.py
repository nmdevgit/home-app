"""Grocery list: quick add, aisle sections, frequent chips, saved lists, edit, archive."""
from __future__ import annotations

import streamlit as st

from core import rules
from core.errors import RepositoryError
from core.quickadd import parse_quick_grocery
from core.repo import GroceryItem, Repository, Template
from ui import state, theme
from ui.common import confirm_delete, friendly, load, run, run_value, set_undo, show_flash
from ui.grouping import CATEGORY_ORDER, group_grocery
from ui.money import format_cents, parse_cents

LIMIT = 300


def _add(repo: Repository) -> None:
    text = str(st.session_state.get("g_name", "")).strip()
    if not text:
        return
    try:
        parsed = parse_quick_grocery(text)
    except (RepositoryError, ValueError) as exc:
        st.session_state["_flash"] = [("error", f"Could not read that: {exc}")]
        return
    # Adding is never blocked: an identical active item just gets another line.
    try:
        dupe = any(i.name.lower() == parsed.name.lower() and not i.checked
                   for i in repo.list_grocery(limit=LIMIT))
    except RepositoryError:
        dupe = False
    note = f"Added {parsed.name}."
    if dupe:
        note = f"Added {parsed.name} (already on the list, added another)."
    if run(repo.add_grocery, parsed.name, parsed.quantity, parsed.category, ok=note):
        st.session_state["g_name"] = ""


def cart_stats(items: list[GroceryItem]) -> tuple[int, int, int]:
    """(in-cart count, total cents of priced in-cart items, in-cart items without a price)."""
    cart = [i for i in items if i.checked]
    missing = sum(i.price_cents is None for i in cart)
    return len(cart), rules.cart_total_cents(items), missing


def _set_price(repo: Repository, item_id: str, key: str) -> None:
    text = str(st.session_state.get(key, "")).strip()
    try:
        cents = parse_cents(text) if text else None
    except ValueError as exc:
        st.session_state["_flash"] = [("error", str(exc))]
        return
    run(repo.set_grocery_price, item_id, cents)


def _cart_bar(items: list[GroceryItem]) -> None:
    count, total, missing = cart_stats(items)
    if not count:
        return
    extra = f" <span>{missing} without price</span>" if missing else ""
    plural = "item" if count == 1 else "items"
    with st.container(key="cartbar"):
        st.markdown(f'<div class="hh-cart"><b>In cart: {count} {plural}</b>'
                    f'<em>{format_cents(total)}</em>{extra}</div>', unsafe_allow_html=True)


def _readd(repo: Repository, key: str) -> None:
    """Frequent-chip callback: key holds 'name' from the pills widget."""
    picked = st.session_state.get(key)
    if not picked:
        return
    cats = st.session_state.get("g_freq_cats", {})
    run(repo.add_grocery, picked, "", cats.get(picked, "other"), ok=f"Added {picked}.")
    st.session_state[key] = None


def _toggle(repo: Repository, item: GroceryItem, key: str) -> None:
    run(repo.set_grocery_checked, item.id, bool(st.session_state.get(key)))


def _archive_checked(repo: Repository) -> None:
    try:
        ids = [i.id for i in repo.list_grocery(limit=LIMIT) if i.checked]
    except RepositoryError:
        ids = []
    if run(repo.archive_checked_grocery, ok="Archived checked items. You can restore them."):
        set_undo("grocery", ids, f"{len(ids)} grocery item(s)")


def _save(repo: Repository, item_id: str) -> None:
    get = st.session_state.get
    run(repo.update_grocery, item_id, name=get(f"ge_{item_id}_n", ""),
        quantity=get(f"ge_{item_id}_q", ""), category=get(f"ge_{item_id}_c", "other"),
        ok="Item saved.")


def _add_saved(repo: Repository) -> None:
    template_id = st.session_state.get("g_tpl")
    if not template_id:
        return
    count = run_value(repo.template_to_grocery, template_id)
    if count is not None:
        st.session_state["_flash"] = [("ok", f"Added {count} item(s) from the saved list.")]


def _frequent(repo: Repository) -> None:
    try:
        freq = repo.frequent_grocery(limit=8)
    except RepositoryError as exc:
        st.error(friendly(exc))
        return
    if not freq:
        return
    st.session_state["g_freq_cats"] = {name: cat for name, cat in freq}
    st.pills("Frequent items", [name for name, _ in freq], key="g_freq", selection_mode="single",
             on_change=_readd, args=(repo, "g_freq"))


def _saved_lists(repo: Repository) -> None:
    templates: list[Template] = load(lambda: repo.list_templates("shopping", limit=50))
    if not templates:
        return
    with st.expander("Add a saved list", icon=":material/playlist_add:"):
        names = {t.id: t.name for t in templates}
        st.selectbox("Saved list", list(names), format_func=names.get, key="g_tpl")
        st.button("Add to grocery list", on_click=_add_saved, args=(repo,),
                  width="stretch", key="g_tpl_add")


def _edit(repo: Repository, item: GroceryItem) -> None:
    key = f"ge_{item.id}"
    st.text_input("Name", value=item.name, key=f"{key}_n")
    st.text_input("Quantity", value=item.quantity, key=f"{key}_q")
    st.selectbox("Aisle", CATEGORY_ORDER, index=CATEGORY_ORDER.index(item.category),
                 format_func=str.title, key=f"{key}_c")
    st.button("Save", key=f"{key}_s", type="primary", on_click=_save,
              args=(repo, item.id), width="stretch")
    confirm_delete(f"gro_{item.id}", repo.delete_grocery, item.id, what=item.name,
                   ok="Item deleted.")


def _item_row(repo: Repository, item: GroceryItem) -> None:
    key = f"g_chk_{item.id}"
    label = f"{item.name} ({item.quantity})" if item.quantity else item.name
    if not item.checked:
        st.checkbox(label, value=False, key=key, on_change=_toggle, args=(repo, item, key))
        return
    with st.container(key=f"prow_{item.id}"):
        left, right = st.columns([3, 2], vertical_alignment="center")
        with left:
            st.checkbox(f"~~{label}~~", value=True, key=key, on_change=_toggle,
                        args=(repo, item, key))
        with right:
            pkey = f"g_price_{item.id}"
            start = "" if item.price_cents is None else f"{item.price_cents / 100:.2f}"
            st.text_input("Price", value=start, key=pkey, placeholder="$ price",
                          label_visibility="collapsed", on_change=_set_price,
                          args=(repo, item.id, pkey))


def _aisle(repo: Repository, category: str, group: list[GroceryItem]) -> None:
    theme.section(category.title(), sum(not i.checked for i in group))
    with st.container(key=f"card_aisle_{category}"):
        for item in group:
            _item_row(repo, item)
        with st.expander("Edit items"):
            for item in group:
                st.caption(item.name)
                _edit(repo, item)


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Grocery")
    show_flash()
    with st.form("grocery_add", clear_on_submit=False, border=False):
        st.text_input("Add item", key="g_name", placeholder="2 milk, bread, 500g mince",
                      label_visibility="collapsed")
        st.form_submit_button("Add", type="primary", icon=":material/add:",
                              width="stretch", on_click=_add, args=(repo,))
    _frequent(repo)
    _saved_lists(repo)
    items: list[GroceryItem] = load(lambda: repo.list_grocery(limit=LIMIT))
    if not items:
        theme.empty("The list is empty", "Type an item above, or add a saved list.")
        return
    to_buy = sum(not i.checked for i in items)
    theme.pills(theme.badge(f"{to_buy} to buy", "accent"),
                theme.badge(f"{len(items) - to_buy} in the trolley", "ok"))
    for category, group in group_grocery(items).items():
        _aisle(repo, category, group)
    _cart_bar(items)
    if any(i.checked for i in items):
        count, total, _ = cart_stats(items)
        worth = f" ({count} in cart, {format_cents(total)})"
        st.button("Archive checked", icon=":material/inventory_2:", on_click=_archive_checked,
                  args=(repo,), width="stretch",
                  help=f"Archive{worth}. Restore from Undo or the Archive page.")
        confirm_delete("gro_checked", repo.delete_checked_grocery,
                       what=f"all checked items{worth}",
                       ok="Deleted checked items.", label="Delete checked")
        st.markdown('<div class="hh-cart-spacer">&nbsp;</div>', unsafe_allow_html=True)
