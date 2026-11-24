"""Grocery price_cents: rules helper, SQLite repo (+ old-DB migration), Supabase repo (fake)."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core import rules
from core.errors import NotFoundError, ValidationError
from core.repo import GroceryItem
from core.sqlite_repo import SqliteRepository
from core.supabase_repo import SupabaseRepository
from tests.test_supabase_repo import FakeClient


@pytest.fixture(params=["sqlite", "supabase"])
def repo(request: pytest.FixtureRequest) -> SqliteRepository | SupabaseRepository:
    if request.param == "sqlite":
        return SqliteRepository(":memory:", user_id="u")
    return SupabaseRepository(FakeClient(), "nick-id")


def _item(price: int | None, checked: bool) -> GroceryItem:
    return GroceryItem("i", "n", "", checked, "u", datetime.now(UTC), "other", price)


def test_cart_total_only_checked_priced() -> None:
    items = [_item(250, True), _item(100, False), _item(None, True), _item(0, True)]
    assert rules.cart_total_cents(items) == 250
    assert rules.cart_total_cents([]) == 0


def test_set_price_everywhere(repo: SqliteRepository | SupabaseRepository) -> None:
    g = repo.add_grocery("milk")
    assert g.price_cents is None
    assert repo.set_grocery_price(g.id, 349).price_cents == 349
    assert repo.set_grocery_checked(g.id, True).price_cents == 349
    assert repo.list_grocery()[0].price_cents == 349
    assert repo.update_grocery(g.id, price_cents=500, name="oat milk").price_cents == 500
    repo.archive_checked_grocery()
    assert repo.list_archived_grocery()[0].price_cents == 500
    assert repo.restore_grocery(g.id).price_cents == 500
    assert repo.set_grocery_price(g.id, 0).price_cents == 0
    assert repo.set_grocery_price(g.id, None).price_cents is None
    assert any(r.get("price_cents") is None for r in repo.export_rows("grocery_items"))
    assert "price_cents" in repo.export_rows("grocery_items")[0]


@pytest.mark.parametrize("bad", [-1, 100_000_001, True, 1.5, "5"])
def test_set_price_validates(repo: SqliteRepository | SupabaseRepository, bad: object) -> None:
    g = repo.add_grocery("x")
    with pytest.raises(ValidationError):
        repo.set_grocery_price(g.id, bad)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        repo.update_grocery(g.id, price_cents=bad)
    assert repo.list_grocery()[0].price_cents is None


def test_set_price_missing_id(repo: SqliteRepository | SupabaseRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.set_grocery_price("nope", 100)


def test_max_price_ok(repo: SqliteRepository | SupabaseRepository) -> None:
    g = repo.add_grocery("x")
    assert repo.set_grocery_price(g.id, 100_000_000).price_cents == 100_000_000


def test_sqlite_check_constraint_in_schema() -> None:
    repo = SqliteRepository(":memory:", user_id="u")
    g = repo.add_grocery("x")
    with pytest.raises(sqlite3.IntegrityError):
        repo._conn.execute("UPDATE grocery_items SET price_cents = -5 WHERE id = ?", (g.id,))


def test_sqlite_migrates_old_db_file(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE grocery_items (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "quantity TEXT NOT NULL DEFAULT '', checked INTEGER NOT NULL DEFAULT 0, "
        "added_by TEXT NOT NULL, created_at TEXT NOT NULL, archived_at TEXT, "
        "category TEXT NOT NULL DEFAULT 'other')"
    )
    conn.execute(
        "INSERT INTO grocery_items (id, name, added_by, created_at) "
        "VALUES ('a','old','u','2025-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()
    repo = SqliteRepository(str(path), user_id="u")
    assert repo.list_grocery()[0].price_cents is None
    assert repo.set_grocery_price("a", 99).price_cents == 99
    with pytest.raises(sqlite3.IntegrityError):
        repo._conn.execute("UPDATE grocery_items SET price_cents = 200000000 WHERE id = 'a'")
    SqliteRepository(str(path), user_id="u")  # re-open is idempotent
