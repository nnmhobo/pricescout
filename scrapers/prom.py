"""
Scraper: Prom.ua — Scrapling (fast HTTP path).

Prom is a marketplace aggregator (~100k+ sellers), so an item is found
on multiple seller listings at different prices. We take the best fuzzy
match the matcher returns, which is normally the price the marketplace
itself ranks first (sponsored or top-rated seller). Power users can
re-rank by opening the URL — the result still lets the cost-estimate
compare a real, live Ukrainian retail price.

Platform: server-rendered HTML with `data-qaid` attributes on every card.
No browser warm-up needed — `?search_term=` returns ten cards per page.

DOM (verified live):
  card  : [data-qaid="product_block"]
  title : [data-qaid="product_name"]
  price : [data-qaid="product_price"]
  url   : a[data-qaid="product_link"]
"""
from scrapers._scrapling_base import (
    SiteConfig, search_and_extract, FETCH_MODE_FAST,
)

CONFIG = SiteConfig(
    name="Prom.ua",
    domain="prom.ua",
    search_url_template="https://prom.ua/ua/search?search_term={q}",
    card_selectors=['[data-qaid="product_block"]'],
    title_selector='[data-qaid="product_name"]',
    price_selectors=['[data-qaid="product_price"]'],
    url_selector='a[data-qaid="product_link"]',
    # Prom doesn't expose a stable SKU in the card; skip the detail-page
    # round-trip to keep the search fast.
    sku_selectors=[],
    sku_text_patterns=[],
    fetch_timeout=20,
    check_cloudflare=False,
    fetcher_mode=FETCH_MODE_FAST,
)


def scrape(supplier, label, log, saved_url=None):
    return search_and_extract(CONFIG, label, log, saved_url)
