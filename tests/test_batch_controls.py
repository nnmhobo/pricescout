"""Tests for the new batch-run knobs in ``runner``.

Covers:
- :func:`_clamp_parallel` — input validation for the user-supplied
  parallelism setting (1..MAX_PARALLEL_ITEMS).
- :func:`_apply_limit` — slicing the queue down to the first N ids.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

import runner
from runner import _apply_limit, _clamp_parallel


# ── _clamp_parallel ────────────────────────────────────────────


@pytest.mark.parametrize(
    "value, expected",
    [
        (1, 1),
        (2, 2),
        (3, 3),
        ("2", 2),
    ],
)
def test_clamp_parallel_accepts_valid_values(value, expected):
    assert _clamp_parallel(value) == expected


def test_clamp_parallel_caps_at_max(monkeypatch):
    monkeypatch.setattr(runner, "MAX_PARALLEL_ITEMS", 5)
    assert _clamp_parallel(99) == 5
    assert _clamp_parallel(5) == 5


def test_clamp_parallel_falls_back_on_invalid_input():
    # None / non-numeric / 0 / negative -> fallback default
    assert _clamp_parallel(None) == runner.DEFAULT_PARALLEL_ITEMS
    assert _clamp_parallel("abc") == runner.DEFAULT_PARALLEL_ITEMS
    assert _clamp_parallel(0) == runner.DEFAULT_PARALLEL_ITEMS
    assert _clamp_parallel(-3) == runner.DEFAULT_PARALLEL_ITEMS


def test_clamp_parallel_custom_fallback():
    assert _clamp_parallel(None, fallback=2) == min(runner.MAX_PARALLEL_ITEMS, 2)


# ── _apply_limit ───────────────────────────────────────────────


_IDS = ["a", "b", "c", "d", "e"]


@pytest.mark.parametrize(
    "limit, expected",
    [
        (None,  _IDS),       # missing -> all
        (0,     _IDS),       # zero  -> all
        (-1,    _IDS),       # negative -> all
        ("",    _IDS),       # blank -> all
        ("abc", _IDS),       # garbage -> all
        (1,     ["a"]),      # first
        (3,     ["a", "b", "c"]),
        ("2",   ["a", "b"]),  # numeric string is fine
        (5,     _IDS),       # exact len -> all
        (99,    _IDS),       # bigger -> all
    ],
)
def test_apply_limit_slices_queue_head(limit, expected):
    assert _apply_limit(_IDS, limit) == expected


def test_apply_limit_returns_a_copy():
    out = _apply_limit(_IDS, None)
    assert out == _IDS
    assert out is not _IDS  # must not be the same list object


def test_apply_limit_empty_input():
    assert _apply_limit([], 5) == []
    assert _apply_limit([], None) == []
