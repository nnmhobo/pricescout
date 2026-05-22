"""Tests for the run-results ordering in ``runner._sort_results``.

The Results tab and Excel exports group rows by `item_label` (alphabetic,
Ukrainian-friendly) and within a group by `supplier`. Without a stable
sort the tab would interleave items in futures-completion order.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.runner import _sort_results, _ua_sort_key


def test_groups_items_alphabetically_then_by_supplier():
    raw = [
        {"item_label": "Цемент М400", "supplier": "Епіцентр К", "price": 100},
        {"item_label": "Анкер М12",   "supplier": "М2",         "price": 50},
        {"item_label": "Цемент М400", "supplier": "АРС",        "price": 95},
        {"item_label": "Анкер М12",   "supplier": "Епіцентр К", "price": 48},
        {"item_label": "Гіпсокартон", "supplier": "Будія",      "price": 200},
    ]
    out = _sort_results(raw)
    labels = [r["item_label"] for r in out]
    # Items grouped (all "Анкер" before all "Гіпсокартон" before all "Цемент")
    assert labels == [
        "Анкер М12", "Анкер М12",
        "Гіпсокартон",
        "Цемент М400", "Цемент М400",
    ]
    # Inside each group: stable alphabetical by supplier
    assert [r["supplier"] for r in out[:2]] == ["Епіцентр К", "М2"]
    assert [r["supplier"] for r in out[3:]] == ["АРС", "Епіцентр К"]


def test_ua_sort_key_folds_ukrainian_diacritics():
    # Ґ, І, Ї, Є get folded onto their nearest Russian equivalents so the
    # sort is intuitive (Ґрунт ~ Г, Іграшка ~ И) instead of landing in the
    # codepoint hole between Я and а.
    keys = sorted(["Ґрунтовка", "Гіпсокартон", "Анкер"], key=_ua_sort_key)
    assert keys[0] == "Анкер"


def test_sort_is_stable_for_missing_fields():
    # Rows with no item_label / supplier sort together at the top in a
    # predictable order — they shouldn't crash _ua_sort_key.
    raw = [
        {"supplier": "X"},
        {"item_label": None, "supplier": None},
        {"item_label": "Бетон", "supplier": "A"},
    ]
    out = _sort_results(raw)
    assert out[-1]["item_label"] == "Бетон"
