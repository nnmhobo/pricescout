"""Routing reachability: every registered supplier must be returned by
``get_suppliers_for_item`` for at least one category / label.

Regression for the Будпостач bug: ``budpostach`` sat only in the unused
``HARDWARE_SUPPLIERS`` list, so it was never queried although it was
registered, had a working scraper and a sidebar toggle.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.suppliers import SUPPLIER_REGISTRY
from matching.category_routing import (
    CATEGORY_ROUTING,
    GENERAL_SUPPLIERS,
    get_suppliers_for_item,
)

ALL_IDS = [sid for sid, *_ in SUPPLIER_REGISTRY]


def _reachable() -> set[str]:
    seen: set[str] = set()
    for category in list(CATEGORY_ROUTING) + ["", "Невідома категорія"]:
        seen.update(get_suppliers_for_item({"category": category, "label": ""}, ALL_IDS))
    # label override path (retail keyword)
    seen.update(get_suppliers_for_item({"category": "", "label": "шпаклівка"}, ALL_IDS))
    return seen


def test_every_registered_supplier_is_routable():
    unreachable = set(ALL_IDS) - _reachable()
    assert not unreachable, f"never queried: {sorted(unreachable)}"


def test_budpostach_is_a_general_supplier():
    assert "budpostach" in GENERAL_SUPPLIERS
    routed = get_suppliers_for_item({"category": "Будівельні матеріали", "label": "Цемент"}, ALL_IDS)
    assert "budpostach" in routed


def test_disabled_supplier_is_never_returned():
    enabled = [sid for sid in ALL_IDS if sid != "budpostach"]
    routed = get_suppliers_for_item({"category": "Будівельні матеріали", "label": ""}, enabled)
    assert "budpostach" not in routed
