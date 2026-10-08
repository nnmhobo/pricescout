"""Конфігурація постачальників PriceScout.

13 постачальників; ціни збираються через Scrapling (звичайний HTTP або
браузер Patchright/camoufox для JS-сайтів і захисту від ботів). Які саме
постачальники опитуються для матеріалу, вирішує matching/category_routing.py.

Як додати нового постачальника:
  1. Створити файл scrapers/<id>.py з функцією scrape(supplier, label, log, saved_url=None)
  2. Додати запис у SUPPLIER_REGISTRY нижче (id, name, url, module, enabled)
  3. Додати id у потрібні списки category_routing.py — постачальника, якого
     немає в жодному робочому списку маршрутизації, НЕ опитують ніколи
"""
import importlib
from typing import Callable, Optional


# ── Supplier Registry ─────────────────────────────────────────
# Each entry: (id, name, url, scraper_module, enabled)
# Adding a new supplier = one line here + scraper file.
SUPPLIER_REGISTRY: list[tuple[str, str, str, str, bool]] = [
    ("epicentr",   "Епіцентр К",      "https://epicentrk.ua",        "scrapers.epicentr",   True),
    ("ars",        "АРС",              "https://ars.ua",              "scrapers.ars",        True),
    ("buddvir",    "Будівельний Двір", "https://buddvir.ua",          "scrapers.buddvir",    True),
    ("kub",        "КУБ",              "https://kub.in.ua",           "scrapers.kub",        True),
    ("venbud",     "Вен Буд",          "https://venbud.ua",           "scrapers.venbud",     True),
    ("budpostach", "Будпостач",        "https://budpostach.ua",       "scrapers.budpostach", True),
    ("m2",         "М2",               "https://m2.org.ua",           "scrapers.m2",         True),
    ("vista",      "Віста",            "https://vista.ua",            "scrapers.vista",      True),
    ("megatrade",  "Мегатрейд СМ",    "https://megatrade-sm.com.ua", "scrapers.megatrade",  True),
    ("budia",      "Будія",            "https://budia.ua",            "scrapers.budia",      True),
    ("teplodim",   "ТеплоДiм",        "https://teplodim.com.ua",     "scrapers.teplodim",   True),
    # Marketplaces (broad coverage, lower data quality) — added 2026-05-18.
    # Prom.ua is a 100k-seller marketplace; OLX is a classifieds board.
    # `enabled=True` means "available to toggle on in the UI" — not
    # "checked by default". The user can untick them per batch if the
    # marketplace noise hurts a specific run.
    ("prom",       "Prom.ua",          "https://prom.ua",             "scrapers.prom",       True),
    ("olx",        "OLX",              "https://www.olx.ua",          "scrapers.olx",        True),
]


def _load_scraper(module_path: str) -> Callable:
    """Dynamically import a scraper module and return its `scrape` function."""
    mod = importlib.import_module(module_path)
    return mod.scrape


def build_suppliers(registry: Optional[list] = None) -> list[dict]:
    """Build the SUPPLIERS list from the registry with lazy module loading."""
    reg = registry or SUPPLIER_REGISTRY
    suppliers = []
    for sid, name, url, module, enabled in reg:
        try:
            scrape_fn = _load_scraper(module)
        except (ImportError, AttributeError) as exc:
            print(f"[suppliers] WARNING: failed to load {module}: {exc}")
            continue
        suppliers.append({
            "id": sid,
            "name": name,
            "url": url,
            "enabled": enabled,
            "scrape": scrape_fn,
        })
    return suppliers


SUPPLIERS = build_suppliers()
