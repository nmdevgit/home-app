"""Templates: reusable shopping lists and recipes."""
from __future__ import annotations

from datetime import date

import streamlit as st

from core.repo import Repository, Template
from ui import state, theme
from ui.common import archive_item, confirm_delete, load, run, run_value, show_flash, today

KINDS = {"shopping": "Shopping lists", "recipe": "Recipes"}
SLOTS = ("breakfast", "lunch", "dinner")
LIMIT = 100


def _add(repo: Repository, kind: str) -> None:
    get = st.session_state.get
    if run(repo.add_template, kind, get("tp_name", ""), get("tp_items", ""),
           ok="Template saved."):
        st.session_state["tp_name"] = ""
        st.session_state["tp_items"] = ""


def _save(repo: Repository, tid: str) -> None:
    get = st.session_state.get
    run(repo.update_template, tid, name=get(f"tp_{tid}_n", ""), items=get(f"tp_{tid}_i", ""),
        ok="Template saved.")


def _archive(repo: Repository, tid: str, title: str) -> None:
    archive_item("template", repo.archive_template, tid, title, "Template archived.")


def _to_grocery(repo: Repository, tid: str) -> None:
    count = run_value(repo.template_to_grocery, tid)
    if count is not None:
        st.session_state["_flash"] = [("ok", f"Added {count} item(s) to the grocery list.")]


def _plan(repo: Repository, tpl: Template) -> None:
    get = st.session_state.get
    day = get(f"tp_{tpl.id}_day")
    if not isinstance(day, date):
        st.session_state["_flash"] = [("error", "Pick a day.")]
        return
    run(repo.add_meal, day, tpl.name, tpl.items, get(f"tp_{tpl.id}_slot", "dinner"),
        ok=f"Planned {tpl.name} for {day:%a %d %b}.")


def _plan_popover(repo: Repository, tpl: Template) -> None:
    with st.popover("Plan this recipe", icon=":material/event:", width="stretch"):
        st.date_input("Day", value=today(), format="YYYY-MM-DD", key=f"tp_{tpl.id}_day")
        st.selectbox("Meal", SLOTS, index=2, format_func=str.title, key=f"tp_{tpl.id}_slot")
        st.button("Add to meal plan", type="primary", key=f"tp_{tpl.id}_plan", on_click=_plan,
                  args=(repo, tpl), width="stretch")


def _card(repo: Repository, tpl: Template) -> None:
    lines = [ln for ln in tpl.items.splitlines() if ln.strip()]
    with st.container(key=f"card_tpl_{tpl.id}"):
        st.write(f"**{tpl.name}**")
        theme.pills(theme.badge(f"{len(lines)} items", "accent"))
        st.button("Add to grocery", icon=":material/shopping_cart:", key=f"tp_{tpl.id}_g",
                  on_click=_to_grocery, args=(repo, tpl.id), width="stretch")
        if tpl.kind == "recipe":
            _plan_popover(repo, tpl)
        with st.expander("Edit"):
            st.text_input("Name", value=tpl.name, key=f"tp_{tpl.id}_n")
            st.text_area("One per line", value=tpl.items, key=f"tp_{tpl.id}_i", height=160)
            st.button("Save changes", type="primary", key=f"tp_{tpl.id}_s", on_click=_save,
                      args=(repo, tpl.id), width="stretch")
            with st.popover("Archive", icon=":material/inventory_2:", width="stretch"):
                st.write("Archive this template? It is hidden, and you can restore it any time.")
                st.button("Yes, archive", key=f"tp_{tpl.id}_x", on_click=_archive,
                          args=(repo, tpl.id, tpl.name), width="stretch")
            confirm_delete(f"tpl_{tpl.id}", repo.delete_template, tpl.id, what="this template",
                           ok="Template deleted.")


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Templates")
    show_flash()
    kind = st.segmented_control("Type", list(KINDS), default="shopping", format_func=KINDS.get,
                                key="tp_kind") or "shopping"
    with st.expander("Create a template", icon=":material/add:"):
        st.text_input("Name", key="tp_name", placeholder="Weekly shop")
        st.text_area("One item per line", key="tp_items", height=140)
        st.button("Save template", type="primary", width="stretch", on_click=_add,
                  args=(repo, kind), key="tp_add")
    templates: list[Template] = load(lambda: repo.list_templates(kind, limit=LIMIT))
    if not templates:
        theme.empty("Nothing saved yet", "Save a list you buy often, or a recipe you cook.")
    for tpl in templates:
        _card(repo, tpl)
