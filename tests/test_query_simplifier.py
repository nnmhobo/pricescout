"""Regression tests for the cost-estimate label simplifier.

The simplifier converts long spec strings ("Болти із шестигранною головкою
оцинковані, діаметр різьби 12-[14] мм") into shorter, e-commerce-friendly
queries. Bugs here directly translate to "not found" results, so the most
important cases are pinned with tests.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from scrapers.query_simplifier import simplify_label


def _flatten(variants: list[str]) -> str:
    return " | ".join(variants)


def test_diameter_through_qualifier_word_is_extracted():
    """Bug #4: 'діаметр різьби 12 мм' used to lose the '12 мм' size."""
    variants = simplify_label(
        "Болти із шестигранною головкою оцинковані, діаметр різьби 12-[14] мм",
        max_variants=6,
    )
    flat = _flatten(variants)
    assert "болти" in flat.lower()
    assert "12 мм" in flat


def test_diameter_with_two_qualifier_words():
    variants = simplify_label("Сталь арматурна, діаметр стрижня 6 мм", max_variants=5)
    flat = _flatten(variants)
    assert "6 мм" in flat


def test_simple_diameter_still_works():
    variants = simplify_label(
        "Дріт сталевий низьковуглецевий різного призначення світлий, діаметр 4,0 мм",
        max_variants=5,
    )
    flat = _flatten(variants)
    assert "4 мм" in flat


def test_brackets_kept_for_inner_content():
    """[14] inside '12-[14] мм' must not destroy the '12' that comes before."""
    variants = simplify_label("Анкер діаметр 8-[10] мм", max_variants=5)
    flat = _flatten(variants)
    assert "8 мм" in flat


def test_compact_size_takes_priority_over_labelled_dim():
    variants = simplify_label("Цвяхи будівельні з конічною головкою 4,0х100 мм",
                              max_variants=4)
    flat = _flatten(variants)
    assert "4.0х100" in flat or "4х100" in flat
    assert "цвяхи" in flat.lower()


def test_returns_original_first():
    label = "Гіпсові в'яжучі Г-3"
    variants = simplify_label(label, max_variants=4)
    assert variants[0] == label


def test_empty_input_handling():
    assert simplify_label("") == [""]
    assert simplify_label("   ") == ["   "]
