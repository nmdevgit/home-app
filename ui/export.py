"""'Download my data': zip of CSV files built in memory (no temp files)."""
from __future__ import annotations

import csv
import io
import zipfile

from core.repo import EXPORT_TABLES, Repository

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    """Stringify; neutralise spreadsheet formulas so a note cannot run code in Excel."""
    text = "" if value is None else str(value)
    # Check the first non-space character too: " =1+1" is still a formula in some apps.
    return "'" + text if text.lstrip(" ").startswith(_DANGEROUS) else text


def rows_to_csv(rows: list[dict[str, object]]) -> str:
    """CSV text with the union of all keys as header (first-seen order)."""
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(c)) for c in columns])
    return buf.getvalue()


def build_export_zip(repo: Repository) -> bytes:
    """One CSV per EXPORT_TABLES table (archived rows included), zipped in memory."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in EXPORT_TABLES:
            zf.writestr(f"{table}.csv", rows_to_csv(repo.export_rows(table)))
    return out.getvalue()
