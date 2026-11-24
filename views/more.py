"""More hub: search box, links to every page that is not in the tab bar, log out."""
from __future__ import annotations

import streamlit as st

from ui import nav, state

SEARCH_KEY = "_search_q"


def _logout() -> None:
    state.sign_out()


def _search(pages: dict[str, st.Page]) -> None:
    with st.form("more_search", border=False, clear_on_submit=True):
        text = st.text_input("Search", key="more_q", placeholder="Search everything",
                             label_visibility="collapsed")
        go = st.form_submit_button("Search", icon=":material/search:", width="stretch")
    if go and text.strip() and "search" in pages:
        st.session_state[SEARCH_KEY] = text.strip()
        st.switch_page(pages["search"])


def render() -> None:
    me = state.current_user()
    st.title("More")
    st.caption(f"Signed in as {(me or '').title()}")
    pages = st.session_state.get(nav.PAGES_KEY, {})
    _search(pages)
    links = [(p, t, i) for p, t, i in nav.more_links() if p in pages and p != "search"]
    for start in range(0, len(links), 2):
        cols = st.columns(2, gap="small")
        for col, (path, title, icon) in zip(cols, links[start:start + 2], strict=False):
            with col, st.container(key=f"card_more_{path}"):
                st.page_link(pages[path], label=title, icon=icon, width="stretch")
    st.button("Log out", on_click=_logout, width="stretch", key="more_logout")
    st.caption(f"App version {nav.APP_VERSION}")
