"""Tests for the per-result hand-edits (manual_price + comment).

`runner._apply_overrides` is the single integration point: it takes a
fresh list of scrape results, looks up overrides keyed by
(item_id, supplier_id) in the DB, and splices them in. The price is
swapped (with the original preserved on `original_price`) and the
total is recomputed against the new price.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from runner import _apply_overrides


def _mk(item_id, supplier_id, price=100, qty=2):
    return {
        "item_id": item_id,
        "supplier_id": supplier_id,
        "supplier": supplier_id,
        "price": price,
        "qty": qty,
        "total_price": round(price * qty, 2),
        "name": "x",
    }


def test_manual_price_replaces_price_and_recomputes_total():
    raw = [_mk("i1", "s1", price=100, qty=2)]
    overrides = {("i1", "s1"): {"manual_price": 80, "comment": None}}
    with patch("runner.get_result_overrides", return_value=overrides):
        out = _apply_overrides(raw)
    assert out[0]["price"] == 80
    assert out[0]["manual_price"] == 80
    assert out[0]["original_price"] == 100
    assert out[0]["total_price"] == 160  # 80 × 2


def test_comment_only_does_not_touch_price():
    raw = [_mk("i1", "s1", price=100, qty=2)]
    overrides = {("i1", "s1"): {"manual_price": None, "comment": "звірити з постачальником"}}
    with patch("runner.get_result_overrides", return_value=overrides):
        out = _apply_overrides(raw)
    assert out[0]["price"] == 100
    assert out[0].get("manual_price") is None
    assert out[0].get("original_price") is None
    assert out[0]["comment"] == "звірити з постачальником"
    assert out[0]["total_price"] == 200


def test_no_override_passes_results_through():
    raw = [_mk("i1", "s1")]
    with patch("runner.get_result_overrides", return_value={}):
        out = _apply_overrides(raw)
    assert out is raw or out == raw
    assert "manual_price" not in out[0]


def test_only_matching_keys_are_overridden():
    raw = [
        _mk("i1", "s1", price=100),
        _mk("i1", "s2", price=110),  # different supplier — untouched
        _mk("i2", "s1", price=200),  # different item — untouched
    ]
    overrides = {("i1", "s1"): {"manual_price": 50, "comment": None}}
    with patch("runner.get_result_overrides", return_value=overrides):
        out = _apply_overrides(raw)
    assert out[0]["price"] == 50
    assert out[1]["price"] == 110
    assert out[2]["price"] == 200
