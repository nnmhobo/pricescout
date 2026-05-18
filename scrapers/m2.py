"""
Scraper: М2 (m2.org.ua) — Scrapling.
Search: /search?search=... (OpenCart standard, uses &search= not &q=).

Card structure:
  - Card: .product-layout
  - Title: .rm-module-title a
  - Price: .rm-module-price (format: "1 245.74 грн")
  - URL: .rm-module-title a[href]

Note: M2's search is strict — multi-word queries often return no results.
We try the full query first, then fall back to individual words.
"""
from scrapers._scrapling_base import (
    SiteConfig, search_and_extract, normalize_search_query, FETCH_MODE_FAST,
)

CONFIG = SiteConfig(
    name="М2",
    domain="m2.org.ua",
    search_url_template="https://m2.org.ua/search?search={q}",
    card_selectors=[
        ".product-layout",
        ".rm-module-item",
    ],
    title_selector=".rm-module-title a",
    price_selectors=[".rm-module-price", ".price-new", ".price"],
    url_selector=".rm-module-title a",
    sku_selectors=['[itemprop="sku"]', '.rm-module-model'],
    sku_text_patterns=[
        r'(?:Артикул|Код|SKU)[:\s]+([A-Za-z0-9][A-Za-z0-9\-]{3,})',
    ],
    fetch_timeout=20,
    check_cloudflare=False,
    fetcher_mode=FETCH_MODE_FAST,
)


def scrape(supplier, label, log, saved_url=None):
    # Try the full query first
    result, url = search_and_extract(CONFIG, label, log, saved_url)
    if result:
        return result, url

    # If no results, M2's search is strict — try individual words
    # or the first significant word alone
    query = normalize_search_query(label)
    words = [w for w in query.split() if len(w) >= 4]

    # Try each word individually (longest first — more specific)
    tried = {query.lower()}
    for word in sorted(words, key=len, reverse=True):
        if word.lower() in tried:
            continue
        tried.add(word.lower())
        log(f"  → повторна спроба: '{word}'")
        result, url = search_and_extract(CONFIG, word, log)
        if result:
            return result, url

    return None, None
