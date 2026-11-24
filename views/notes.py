"""Notes page: pinned-first shared notes with add/edit/pin/archive."""
from __future__ import annotations

import streamlit as st

from core.repo import Note, Repository
from ui import state, theme
from ui.common import archive_item, confirm_delete, load, run, show_flash

LIMIT = 200


def _add(repo: Repository) -> None:
    get = st.session_state.get
    if run(repo.add_note, get("n_title", ""), get("n_body", ""), bool(get("n_pin")),
           ok="Note added."):
        st.session_state["n_title"] = ""
        st.session_state["n_body"] = ""
        st.session_state["n_pin"] = False


def _save(repo: Repository, note_id: str) -> None:
    get = st.session_state.get
    run(repo.update_note, note_id, title=get(f"ne_{note_id}_t", ""),
        body=get(f"ne_{note_id}_b", ""), pinned=bool(get(f"ne_{note_id}_p")), ok="Note saved.")


def _toggle_pin(repo: Repository, note: Note) -> None:
    run(repo.update_note, note.id, pinned=not note.pinned)


def _archive(repo: Repository, note_id: str, title: str) -> None:
    archive_item("note", repo.archive_note, note_id, title, "Note archived.")


def _note(repo: Repository, note: Note) -> None:
    with st.container(key=f"card_note_{note.id}"):
        if note.pinned:
            theme.pills(theme.badge("Pinned", "accent"))
        with st.expander(note.title):
            _note_body(repo, note)


def _note_body(repo: Repository, note: Note) -> None:
    if note.body:
        st.write(note.body)
    key = f"ne_{note.id}"
    st.button("Unpin" if note.pinned else "Pin", key=f"{key}_pin", on_click=_toggle_pin,
              args=(repo, note), width="stretch")
    st.text_input("Title", value=note.title, key=f"{key}_t")
    st.text_area("Note", value=note.body, key=f"{key}_b", height=150)
    st.checkbox("Pinned", value=note.pinned, key=f"{key}_p")
    st.button("Save", key=f"{key}_s", type="primary", on_click=_save,
              args=(repo, note.id), width="stretch")
    with st.popover("Archive", width="stretch"):
        st.write("Archive this note? It is hidden, and you can restore it any time.")
        st.button("Yes, archive", key=f"{key}_x", on_click=_archive,
                  args=(repo, note.id, note.title), width="stretch")
    confirm_delete(f"note_{note.id}", repo.delete_note, note.id, what="this note",
                   ok="Note deleted.")


def render() -> None:
    repo = state.current_repo()
    if repo is None:
        return
    st.title("Notes")
    show_flash()
    with st.expander("Add a note"):
        st.text_input("Title", key="n_title")
        st.text_area("Note", key="n_body", height=150)
        st.checkbox("Pin to top", key="n_pin")
        st.button("Add note", type="primary", width="stretch", on_click=_add,
                  args=(repo,), key="n_add")
    notes: list[Note] = load(lambda: repo.list_notes(limit=LIMIT))
    if not notes:
        theme.empty("No notes yet", "Wifi codes, gift ideas, anything worth keeping.")
    for note in notes:
        _note(repo, note)
