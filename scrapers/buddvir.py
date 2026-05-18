"""
Scraper: Будівельний Двір (buddvir.ua) — Scrapling.
Search: OpenCart /index.php?route=product/search&search=...
Results are server-rendered in .product-layout cards.
"""
from scrapers._scrapling_base import SiteConfig, text_based_extract, FETCH_MODE_FAST

CONFIG = SiteConfig(
    name="Будівельний Двір",
    domain="buddvir.ua",
    search_url_template="https://buddvir.ua/index.php?route=product/search&search={q}",
    card_selectors=[".product-layout", ".product-thumb"],
    title_selector="a.ds-module-title",
    price_selectors=[".ds-module-price", ".price-new", ".special-price"],
    url_selector="a.ds-module-title",
    sku_selectors=[".ds-module-code"],
    sku_text_patterns=[
        r'(?:Артикул|Код|SKU)[:\s]+([A-Za-z0-9][A-Za-z0-9\-]{3,})',
    ],
    fetch_timeout=20,
    check_cloudflare=False,
    fetcher_mode=FETCH_MODE_FAST,
)


def scrape(supplier, label, log, saved_url=None):
    return text_based_extract(CONFIG, label, log, saved_url)
