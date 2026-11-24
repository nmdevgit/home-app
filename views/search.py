"""Search everything (tasks, grocery, notes, meals, templates, bills, events, goals)."""
from __future__ import annotations

import streamlit as st

from core.errors import RepositoryError
from core.repo import Repository, SearchHit
from ui import nav, state, theme
from ui.common import friendly, show_flash

KIND_TONE = {"task": "accent", "grocery": "ok", "note": "warn", "meal": "nick", "bill": "bad",
             "event": "natalie", "goal": "ok", "template": "either"}


def _results(repo: Repository, query: str) -> None:
    try:
        hits: list[SearchHit] = repo.search(query, limit=40)
    except RepositoryError as exc:
        st.warning(friendly(exc))
        return
    if not hits:
        theme.empty("No matches", "Try a different word.")
        return
    pages = st.session_state.get(nav.PAGES_KEY, {})
    theme.section("Results", len(hits))
    for hit in hits:
        with st.container(key=f"card_hit_{hit.kind}_{hit.id}"):
            theme.pills(theme.badge(hit.kind.title(), KIND_TONE.get(hit.kind, "neutral")))
            st.markdown(f"**{hit.title}**")
            if hit.snippet:
                st.caption(hit.snippet[:120])
            if hit.page in pages:
                st.page_link(pages[hit.page], label=f"Open {pages[hit.page].title}",
                             icon=":material/arrow_forward:")


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Search")
    show_flash()
    if "_search_q" in st.session_state:
        st.session_state["s_q"] = st.session_state.pop("_search_q")
    query = st.text_input("Search", key="s_q", placeholder="Tasks, notes, bills, goals...",
                          label_visibility="collapsed")
    if len(query.strip()) < 2:
        theme.empty("Search the whole house", "Type at least 2 letters.")
        return
    _results(repo, query)
