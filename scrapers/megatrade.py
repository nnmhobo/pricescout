"""
Scraper: Мегатрейд СМ (megatrade-sm.com.ua) — Scrapling.
Search: /shop/search?q=...  (ImageCMS/Multishop platform)
"""
from scrapers._scrapling_base import SiteConfig, text_based_extract, FETCH_MODE_FAST

CONFIG = SiteConfig(
    name="Мегатрейд СМ",
    domain="megatrade-sm.com.ua",
    search_url_template="https://megatrade-sm.com.ua/shop/search?q={q}",
    card_selectors=["article.product-cut"],
    title_selector=".product-cut__title-link",
    price_selectors=[".product-price__main-value", ".product-price__item", ".product-price__main"],
    url_selector=".product-cut__title-link",
    sku_selectors=["[data-product-number]"],
    sku_text_patterns=[
        r'(?:Артикул|Код|SKU)[:\s]+([A-Za-z0-9][A-Za-z0-9\-]{3,})',
    ],
    fetch_timeout=20,
    check_cloudflare=False,
    fetcher_mode=FETCH_MODE_FAST,
)


def scrape(supplier, label, log, saved_url=None):
    return text_based_extract(CONFIG, label, log, saved_url)
