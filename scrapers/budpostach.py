"""
Scraper: Будпостач (budpostach.ua) — Scrapling.
Search: OpenCart standard.
"""
from scrapers._scrapling_base import SiteConfig, text_based_extract, FETCH_MODE_FAST

CONFIG = SiteConfig(
    name="Будпостач",
    domain="budpostach.ua",
    search_url_template="https://budpostach.ua/index.php?route=product/search&search={q}",
    # BEM-style markup. The card is `.product-layout` (grid wrapper); the
    # actual tile is `.product-thumb` inside. `.product-thumb__name` is an
    # <a> with the title and href, `.product-thumb__price` holds the price.
    card_selectors=[".product-layout", ".product-thumb"],
    title_selector="a.product-thumb__name, .product-thumb__caption a",
    price_selectors=[".product-thumb__price", ".price-new", ".price"],
    url_selector="a.product-thumb__name, .product-thumb__caption a",
    sku_selectors=['[itemprop="sku"]', '.product-thumb__model'],
    sku_text_patterns=[
        r'(?:Код|Артикул|SKU|Model)[:\s]+([A-Za-z0-9][A-Za-z0-9\-]{3,})',
    ],
    fetch_timeout=20,
    check_cloudflare=False,
    fetcher_mode=FETCH_MODE_FAST,
)


def scrape(supplier, label, log, saved_url=None):
    return text_based_extract(CONFIG, label, log, saved_url)
