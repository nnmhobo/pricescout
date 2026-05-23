"""Second probe — using the URLs the user actually gave us.

Verifies:
  - elektro.in.ua/ua/index.php?route=product/search&search= (confirmed search URL)
  - teplodim.com.ua/konvektor (category page) + try alternative search URLs

Saves HTML and prints structural hints we can convert into SiteConfig.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from scrapers._scrapling_base import fetch_html  # noqa: E402

DEBUG = Path(__file__).parent / "debug"
DEBUG.mkdir(exist_ok=True)


CARDS = [
    ".product-thumb", ".product-layout", ".product-card", "article.product",
    ".catalog-item", "li.product-item", "[itemtype*='Product']",
    ".product", ".product-block", ".product-cut", "div.b-search-item",
    ".product-list-item", ".item-product", "div.item", ".product-grid > div",
]
TITLES = [
    "h4 a", ".name a", ".caption h4 a", ".product-name a",
    ".product-title a", ".product-card__name a", "a.product-link",
    "[itemprop='name'] a", "[itemprop='name']",
    ".product-thumb .caption a", ".product__title a",
    ".item-title a", ".title a",
]
PRICES = [
    ".price", ".price-new", ".product-price", ".price-current",
    "[itemprop='price']", "span.price", ".product__price",
    ".price__main", ".item-price", ".price-actual",
    ".price-block .price", ".product-thumb .price",
]


def _body(page) -> str:
    for a in ("body", "html", "text"):
        v = getattr(page, a, None)
        if callable(v):
            try:
                v = v()
            except Exception:
                v = None
        if v:
            return str(v)
    return ""


def probe(label: str, url: str, save_name: str) -> None:
    print(f"\n=== {label} ===")
    print(f"    URL: {url}")
    try:
        page = fetch_html(url, timeout=60, wait_ms=8000)
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return
    print(f"    HTTP {getattr(page, 'status', '?')}")
    body = _body(page)
    if body:
        out = DEBUG / f"{save_name}.html"
        out.write_text(body, encoding="utf-8", errors="ignore")
        print(f"    saved {out.name} ({len(body)} chars)")

    def hits(pats):
        out = {}
        for s in pats:
            try:
                found = page.css(s)
                if found and len(found) > 0:
                    out[s] = len(found)
            except Exception:
                pass
        return out

    cards = hits(CARDS); titles = hits(TITLES); prices = hits(PRICES)
    def fmt(d): return "—" if not d else ", ".join(f"{k}={v}" for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:5])
    print(f"    cards : {fmt(cards)}")
    print(f"    titles: {fmt(titles)}")
    print(f"    prices: {fmt(prices)}")


TESTS = [
    # elektro.in.ua — user-confirmed search URL works
    ("elektro: search 'кабель'",  "https://elektro.in.ua/ua/index.php?route=product/search&search=" + quote_plus("кабель"),  "elektro_search_kabel"),
    ("elektro: search 'автомат'", "https://elektro.in.ua/ua/index.php?route=product/search&search=" + quote_plus("автомат"), "elektro_search_avtomat"),
    ("elektro: product page",     "https://elektro.in.ua/ua/kabel-dlya-sonyachnih-fotomodulej-olflex-solar-60",             "elektro_product"),

    # teplodim — user gave category + product, no search URL.
    # Try several search-URL templates; OpenCart often hides search under different path.
    ("teplodim: category",        "https://teplodim.com.ua/konvektor",                                                       "teplodim_category"),
    ("teplodim: product",         "https://teplodim.com.ua/konvektor/EPHBM05P",                                              "teplodim_product"),
    ("teplodim: search std",      "https://teplodim.com.ua/index.php?route=product/search&search=" + quote_plus("конвектор"), "teplodim_search_std"),
    ("teplodim: search /ua/",     "https://teplodim.com.ua/ua/index.php?route=product/search&search=" + quote_plus("конвектор"), "teplodim_search_ua"),
    ("teplodim: search ?q=",      "https://teplodim.com.ua/search?q=" + quote_plus("конвектор"),                              "teplodim_search_q"),
    ("teplodim: search ?s=",      "https://teplodim.com.ua/?s=" + quote_plus("конвектор"),                                   "teplodim_search_s"),
]

for label, url, save in TESTS:
    probe(label, url, save)
