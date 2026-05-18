"""
Scraper: Віста (vista.ua) — Scrapling.
Search: /search/?search=... (OpenCart standard, uses &search= not &q=).

Card structure:
  - Card: .product-layout .product-thumb
  - Title: a.product-name span, a.product-name
  - Price: .price-new (format: "776\n,20\n грн" — multiline, or just "1498")
  - URL: a.product-name[href]
  - SKU: .model (format: "Код: 322612")
"""
from scrapers._scrapling_base import SiteConfig, search_and_extract, FETCH_MODE_FAST

CONFIG = SiteConfig(
    name="Віста",
    domain="vista.ua",
    search_url_template="https://vista.ua/search/?search={q}",
    card_selectors=[
        ".product-layout",
        ".product-thumb",
    ],
    title_selector="a.product-name span, a.product-name, .product-name",
    price_selectors=[".price-new", ".price", ".price-old"],
    url_selector="a.product-name, .product-name a",
    sku_selectors=['[itemprop="sku"]'],
    sku_text_patterns=[
        r'Код:\s*(\d+)',
        r'(?:Код|Артикул|SKU)[:\s]+([A-Za-z0-9][A-Za-z0-9\-]{3,})',
    ],
    fetch_timeout=20,
    check_cloudflare=False,
    fetcher_mode=FETCH_MODE_FAST,
)


def scrape(supplier, label, log, saved_url=None):
    return search_and_extract(CONFIG, label, log, saved_url)
