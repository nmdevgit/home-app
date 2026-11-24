"""Round 4 on SQLite: activity, search, bulk, undo, restores, events, goals, prefs, purge."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from core import rules
from core.errors import NotFoundError, ValidationError
from core.sqlite_repo import SqliteRepository

LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)

# ---- activity -------------------------------------------------------------------


def test_activity_merges_sources_newest_first(repo: SqliteRepository) -> None:
    t = repo.add_task("Vacuum")
    repo.complete_task(t.id)
    repo.add_grocery("Milk")
    repo.add_expense(date(2025, 1, 1), "Pizza", 2000, "nick")
    repo.add_expense(date(2025, 1, 1), "Back", 500, "nick", kind="settlement")
    repo.add_note("Wifi")
    repo.add_event("Dinner", date(2025, 2, 1))
    g = repo.add_goal("Trip", 10_000)
    repo.add_goal_move(g.id, 500, "natalie")
    repo.add_goal_move(g.id, -100, "natalie")
    acts = repo.list_activity(LONG_AGO)
    pairs = {(a.kind, a.verb) for a in acts}
    assert {("task", "finished"), ("task", "added"), ("grocery", "added"), ("expense", "paid"),
            ("expense", "settled"), ("note", "updated"), ("event", "added"),
            ("goal", "saved to"), ("goal", "withdrew from")} <= pairs
    assert [a.at for a in acts] == sorted((a.at for a in acts), reverse=True)
    goal_act = next(a for a in acts if a.kind == "goal")
    assert goal_act.title == "Trip" and goal_act.person == "natalie"
    assert len(repo.list_activity(LONG_AGO, limit=3)) == 3


def test_activity_since_filter_and_naive_rejected(repo: SqliteRepository) -> None:
    repo.add_task("x")
    assert repo.list_activity(datetime.now(UTC) + timedelta(days=1)) == []
    with pytest.raises(ValidationError):
        repo.list_activity(datetime(2000, 1, 1))


def test_activity_skips_archived(repo: SqliteRepository) -> None:
    t = repo.add_task("gone")
    repo.archive_task(t.id)
    assert repo.list_activity(LONG_AGO) == []


# ---- search -----------------------------------------------------------------------


def test_search_all_sources_and_pages(repo: SqliteRepository) -> None:
    repo.add_task("Fix zebra gate", notes="paint")
    repo.add_grocery("zebra cake")
    repo.add_note("zebra", body="stripes")
    repo.add_meal(date(2025, 1, 1), "zebra stew")
    repo.add_template("shopping", "zebra list", "a")
    repo.add_bill("zebra rent", 1, date(2025, 1, 1))
    repo.add_event("zebra day", date(2025, 1, 1))
    repo.add_goal("zebra fund", 100)
    hits = repo.search("ZEBRA")
    assert {h.kind: h.page for h in hits} == {
        "task": "tasks", "grocery": "grocery", "note": "notes", "meal": "meals",
        "template": "templates", "bill": "bills", "event": "calendar", "goal": "goals"}
    assert [h.snippet for h in hits if h.kind == "task"] == ["paint"]
    assert len(repo.search("zebra", limit=3)) == 3


def test_search_matches_body_notes_and_items(repo: SqliteRepository) -> None:
    repo.add_task("a", notes="needle here")
    repo.add_note("b", body="hay needle")
    repo.add_template("recipe", "c", "needle")
    assert {h.kind for h in repo.search("needle")} == {"task", "note", "template"}


def test_search_excludes_archived_and_caps_per_source(repo: SqliteRepository) -> None:
    ids = [repo.add_task(f"cap {i}").id for i in range(12)]
    assert len(repo.search("cap")) == rules.SEARCH_PER_SOURCE
    repo.bulk_archive_tasks(ids)
    assert repo.search("cap") == []


def test_search_special_chars_are_literal_not_wildcards(repo: SqliteRepository) -> None:
    repo.add_task("100% sure")
    repo.add_task("abc")
    repo.add_task("a_c")
    assert repo.search("a_c") == []  # "_" removed -> "ac" matches nothing, not 'abc'
    assert repo.search("100% su") == []  # "%" removed -> "100 su" is not a substring
    assert [h.title for h in repo.search("sure,(")] == ["100% sure"]
    for bad in ("", "a", "x" * 61, ",,,", "%%"):
        with pytest.raises(ValidationError):
            repo.search(bad)


# ---- bulk -------------------------------------------------------------------------


def test_bulk_complete_counts_only_open_existing(repo: SqliteRepository) -> None:
    a, b = repo.add_task("a"), repo.add_task("b")
    repo.complete_task(b.id)
    assert repo.bulk_complete_tasks([a.id, b.id, "missing"]) == 1
    assert repo.bulk_complete_tasks([]) == 0
    assert repo.list_tasks() == []


def test_bulk_complete_recurring_spawns(repo: SqliteRepository) -> None:
    repo.add_task("bins", recurrence="weekly", due_date=date(2025, 1, 1))
    t = repo.list_tasks()[0]
    repo.bulk_complete_tasks([t.id])
    assert [x.title for x in repo.list_tasks()] == ["bins"]


def test_bulk_update_only_allowed_fields(repo: SqliteRepository) -> None:
    a, b = repo.add_task("a"), repo.add_task("b")
    gone = repo.add_task("c")
    repo.archive_task(gone.id)
    n = repo.bulk_update_tasks([a.id, b.id, gone.id], assignee="natalie", priority="high",
                               due_date=date(2025, 3, 3))
    assert n == 2
    t = repo.list_tasks()
    assert {x.assignee for x in t} == {"natalie"} and {x.priority for x in t} == {"high"}
    for bad in ({"title": "x"}, {}, {"assignee": "bob"}):
        with pytest.raises(ValidationError):
            repo.bulk_update_tasks([a.id], **bad)
    assert repo.bulk_update_tasks([a.id], due_date=None) == 1


def test_bulk_archive_and_delete(repo: SqliteRepository) -> None:
    ids = [repo.add_task(str(i)).id for i in range(4)]
    repo.add_subtask(ids[0], "s")
    assert repo.bulk_archive_tasks(ids[:2]) == 2
    assert repo.bulk_archive_tasks(ids[:2]) == 0  # already archived
    assert repo.bulk_delete_tasks(ids[:3]) == 3  # archived and active both
    assert [t.id for t in repo.list_tasks()] == [ids[3]]
    assert repo.export_rows("subtasks") == []


def test_bulk_max_50(repo: SqliteRepository) -> None:
    ids = [f"x{i}" for i in range(51)]
    for fn in (repo.bulk_complete_tasks, repo.bulk_archive_tasks, repo.bulk_delete_tasks):
        with pytest.raises(ValidationError):
            fn(ids)
    with pytest.raises(ValidationError):
        repo.bulk_update_tasks(ids, priority="low")
    assert repo.bulk_complete_tasks([f"x{i}" for i in range(50)]) == 0


# ---- undo ---------------------------------------------------------------------------


def test_undo_complete_plain_task(repo: SqliteRepository) -> None:
    t = repo.add_task("x")
    repo.complete_task(t.id)
    back = repo.undo_complete(t.id)
    assert back.status == "open" and back.completed_by is None


def test_undo_complete_removes_untouched_spawn(repo: SqliteRepository) -> None:
    t = repo.add_task("bins", recurrence="weekly", due_date=date(2025, 1, 1), assignee="nick",
                      rotate=True)
    repo.complete_task(t.id)
    assert len(repo.list_tasks()) == 1 and repo.list_tasks()[0].assignee == "natalie"
    repo.undo_complete(t.id)
    open_ = repo.list_tasks()
    assert [x.id for x in open_] == [t.id]


def test_undo_complete_keeps_touched_spawn(repo: SqliteRepository) -> None:
    t = repo.add_task("bins", recurrence="weekly", due_date=date(2025, 1, 1))
    repo.complete_task(t.id)
    spawn = next(x for x in repo.list_tasks() if x.id != t.id)
    repo.update_task(spawn.id, notes="edited")
    repo.undo_complete(t.id)
    assert {x.id for x in repo.list_tasks()} == {t.id, spawn.id}


def test_undo_complete_keeps_spawn_with_subtasks_and_preexisting(repo: SqliteRepository) -> None:
    t = repo.add_task("bins", recurrence="weekly", due_date=date(2025, 1, 1))
    repo.complete_task(t.id)
    spawn = next(x for x in repo.list_tasks() if x.id != t.id)
    repo.add_subtask(spawn.id, "s")
    repo.undo_complete(t.id)
    assert len(repo.list_tasks()) == 2
    with pytest.raises(NotFoundError):
        repo.undo_complete("nope")


# ---- restores ----------------------------------------------------------------------


def test_restore_each_kind(repo: SqliteRepository) -> None:
    m = repo.add_meal(date(2025, 1, 1), "m")
    b = repo.add_bill("b", 1, date(2025, 1, 1))
    n = repo.add_note("n")
    e = repo.add_expense(date(2025, 1, 1), "e", 1, "nick")
    tp = repo.add_template("recipe", "t", "x")
    repo.archive_meal(m.id)
    repo.archive_bill(b.id)
    repo.archive_note(n.id)
    repo.archive_expense(e.id)
    repo.archive_template(tp.id)
    assert repo.restore_meal(m.id).id == m.id
    assert repo.restore_bill(b.id).id == b.id
    assert repo.restore_note(n.id).id == n.id
    assert repo.restore_expense(e.id).id == e.id
    assert repo.restore_template(tp.id).id == tp.id
    assert len(repo.list_notes()) == 1 and len(repo.list_templates()) == 1
    for fn, rid in ((repo.restore_meal, m.id), (repo.restore_note, n.id), (repo.restore_bill, "?")):
        with pytest.raises(NotFoundError):  # not archived any more / unknown
            fn(rid)


# ---- events -----------------------------------------------------------------------


def test_event_crud_roundtrip(repo: SqliteRepository) -> None:
    ev = repo.add_event("  Dentist ", date(2025, 3, 3), who="nick", start_time=time(9, 30),
                        notes="bring card", remind_days=3)
    assert ev.title == "Dentist" and ev.start_time == time(9, 30) and ev.remind_days == 3
    up = repo.update_event(ev.id, title="Dentist 2", start_time=None, who="both")
    assert up.start_time is None and up.title == "Dentist 2"
    repo.archive_event(ev.id)
    assert repo.list_events(date(2025, 1, 1), date(2025, 12, 31)) == []
    assert repo.restore_event(ev.id).id == ev.id
    repo.delete_event(ev.id)
    with pytest.raises(NotFoundError):
        repo.delete_event(ev.id)
    with pytest.raises(NotFoundError):
        repo.update_event(ev.id, title="x")


@pytest.mark.parametrize(
    "kwargs",
    [{"title": ""}, {"title": "x" * 121}, {"who": "all"}, {"recurrence": "daily"},
     {"remind_days": 61}, {"remind_days": -1}, {"remind_days": True}, {"notes": "n" * 1001},
     {"start_time": "9:00"}, {"day": "2025-01-01"}],
)
def test_event_validation(repo: SqliteRepository, kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {"title": "t", "day": date(2025, 1, 1)}
    with pytest.raises(ValidationError):
        repo.add_event(**{**base, **kwargs})  # type: ignore[arg-type]


def test_list_events_expands_and_sorts(repo: SqliteRepository) -> None:
    repo.add_event("birthday", date(2000, 2, 29), recurrence="yearly")
    repo.add_event("gym", date(2025, 1, 1), recurrence="weekly", start_time=time(7, 0))
    repo.add_event("rent", date(2024, 11, 15), recurrence="monthly")
    repo.add_event("once", date(2025, 1, 10))
    repo.add_event("past once", date(2024, 1, 10))
    occ = repo.list_events(date(2025, 1, 1), date(2025, 2, 28))
    pairs = [(o.event.title, o.on) for o in occ]
    assert ("birthday", date(2025, 2, 28)) in pairs
    assert ("once", date(2025, 1, 10)) in pairs and not any(p[0] == "past once" for p in pairs)
    assert [p[1] for p in pairs] == sorted(p[1] for p in pairs)
    assert next(p for p in pairs if p[0] == "gym")[1] == date(2025, 1, 1)
    assert len([p for p in pairs if p[0] == "gym"]) == 9
    assert ("rent", date(2025, 2, 15)) in pairs
    assert len(repo.list_events(date(2025, 1, 1), date(2025, 2, 28), limit=4)) == 4


def test_upcoming_events(repo: SqliteRepository) -> None:
    repo.add_event("soon", date(2025, 1, 5))
    repo.add_event("far", date(2025, 6, 5))
    out = repo.upcoming_events(date(2025, 1, 1), days=60, limit=10)
    assert [o.event.title for o in out] == ["soon"]
    with pytest.raises(ValidationError):
        repo.upcoming_events(date(2025, 1, 1), days=0)


# ---- goals -------------------------------------------------------------------------


def test_goal_moves_sum_and_delete(repo: SqliteRepository) -> None:
    g = repo.add_goal(" Holiday ", 100_000, date(2025, 12, 1), "holiday")
    assert g.name == "Holiday" and g.saved_cents == 0
    m1 = repo.add_goal_move(g.id, 5000, "nick", "first")
    repo.add_goal_move(g.id, 2500, "natalie")
    repo.add_goal_move(g.id, -1000, "nick", "oops")
    assert repo.list_goals()[0].saved_cents == 6500
    assert m1.day == date(2025, 1, 1)
    assert [m.amount_cents for m in repo.list_goal_moves(g.id)] == [-1000, 2500, 5000]
    assert len(repo.list_goal_moves(g.id, limit=1)) == 1
    repo.delete_goal_move(m1.id)
    assert repo.list_goals()[0].saved_cents == 1500
    with pytest.raises(NotFoundError):
        repo.delete_goal_move(m1.id)


@pytest.mark.parametrize(
    "args",
    [(0, "nick"), (True, "nick"), (10**9 + 1, "nick"), (-(10**9) - 1, "nick"), (5, "bob")],
)
def test_goal_move_validation(repo: SqliteRepository, args: tuple[object, object]) -> None:
    g = repo.add_goal("g", 100)
    with pytest.raises(ValidationError):
        repo.add_goal_move(g.id, *args)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        repo.add_goal_move(g.id, 5, "nick", "n" * 121)
    with pytest.raises(NotFoundError):
        repo.add_goal_move("missing", 5, "nick")


@pytest.mark.parametrize(
    "kwargs",
    [{"name": ""}, {"name": "n" * 81}, {"target_cents": 0}, {"target_cents": 10**9 + 1},
     {"icon": "rocket"}, {"due_date": "2025-01-01"}],
)
def test_goal_validation(repo: SqliteRepository, kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        repo.add_goal(**{"name": "g", "target_cents": 5, **kwargs})  # type: ignore[arg-type]


def test_goal_update_archive_delete_cascade(repo: SqliteRepository) -> None:
    g = repo.add_goal("g", 100)
    repo.add_goal_move(g.id, 10, "nick")
    up = repo.update_goal(g.id, target_cents=200, due_date=date(2026, 1, 1), icon="car")
    assert (up.target_cents, up.icon, up.saved_cents) == (200, "car", 10)
    repo.archive_goal(g.id)
    assert repo.list_goals() == []
    with pytest.raises(NotFoundError):
        repo.add_goal_move(g.id, 5, "nick")
    repo.delete_goal(g.id)  # archived goals delete too, with their moves
    assert repo.export_rows("goal_moves") == [] and repo.export_rows("goals") == []
    with pytest.raises(NotFoundError):
        repo.delete_goal(g.id)


# ---- prefs -------------------------------------------------------------------------


def test_prefs_defaults_save_and_partial(repo: SqliteRepository) -> None:
    assert repo.get_prefs().accent == "teal" and repo.get_prefs().pinned == ()
    p = repo.save_prefs(accent="violet", pinned=["tasks", "goals"])
    assert (p.accent, p.pinned, p.start_page, p.compact) == ("violet", ("tasks", "goals"),
                                                              "today", False)
    p = repo.save_prefs(compact=True, start_page="tasks")
    assert p.accent == "violet" and p.pinned == ("tasks", "goals") and p.compact
    assert repo.get_prefs() == p
    assert repo.save_prefs(pinned=[]).pinned == ()
    with pytest.raises(ValidationError):
        repo.save_prefs(accent="red")


def test_prefs_are_per_user(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "db.sqlite"
    a, b = SqliteRepository(path, "a"), SqliteRepository(path, "b")
    a.save_prefs(accent="rose")
    assert b.get_prefs().accent == "teal"


# ---- export / purge -----------------------------------------------------------------


def test_export_new_tables_and_purge(repo: SqliteRepository) -> None:
    ev = repo.add_event("e", date(2025, 1, 1), start_time=time(8, 0))
    g = repo.add_goal("g", 100)
    keep = repo.add_goal("keep", 100)
    repo.add_goal_move(g.id, 5, "nick")
    repo.add_goal_move(keep.id, 5, "nick")
    rows = repo.export_rows("events")
    assert rows[0]["start_time"] == "08:00" and rows[0]["day"] == "2025-01-01"
    assert len(repo.export_rows("goal_moves")) == 2
    repo.archive_event(ev.id)
    repo.archive_goal(g.id)
    assert repo.purge_archived() == 3  # event + goal + its move
    assert [x.name for x in repo.list_goals()] == ["keep"]
    assert len(repo.export_rows("goal_moves")) == 1
    assert repo.purge_archived() == 0
