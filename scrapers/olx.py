"""
Scraper: OLX.ua — Scrapling (fast HTTP path).

OLX is a classifieds board, not a retail store: each card is a seller's
ad with a hand-typed title and a hand-typed price. The matcher does the
heavy lifting of rejecting unrelated listings; the price we report is
whatever the highest-scoring listing asks. Treat OLX numbers as an
indicative floor (often «договірна») rather than a quote.

Platform: server-rendered with `data-cy` / `data-testid` attributes on
every card. No browser warm-up needed.

DOM (verified live):
  card  : [data-cy="l-card"]
  title : [data-cy="ad-card-title"]
  price : p[data-testid="ad-price"]
  url   : <a href> inside the card
"""
from scrapers._scrapling_base import (
    SiteConfig, search_and_extract, FETCH_MODE_FAST,
)

CONFIG = SiteConfig(
    name="OLX",
    domain="www.olx.ua",
    # OLX puts the query in the path, not a `?q=` param.
    search_url_template="https://www.olx.ua/uk/list/q-{q}/",
    card_selectors=['[data-cy="l-card"]'],
    title_selector='[data-cy="ad-card-title"]',
    price_selectors=['p[data-testid="ad-price"]'],
    # The card itself is a <div> — the clickable <a> with the listing href
    # is nested inside. Without this, `_extract_url_from_card` falls back
    # to the title element (an <h6>) which has no href and the result gets
    # silently dropped.
    url_selector='a[href]',
    sku_selectors=[],
    sku_text_patterns=[],
    fetch_timeout=20,
    check_cloudflare=False,
    fetcher_mode=FETCH_MODE_FAST,
)


def scrape(supplier, label, log, saved_url=None):
    return search_and_extract(CONFIG, label, log, saved_url)
