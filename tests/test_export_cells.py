"""CSV cells that could run as spreadsheet formulas are neutralised."""
import pytest

from ui.export import _cell


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1+2", "@SUM(A1)", " =1+1", "\tx", "\rx"])
def test_formula_like_cells_get_a_leading_quote(value: str) -> None:
    assert _cell(value).startswith("'")


@pytest.mark.parametrize("value", ["milk", "2026-11-23", "", None, 42])
def test_plain_cells_unchanged(value: object) -> None:
    assert _cell(value) == ("" if value is None else str(value))
