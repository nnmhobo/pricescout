"""
Scraper: Будія (budia.ua) — Scrapling.
Search: /ua/shop/search?text=...  (ImageCMS/Multishop platform, same as megatrade)
Note: search param is 'text', not 'q'.
"""
from scrapers._scrapling_base import SiteConfig, text_based_extract, FETCH_MODE_FAST

CONFIG = SiteConfig(
    name="Будія",
    domain="budia.ua",
    search_url_template="https://budia.ua/ua/shop/search?text={q}",
    card_selectors=["article.product-cut"],
    title_selector=".product-cut__title-link",
    price_selectors=[".product-price__item", ".product-price__main", ".product-cut__price"],
    url_selector=".product-cut__title-link",
    sku_selectors=[],
    sku_text_patterns=[
        r'(?:Код|Артикул|SKU)[:\s]+([A-Za-z0-9][A-Za-z0-9\-]{3,})',
    ],
    fetch_timeout=20,
    check_cloudflare=False,
    fetcher_mode=FETCH_MODE_FAST,
)


def scrape(supplier, label, log, saved_url=None):
    return text_based_extract(CONFIG, label, log, saved_url)
