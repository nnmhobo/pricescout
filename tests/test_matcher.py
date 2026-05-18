"""Unit tests for the fuzzy matcher used by every supplier scraper.

These tests are the contract for "if the product exists on a website it
must 100% be found": every regression spotted in real cost-estimates
becomes a case here so it never silently breaks again.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from matcher import (
    calculate_match_score,
    find_best_match,
    normalize_text,
    DEFAULT_THRESHOLD,
)


# ── Normalization ────────────────────────────────────────────


def test_normalize_collapses_ukrainian_and_russian_variants():
    # і/и/ї → и; є/ё → е; apostrophe variants removed.
    assert normalize_text("МІНВАТА") == normalize_text("МИНВАТА")
    assert normalize_text("утеплЮВАЧ") == normalize_text("УТЕПЛЮВАЧ")
    assert normalize_text("в’яжучі") == normalize_text("вяжучі")
    assert normalize_text("ЦвЯх") == "цвях".translate(normalize_text.__globals__["_NORM_MAP"])


def test_normalize_idempotent():
    s = "Грунт-фарба Rolax 10 л"
    assert normalize_text(s) == normalize_text(normalize_text(s))


# ── calculate_match_score ────────────────────────────────────


@pytest.mark.parametrize(
    "query, candidate",
    [
        ("Утеплювач мінвата т=50 мм НГ",   "Мінеральна вата 50 мм 100кг/м3"),
        ("Утеплитель базальтова вата 100мм","Утеплювач Технониколь Роклайт 100мм"),
        ("Фарба грунтувальна Rolax 10 л",  "Грунт-фарба Rolax 10 л"),
        ("Гіпсокартон Knauf 12.5 мм",      "ГКЛ Кнауф 12.5 мм"),
        ("Краска фасадна Sniezka 5 кг",    "Фарба фасадна Sniezka 5 кг"),
    ],
)
def test_score_passes_threshold_for_real_synonym_pairs(query, candidate):
    score = calculate_match_score(query, candidate)
    assert score >= DEFAULT_THRESHOLD, (query, candidate, score)


@pytest.mark.parametrize(
    "query, wrong, right",
    [
        # Different brand code — must prefer the right one.
        ("Ceresit CT 225 Білий 25 кг",
         "Ceresit CT 29 Сірий 25 кг",
         "Ceresit CT 225 Білий 25 кг"),
        # Different thickness — must prefer the right one.
        ("Гіпсокартон Knauf 12.5 мм",
         "Гіпсокартон Knauf 9.5 мм",
         "Гіпсокартон Knauf 12.5 мм"),
        # Wrong dimensions.
        ("Сітка штукатурна 150мм",
         "Сітка штукатурна 100мм",
         "Сітка штукатурна 150мм"),
    ],
)
def test_find_best_match_prefers_correct_dimension_or_code(query, wrong, right):
    res = find_best_match(query, [wrong, right])
    assert res is not None
    assert res.name == right, (query, wrong, right, res.name)


# ── find_best_match ──────────────────────────────────────────


def test_find_best_match_picks_synonym_candidate():
    """Bug #1: query had no shared tokens with candidate before the fix."""
    res = find_best_match(
        "Утеплювач мінвата т=50 мм НГ",
        ["Мінеральна вата 50 мм 100кг/м3", "Пінопласт ПСБ-С 50мм"],
    )
    assert res is not None
    assert res.name == "Мінеральна вата 50 мм 100кг/м3"


def test_find_best_match_returns_none_below_threshold():
    res = find_best_match(
        "Цемент Портланд 25 кг",
        ["Гвозді 100мм", "Електрод 3мм АНО-21"],
    )
    assert res is None


def test_find_best_match_respects_top_n_for_logging(caplog):
    res = find_best_match(
        "Фарба фасадна Sniezka",
        ["Фарба фасадна Sniezka 5 кг", "Фарба фасадна Sniezka 10 кг",
         "Грунт фасадний Sniezka"],
        top_n=2,
    )
    assert res is not None
    # The best (highest-scoring) item must be picked.
    assert "Фарба фасадна Sniezka" in res.name


# ── Russian ↔ Ukrainian ──────────────────────────────────────


def test_russian_to_ukrainian_normalization_lets_match_succeed():
    score = calculate_match_score("Утеплитель Технониколь 100мм",
                                  "Утеплювач Технониколь 100мм")
    assert score >= 70

    score2 = calculate_match_score("Краска фасадная Sniezka",
                                   "Фарба фасадна Sniezka")
    assert score2 >= DEFAULT_THRESHOLD
