"""Tests for the session-cache key in ``runner``.

The cache must include the active supplier set in its key — otherwise
changing which suppliers are enabled between batches in the same session
would return stale results scraped under a different fan-out.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import runner


def _stub_item():
    return {
        "id": "x1",
        "label": "Цемент М400",
        "search_label": None,
        "category": "Будівельні матеріали",
        "monitorable": True,
        "suppliers": {},
        "qty": None,
        "unit": None,
    }


def _fake_supplier(sid):
    return {
        "id": sid,
        "name": sid,
        "enabled": True,
        "scrape": lambda *a, **kw: (None, None),
    }


def test_session_cache_distinguishes_supplier_sets():
    """A cached result scraped under supplier set {A,B} must not be returned
    when the same item is later scraped with set {A,C}."""
    runner._session_cache.clear()
    runner.item_states = {"x1": {"log": [], "results": [], "done": False, "error": None}}

    item = _stub_item()
    sups_ab = [_fake_supplier("a"), _fake_supplier("b")]
    sups_ac = [_fake_supplier("a"), _fake_supplier("c")]

    # Prime cache for set {a, b}
    with patch("core.runner.get_item", return_value=item), \
         patch("core.runner.get_suppliers_for_item", return_value=["a", "b"]), \
         patch("core.runner.update_supplier_entry"):
        runner._run_single_item("x1", sups_ab, discovery_mode=False)

    key_ab = ("x1", frozenset({"a", "b"}))
    key_ac = ("x1", frozenset({"a", "c"}))
    assert key_ab in runner._session_cache
    assert key_ac not in runner._session_cache


def test_session_cache_not_populated_in_discovery_mode():
    runner._session_cache.clear()
    runner.item_states = {"x1": {"log": [], "results": [], "done": False, "error": None}}

    item = _stub_item()
    sups = [_fake_supplier("a")]
    with patch("core.runner.get_item", return_value=item), \
         patch("core.runner.get_suppliers_for_item", return_value=["a"]), \
         patch("core.runner.update_supplier_entry"):
        runner._run_single_item("x1", sups, discovery_mode=True)

    assert not runner._session_cache, "discovery mode must not populate session cache"
