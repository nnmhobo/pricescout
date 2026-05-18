"""Price extraction tests — the second most critical signal next to matching.

Covers parse_price (number normalization) and _PRICE_LINE_RE (regex that
recognises a price-bearing line on a page).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from scrapers._scrapling_base import parse_price, _PRICE_LINE_RE


# ── parse_price ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1 299,99 грн",   1299.99),
        ("1245,74 ₴",      1245.74),
        ("$1,299.99",      1299.99),
        ("622 грн",        622.0),
        ("0,50",           0.5),
        ("12.34",          12.34),
        ("1 234 567,89",   1234567.89),
        ("  ",             None),
        (None,             None),
        ("---",            None),
    ],
)
def test_parse_price_basic(raw, expected):
    assert parse_price(raw) == expected


# ── _PRICE_LINE_RE ──────────────────────────────────────────


_VALID = [
    ("Ціна 1 299,99 грн", 1299.99),
    ("622 грн.",          622.0),
    ("12 345 грн",        12345.0),
    ("1 234 567,89 грн",  1234567.89),
    ("99 ₴",              99.0),
]


@pytest.mark.parametrize("line, expected", _VALID)
def test_price_line_re_matches_valid_prices(line, expected):
    m = _PRICE_LINE_RE.search(line)
    assert m is not None, line
    assert parse_price(m.group(1)) == expected


def test_price_line_re_rejects_malformed_thousand_separators():
    """Bug #5: '1 023 67 грн' (no decimal sep) used to parse as 102367."""
    line = "1 023 67 грн"
    m = _PRICE_LINE_RE.search(line)
    # Either no match at all, or the match must NOT span all three groups —
    # i.e. the parsed value must not be the wrong 102367.
    if m is not None:
        assert parse_price(m.group(1)) != 102367
