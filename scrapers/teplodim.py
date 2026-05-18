"""
Scraper: ТеплоДiм (teplodim.com.ua) — Scrapling.

HVAC / heating specialist (котли, радіатори, конвектори, насоси, бойлери).
Closes the empty 'Теплопостачання', 'Вентиляція', 'Теплотехнічне устаткування'
categories in category_routing.

Platform: OpenCart with friendly URLs (/<category>/<sku>).
Search:   ?route=product/search&search=  (server-rendered, ~15 cards/query)

DOM (verified live on `route=product/search&search=конвектор`):
  card  : .product-thumb           (15 matches)
  title : .caption h4 a            (also '.product-thumb .caption a')
  price : .product-thumb .price    (also '.price')
"""
from scrapers._scrapling_base import SiteConfig, search_and_extract, FETCH_MODE_FAST

CONFIG = SiteConfig(
    name="ТеплоДiм",
    domain="teplodim.com.ua",
    search_url_template="https://teplodim.com.ua/index.php?route=product/search&search={q}",
    card_selectors=[".product-thumb", ".product-layout"],
    title_selector=".caption h4 a",
    price_selectors=[".product-thumb .price", ".price-new", ".price"],
    url_selector=".caption h4 a",
    sku_selectors=['[itemprop="sku"]'],
    sku_text_patterns=[
        r'(?:Код|Артикул|SKU|Модель|Model)[:\s]+([A-Za-z0-9][A-Za-z0-9\-\.]{3,})',
    ],
    fetch_timeout=20,
    check_cloudflare=False,
    fetcher_mode=FETCH_MODE_FAST,
)


def scrape(supplier, label, log, saved_url=None):
    return search_and_extract(CONFIG, label, log, saved_url)
