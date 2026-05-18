"""Tests for the gold/silver/bronze fill applied to the top-3 cheapest
suppliers per material in the single-list Excel export.

The price-matrix export already highlights the per-row min — this is the
flat list users get from `/api/export/excel`. Reading the workbook back
verifies that ranks 1/2/3 each receive their colour and rank 4+ stay clean.
"""

from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import openpyxl

from routes.exports import _build_excel, _MEDAL_FILLS


def _read(results, label="t"):
    data, _ = _build_excel(results, label)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    header = [c.value for c in ws[1]]
    return ws, header


def _row_fill(ws, row_idx):
    return ws.cell(row=row_idx, column=1).fill.fgColor.rgb


def _expected_rgb(rank):
    # openpyxl normalises 6-char hex to 'FFxxxxxx' (alpha prefix). Match that.
    bg = _MEDAL_FILLS[rank][0]
    return f"00{bg}"


def test_top_three_get_gold_silver_bronze_fills():
    results = [
        {"item_label": "Анкер", "name": "A1", "supplier": "X", "price": 50, "currency": "UAH"},
        {"item_label": "Анкер", "name": "A2", "supplier": "Y", "price": 60, "currency": "UAH"},
        {"item_label": "Анкер", "name": "A3", "supplier": "Z", "price": 55, "currency": "UAH"},
        {"item_label": "Анкер", "name": "A4", "supplier": "W", "price": 70, "currency": "UAH"},
    ]
    ws, _ = _read(results)
    # Row 2 = 50 (gold), row 3 = 60 (bronze), row 4 = 55 (silver), row 5 = 70 (no medal)
    assert _row_fill(ws, 2) == _expected_rgb(1)
    assert _row_fill(ws, 4) == _expected_rgb(2)
    assert _row_fill(ws, 3) == _expected_rgb(3)
    # 4th place: openpyxl returns '00000000' for the default no-fill cell.
    assert _row_fill(ws, 5) in ("00000000", None, "00FFFFFF")


def test_tied_prices_share_a_rank():
    # Two suppliers tied at 100 should both wear gold; the third (120) wears
    # silver. Bronze stays empty for this group.
    results = [
        {"item_label": "Цемент", "name": "C1", "supplier": "A", "price": 100, "currency": "UAH"},
        {"item_label": "Цемент", "name": "C2", "supplier": "B", "price": 100, "currency": "UAH"},
        {"item_label": "Цемент", "name": "C3", "supplier": "C", "price": 120, "currency": "UAH"},
    ]
    ws, _ = _read(results)
    assert _row_fill(ws, 2) == _expected_rgb(1)
    assert _row_fill(ws, 3) == _expected_rgb(1)
    assert _row_fill(ws, 4) == _expected_rgb(2)


def test_groups_are_ranked_independently():
    # Cement at 200 still gets gold within its own group, even though it's
    # more expensive than the entire Anchor group.
    results = [
        {"item_label": "Анкер",  "name": "A", "supplier": "X", "price": 50, "currency": "UAH"},
        {"item_label": "Цемент", "name": "C", "supplier": "Y", "price": 200, "currency": "UAH"},
    ]
    ws, _ = _read(results)
    assert _row_fill(ws, 2) == _expected_rgb(1)
    assert _row_fill(ws, 3) == _expected_rgb(1)
