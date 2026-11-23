"""Household app entry point: navigation, dev banner, login gate."""
from __future__ import annotations

import streamlit as st

from ui import state, theme
from views import (
    agenda,
    archive,
    bills,
    dashboard,
    expenses,
    grocery,
    login,
    meals,
    notes,
    settings,
    stats,
    tasks,
    templates,
)


def _logout() -> None:
    state.sign_out()


def _sidebar_account() -> None:
    me = state.current_user()
    with st.sidebar:
        st.write(f"Signed in as **{(me or '').title()}**")
        st.button("Log out", on_click=_logout, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Home", page_icon=":house:", layout="centered")
    if state.dev_mode():
        st.warning("DEV MODE: local SQLite data, no cloud, no real login.")
    elif not state.cloud_configured():
        st.error(
            "App is not configured: set SUPABASE_URL, SUPABASE_KEY, NICK_EMAIL and "
            "NATALIE_EMAIL in the app secrets. (For local testing set HOME_APP_DEV=1.)"
        )
        st.stop()
    state.refresh_session()
    theme.inject()
    if state.current_repo() is None:
        st.navigation([st.Page(login.render, title="Sign in", url_path="login")]).run()
        return
    _sidebar_account()
    core_pages = [
        st.Page(dashboard.render, title="Today", icon=":material/today:",
                url_path="today", default=True),
        st.Page(tasks.render, title="Tasks", icon=":material/checklist:", url_path="tasks"),
        st.Page(grocery.render, title="Grocery", icon=":material/shopping_cart:",
                url_path="grocery"),
    ]
    plan_pages = [
        st.Page(agenda.render, title="Agenda", icon=":material/calendar_month:",
                url_path="agenda"),
        st.Page(meals.render, title="Meals", icon=":material/restaurant:", url_path="meals"),
        st.Page(bills.render, title="Bills", icon=":material/receipt_long:", url_path="bills"),
        st.Page(expenses.render, title="Expenses", icon=":material/payments:",
                url_path="expenses"),
    ]
    list_pages = [
        st.Page(templates.render, title="Templates", icon=":material/library_add_check:",
                url_path="templates"),
        st.Page(notes.render, title="Notes", icon=":material/sticky_note_2:", url_path="notes"),
    ]
    more_pages = [
        st.Page(stats.render, title="Stats", icon=":material/bar_chart:", url_path="stats"),
        st.Page(archive.render, title="Archive", icon=":material/inventory_2:",
                url_path="archive"),
        st.Page(settings.render, title="Settings", icon=":material/settings:",
                url_path="settings"),
    ]
    pages = {"": core_pages, "Plan": plan_pages, "Lists": list_pages, "More": more_pages}
    st.navigation(pages).run()


main()
