"""
Live probe for the three real supplier candidates:
  teplodim.com.ua, santehmag.com.ua, elektro.in.ua

For each (site, query) pair:
  1. Try the homepage to discover the platform / search form.
  2. Hit a search-results URL.
  3. Save raw HTML to debug/<site>_<query>.html.
  4. Print structural hints (counts of known card / title / price selectors).

Run AFTER `scrapling install`. ~30s per fetch with DynamicFetcher.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).parent))

# Ensure stdout can handle Unicode arrows / Cyrillic on Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from scrapers._scrapling_base import fetch_html  # noqa: E402

DEBUG_DIR = Path(__file__).parent / "debug"
DEBUG_DIR.mkdir(exist_ok=True)


# Each site can have multiple candidate search-URL templates — we try the
# first that produces a non-empty product listing.
SITES = {
    "teplodim": {
        "search_url_candidates": [
            "https://teplodim.com.ua/index.php?route=product/search&search={q}",
            "https://teplodim.com.ua/ru/search?q={q}",
            "https://teplodim.com.ua/search?q={q}",
        ],
        "queries": ["котел", "радiатор", "насос"],
    },
    "santehmag": {
        "search_url_candidates": [
            "https://santehmag.com.ua/index.php?route=product/search&search={q}",
            "https://santehmag.com.ua/search?q={q}",
        ],
        "queries": ["змiшувач", "унiтаз", "труба"],
    },
    "elektro_in_ua": {
        "search_url_candidates": [
            "https://elektro.in.ua/ua/search/?q={q}",
            "https://elektro.in.ua/search?q={q}",
            "https://elektro.in.ua/index.php?route=product/search&search={q}",
        ],
        "queries": ["кабель", "автомат", "розетка"],
    },
}

CARD_PATTERNS = [
    ".product-thumb", ".product-layout", ".product-card",
    "article.product", ".catalog-item", "li.product-item",
    ".product-grid .product", ".search-result-item",
    "[data-product]", "[itemtype*='Product']",
    ".product", ".item.product", ".product-block", ".product-cut",
    ".product_card", "div.b-search-item",
]

TITLE_PATTERNS = [
    "h4 a", ".name a", ".caption h4 a", ".product-name a",
    ".product-title", ".product-card__name", "a.product-link",
    ".product-thumb .caption a", ".product__title a",
    "[itemprop='name']", ".item-title a",
]

PRICE_PATTERNS = [
    ".price", ".price-new", ".product-price", ".price-current",
    "[itemprop='price']", "span.price", ".product__price",
    ".price__main", ".item-price", ".product-thumb .price",
    ".price-actual", ".b-price__current",
]


def _get_body(page) -> str:
    for attr in ("body", "html", "text"):
        v = getattr(page, attr, None)
        if callable(v):
            try:
                v = v()
            except Exception:
                v = None
        if v:
            return str(v)
    return ""


def probe(site_id: str, search_url: str, query: str) -> dict:
    url = search_url.format(q=quote_plus(query))
    print(f"\n=== {site_id} :: {query!r} ===")
    print(f"    {url}")
    try:
        page = fetch_html(url, timeout=45, wait_ms=6000)
    except Exception as exc:
        print(f"    ERROR fetch: {exc}")
        return {"site": site_id, "query": query, "error": str(exc)}

    status = getattr(page, "status", 200)
    print(f"    HTTP {status}")

    # Save raw HTML
    out_path = DEBUG_DIR / f"{site_id}__{query[:20].replace(' ', '_')}.html"
    try:
        html_str = _get_body(page)
        if html_str:
            out_path.write_text(html_str, encoding="utf-8", errors="ignore")
            print(f"    saved -> {out_path.name} ({len(html_str)} chars)")
    except Exception as exc:
        print(f"    save failed: {exc}")

    summary = {
        "site": site_id, "query": query, "status": status,
        "cards": {}, "titles": {}, "prices": {},
    }
    for sel in CARD_PATTERNS:
        try:
            found = page.css(sel)
            if found and len(found) > 0:
                summary["cards"][sel] = len(found)
        except Exception:
            pass
    for sel in TITLE_PATTERNS:
        try:
            found = page.css(sel)
            if found and len(found) > 0:
                summary["titles"][sel] = len(found)
        except Exception:
            pass
    for sel in PRICE_PATTERNS:
        try:
            found = page.css(sel)
            if found and len(found) > 0:
                summary["prices"][sel] = len(found)
        except Exception:
            pass

    def fmt(d):
        if not d:
            return "-"
        return ", ".join(f"{k}={v}" for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:5])

    print(f"    cards : {fmt(summary['cards'])}")
    print(f"    titles: {fmt(summary['titles'])}")
    print(f"    prices: {fmt(summary['prices'])}")
    return summary


def main() -> None:
    for site_id, cfg in SITES.items():
        for tmpl_idx, tmpl in enumerate(cfg["search_url_candidates"]):
            # Try first query against each candidate URL to find a working one
            sample_q = cfg["queries"][0]
            sample = probe(site_id, tmpl, sample_q)
            if sample.get("cards"):
                # Working URL found — probe remaining queries with it
                print(f"\n  >>> {site_id}: using URL template #{tmpl_idx}")
                for q in cfg["queries"][1:]:
                    probe(site_id, tmpl, q)
                break
        else:
            print(f"\n  >>> {site_id}: NO working URL template found")


if __name__ == "__main__":
    main()
