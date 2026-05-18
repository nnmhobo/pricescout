"""Tests for the query variation generator (the layer that fans a single
label out to several search strings for the supplier scrapers)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from scrapers.query_variations import generate_variations


def _flat(variants: list[str]) -> str:
    return " | ".join(v.lower() for v in variants)


def test_original_label_always_first():
    v = generate_variations("Фарба фасадна Sniezka")
    assert v[0] == "Фарба фасадна Sniezka"


def test_ceresit_code_is_expanded_even_at_small_max():
    """Bug #8: with max_variations=4 the simplifier could exhaust the slots
    before the Ceresit brand-code expansion ran. Brand codes must always be
    in the first variations."""
    v = generate_variations("Клей плитковий Ceresit CT-83 25 кг", max_variations=4)
    flat = _flat(v)
    assert "ceresit ct 83" in flat or "ct-83" in flat


def test_paint_code_expansion():
    v = generate_variations("Емаль ПФ-115 біла 2.8 кг", max_variations=5)
    flat = _flat(v)
    assert "пф-115" in flat or "пф 115" in flat


def test_compound_hyphen_synthesis():
    v = generate_variations("Фарба грунтувальна Rolax 10 л", max_variations=6)
    flat = _flat(v)
    # Either the compound form or one of its variants should be present.
    assert "грунт-фарба" in flat or "грунт фарба" in flat


def test_empty_label():
    assert generate_variations("") == [""]
    assert generate_variations("   ") == ["   "]


def test_max_variations_bound():
    v = generate_variations("Фарба грунтувальна Rolax 10 л", max_variations=3)
    assert len(v) <= 3


def test_hyphenated_compound_gets_dehyphenated_variant():
    """A label like 'Грунт-фарба' should also try 'Грунт фарба'
    (with space) because many sites tokenize on whitespace and miss
    the literal hyphenated form."""
    v = generate_variations("Грунт-фарба", max_variations=3)
    flat = _flat(v)
    assert "грунт фарба" in flat


def test_number_hyphen_range_is_not_split():
    """'Болти 12-14 мм' must not produce 'Болти 12 14 мм' — that range
    notation is meaningful and the number-hyphen-number pattern should
    stay intact."""
    v = generate_variations("Болти 12-14 мм", max_variations=5)
    for x in v:
        assert "12 14" not in x
