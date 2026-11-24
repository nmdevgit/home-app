"""Round 4 on SupabaseRepository against the in-memory fake client."""
from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from core import rules
from core.errors import NotFoundError, ValidationError
from core.supabase_repo import SupabaseRepository
from tests.test_supabase_repo import FakeClient, FakeQuery

LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


@pytest.fixture()
def client() -> FakeClient:
    c = FakeClient()
    c.stores["household_members"].extend(
        [{"user_id": "nick-id", "name": "nick"}, {"user_id": "nat-id", "name": "natalie"}]
    )
    return c


@pytest.fixture()
def repo(client: FakeClient) -> SupabaseRepository:
    return SupabaseRepository(client, "nick-id")


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rules, "utc_now", lambda: datetime(2025, 1, 1, tzinfo=UTC))


def test_activity(repo: SupabaseRepository, client: FakeClient) -> None:
    t = repo.add_task("Vacuum")
    repo.complete_task(t.id)
    repo.add_grocery("Milk")
    repo.add_expense(date(2025, 1, 1), "Pizza", 100, "nick")
    repo.add_note("Wifi")
    repo.add_event("Dinner", date(2025, 2, 1))
    g = repo.add_goal("Trip", 10_000)
    repo.add_goal_move(g.id, 500, "natalie")
    repo.add_goal_move(g.id, -5, "natalie")
    acts = repo.list_activity(LONG_AGO)
    assert {(a.kind, a.verb) for a in acts} >= {
        ("task", "finished"), ("task", "added"), ("grocery", "added"), ("expense", "paid"),
        ("note", "updated"), ("event", "added"), ("goal", "saved to"),
        ("goal", "withdrew from")}
    assert next(a for a in acts if a.verb == "finished").person == "nick"
    assert next(a for a in acts if a.kind == "goal").title == "Trip"
    assert len(repo.list_activity(LONG_AGO, limit=2)) == 2
    with pytest.raises(ValidationError):
        repo.list_activity(datetime(2000, 1, 1))


def test_search_builds_safe_filters(repo: SupabaseRepository, client: FakeClient) -> None:
    repo.add_task("Fix zebra gate", notes="paint")
    repo.add_grocery("zebra cake")
    repo.add_note("n", body="a zebra")
    repo.add_goal("zebra fund", 5)
    hits = repo.search("zebra")
    assert {h.kind for h in hits} == {"task", "grocery", "note", "goal"}
    assert {h.kind: h.page for h in hits}["note"] == "notes"
    seen_or: list[str] = []
    seen_ilike: list[tuple[str, str]] = []
    orig = FakeQuery.or_

    def spy(self: FakeQuery, expr: str) -> FakeQuery:
        seen_or.append(expr)
        return orig(self, expr)

    FakeQuery.or_ = spy  # type: ignore[method-assign]
    try:
        repo.search('x),id.neq.0,(y*%_\\"zz')
    finally:
        FakeQuery.or_ = orig  # type: ignore[method-assign]
    assert seen_or  # injection text only ever sits inside one quoted value per column
    for expr in seen_or:
        for part in expr.split('",'):
            assert part.count('"') in (1, 2)
        assert "*xid.neq.0yzz*" in expr or "xid.neq.0yzz" in expr
        assert "(" not in expr and ")" not in expr and "\\" not in expr and "%" not in expr
    assert not seen_ilike
    for bad in ("", "a", "x" * 61, ",,,"):
        with pytest.raises(ValidationError):
            repo.search(bad)


def test_search_excludes_archived_and_caps(repo: SupabaseRepository) -> None:
    ids = [repo.add_task(f"cap {i}").id for i in range(12)]
    assert len(repo.search("cap")) == rules.SEARCH_PER_SOURCE
    repo.bulk_archive_tasks(ids)
    assert repo.search("cap") == []


def test_bulk(repo: SupabaseRepository, client: FakeClient) -> None:
    a, b, c = repo.add_task("a"), repo.add_task("b"), repo.add_task("c")
    repo.complete_task(c.id)
    assert repo.bulk_complete_tasks([a.id, c.id, "nope"]) == 1
    assert repo.bulk_update_tasks([a.id, b.id], assignee="natalie", due_date=date(2025, 3, 3)) == 2
    row = next(r for r in client.stores["tasks"] if r["id"] == b.id)
    assert row["assignee"] == "natalie" and row["due_date"] == "2025-03-03"
    with pytest.raises(ValidationError):
        repo.bulk_update_tasks([a.id], title="x")
    repo.add_subtask(b.id, "s")
    assert repo.bulk_archive_tasks([a.id]) == 1
    assert repo.bulk_delete_tasks([a.id, b.id]) == 2
    assert client.stores["subtasks"] == []
    assert repo.bulk_delete_tasks([]) == 0
    with pytest.raises(ValidationError):
        repo.bulk_delete_tasks([str(i) for i in range(51)])


def test_undo_complete(repo: SupabaseRepository, client: FakeClient) -> None:
    t = repo.add_task("bins", recurrence="weekly", due_date=date(2025, 1, 1))
    repo.complete_task(t.id)
    assert len(client.stores["tasks"]) == 2
    back = repo.undo_complete(t.id)
    assert back.status == "open" and [r["id"] for r in client.stores["tasks"]] == [t.id]
    # a touched spawn survives
    repo.complete_task(t.id)
    spawn = next(r for r in client.stores["tasks"] if r["id"] != t.id)
    repo.update_task(spawn["id"], notes="edited")
    repo.undo_complete(t.id)
    assert len(client.stores["tasks"]) == 2
    # a spawn with subtasks survives
    t2 = repo.add_task("mop", recurrence="weekly", due_date=date(2025, 1, 1))
    repo.complete_task(t2.id)
    spawn2 = next(r for r in client.stores["tasks"] if r["title"] == "mop" and r["id"] != t2.id)
    repo.add_subtask(spawn2["id"], "s")
    repo.undo_complete(t2.id)
    assert any(r["id"] == spawn2["id"] for r in client.stores["tasks"])


def test_restores(repo: SupabaseRepository) -> None:
    m = repo.add_meal(date(2025, 1, 1), "m")
    b = repo.add_bill("b", 1, date(2025, 1, 1))
    n = repo.add_note("n")
    e = repo.add_expense(date(2025, 1, 1), "e", 1, "nick")
    tp = repo.add_template("recipe", "t", "x")
    for arch, rest, obj in (
        (repo.archive_meal, repo.restore_meal, m), (repo.archive_bill, repo.restore_bill, b),
        (repo.archive_note, repo.restore_note, n),
        (repo.archive_expense, repo.restore_expense, e),
        (repo.archive_template, repo.restore_template, tp),
    ):
        arch(obj.id)
        assert rest(obj.id).id == obj.id
        with pytest.raises(NotFoundError):
            rest(obj.id)


def test_events(repo: SupabaseRepository, client: FakeClient) -> None:
    ev = repo.add_event("Dentist", date(2025, 3, 3), who="nick", start_time=time(9, 30),
                        remind_days=3)
    assert client.stores["events"][0]["start_time"] == "09:30"
    assert ev.start_time == time(9, 30)
    repo.add_event("birthday", date(2000, 2, 29), recurrence="yearly")
    repo.add_event("gym", date(2025, 1, 1), recurrence="weekly")
    repo.add_event("old", date(2020, 1, 1))
    occ = repo.list_events(date(2025, 1, 1), date(2025, 3, 31))
    pairs = [(o.event.title, o.on) for o in occ]
    assert ("birthday", date(2025, 2, 28)) in pairs and ("Dentist", date(2025, 3, 3)) in pairs
    assert not any(p[0] == "old" for p in pairs)
    assert len([p for p in pairs if p[0] == "gym"]) == 13
    assert [p[1] for p in pairs] == sorted(p[1] for p in pairs)
    assert [o.event.title for o in repo.upcoming_events(date(2025, 3, 1), days=5)] == [
        "Dentist", "gym"]
    up = repo.update_event(ev.id, title="Dentist 2", start_time=None)
    assert up.title == "Dentist 2" and up.start_time is None
    repo.archive_event(ev.id)
    with pytest.raises(NotFoundError):
        repo.update_event(ev.id, title="x")
    assert repo.restore_event(ev.id).id == ev.id
    repo.delete_event(ev.id)
    with pytest.raises(NotFoundError):
        repo.delete_event(ev.id)
    with pytest.raises(ValidationError):
        repo.add_event("x", date(2025, 1, 1), remind_days=99)


def test_goals(repo: SupabaseRepository, client: FakeClient) -> None:
    g = repo.add_goal("Holiday", 100_000, date(2025, 12, 1), "holiday")
    other = repo.add_goal("Car", 5000)
    m1 = repo.add_goal_move(g.id, 5000, "nick", "first")
    repo.add_goal_move(g.id, -1000, "natalie")
    repo.add_goal_move(other.id, 7, "nick")
    assert client.stores["goal_moves"][0]["day"] == "2025-01-01"
    saved = {x.name: x.saved_cents for x in repo.list_goals()}
    assert saved == {"Holiday": 4000, "Car": 7}
    assert next(m.amount_cents for m in repo.list_goal_moves(g.id)) in (5000, -1000)
    up = repo.update_goal(g.id, target_cents=200_000, icon="car")
    assert up.saved_cents == 4000 and up.target_cents == 200_000
    repo.delete_goal_move(m1.id)
    assert repo.list_goals()[0].saved_cents == -1000
    for args in ((0, "nick"), (5, "bob"), (True, "nick")):
        with pytest.raises(ValidationError):
            repo.add_goal_move(g.id, *args)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        repo.add_goal_move("missing", 5, "nick")
    repo.delete_goal(g.id)
    assert all(r["goal_id"] != g.id for r in client.stores["goal_moves"])
    with pytest.raises(NotFoundError):
        repo.delete_goal(g.id)


def test_goal_sum_pages_past_1000(repo: SupabaseRepository, client: FakeClient) -> None:
    g = repo.add_goal("big", 10**9)
    client.stores["goal_moves"].extend(
        {"id": f"m{i:05d}", "goal_id": g.id, "amount_cents": 1, "created_at": f"t{i:05d}"}
        for i in range(2500)
    )
    assert repo.list_goals()[0].saved_cents == 2500


def test_prefs(repo: SupabaseRepository, client: FakeClient) -> None:
    assert repo.get_prefs().accent == "teal"
    p = repo.save_prefs(accent="violet", pinned=["tasks", "goals"])
    assert client.stores["user_prefs"][0]["pinned"] == "tasks,goals"
    assert client.stores["user_prefs"][0]["user_id"] == "nick-id"
    p2 = repo.save_prefs(compact=True)
    assert p2.accent == "violet" and p2.pinned == p.pinned and p2.compact
    assert len(client.stores["user_prefs"]) == 1  # updated, not duplicated
    client.stores["user_prefs"].append({"user_id": "nat-id", "accent": "rose", "pinned": "",
                                        "start_page": "today", "compact": False})
    assert SupabaseRepository(client, "nat-id").get_prefs().accent == "rose"
    assert repo.get_prefs().accent == "violet"
    with pytest.raises(ValidationError):
        repo.save_prefs(pinned=["bad"])


def test_export_and_purge_cover_new_tables(repo: SupabaseRepository, client: FakeClient) -> None:
    ev = repo.add_event("e", date(2025, 1, 1))
    g = repo.add_goal("g", 100)
    keep = repo.add_goal("keep", 100)
    repo.add_goal_move(g.id, 5, "nick")
    repo.add_goal_move(keep.id, 5, "nick")
    assert len(repo.export_rows("events")) == 1 and len(repo.export_rows("goal_moves")) == 2
    assert len(repo.export_rows("goals")) == 2
    repo.archive_event(ev.id)
    repo.archive_goal(g.id)
    assert repo.purge_archived() == 3
    assert [r["name"] for r in client.stores["goals"]] == ["keep"]
    assert len(client.stores["goal_moves"]) == 1
    assert repo.purge_archived() == 0
