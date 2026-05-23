"""
Scraper: АРС (ars.ua) on Scrapling.

ARS runs a standard Magento 2 storefront, so:
  - search:   https://ars.ua/catalogsearch/result/?q={query}
  - card:     .product-item  (many per page)
  - title:    a.product-item-link
  - price:    [data-price-amount]   (also has data-price-amount="169")
  - SKU:      [itemprop="sku"] on the detail page

ARS is behind Cloudflare. Scrapling's StealthyFetcher + camoufox usually
passes, but if we see a 403/503 or the page title mentions Cloudflare,
log a clean message and return (None, None).
"""

from __future__ import annotations

from datetime import date
from urllib.parse import quote_plus, urljoin

from scrapers._scrapling_base import (
    fetch_html,
    normalize_search_query,
    parse_price,
    pick_best_card,
    score_title,
    FETCH_MODE_STEALTH,
)
from matching.matcher import DEFAULT_THRESHOLD

# ARS sits behind Cloudflare — we need the stealth (camoufox) path to
# pass the bot challenge. Fast HTTP gets a 403 here.
_FETCH_MODE = FETCH_MODE_STEALTH

DOMAIN = "https://ars.ua"
SEARCH_URL = "https://ars.ua/catalogsearch/result/?q={q}"

CARD_SELECTOR = ".product-item"
TITLE_SELECTOR = "a.product-item-link"
PRICE_SELECTOR = "[data-price-amount]"
SKU_SELECTOR = '[itemprop="sku"]'


def _text(adaptor) -> str:
    if adaptor is None:
        return ""
    try:
        return adaptor.get_all_text().strip()
    except Exception:
        try:
            return str(adaptor.text).strip()
        except Exception:
            return ""


def _first(matches):
    if not matches:
        return None
    try:
        return matches.first
    except Exception:
        return matches[0] if len(matches) > 0 else None


def _cloudflare_blocked(page) -> bool:
    status = getattr(page, "status", 200)
    if status in (403, 503, 520, 521, 522):
        return True
    # Title-based heuristic (Cloudflare interstitial pages)
    try:
        title_el = _first(page.css("title"))
        if title_el is None:
            return False
        title = _text(title_el).lower()
        return any(w in title for w in ("cloudflare", "attention required", "just a moment"))
    except Exception:
        return False


def _extract_price(node) -> float | None:
    el = _first(node.css(PRICE_SELECTOR))
    if el is None:
        return None
    attr = el.attrib.get("data-price-amount") or el.attrib.get("content")
    if attr:
        parsed = parse_price(attr)
        if parsed is not None:
            return parsed
    return parse_price(_text(el))


def _extract_title_and_url(node) -> tuple[str | None, str | None]:
    el = _first(node.css(TITLE_SELECTOR))
    if el is None:
        return None, None
    title = _text(el) or None
    href = el.attrib.get("href")
    url = urljoin(DOMAIN, href) if href else None
    return title, url


def _extract_sku(page) -> str | None:
    el = _first(page.css(SKU_SELECTOR))
    if el is None:
        return None
    text = _text(el) or el.attrib.get("content")
    return text.strip() if text else None


def _build_result(supplier, name, price, url, sku) -> dict:
    return {
        "name": name or "",
        "price": price,
        "currency": "UAH",
        "unit": None,
        "brand": None,
        "sku": sku,
        "specs": None,
        "supplier": supplier["name"],
        "url": url,
        "date_scraped": date.today().isoformat(),
    }


def _scrape_saved_url(supplier, label, log, saved_url) -> tuple[dict | None, str | None]:
    log(f"  Пряме посилання: {saved_url}")
    try:
        page = fetch_html(saved_url, timeout=30, mode=_FETCH_MODE)
    except Exception as exc:
        log(f"  → помилка завантаження ({exc})")
        return None, None

    if _cloudflare_blocked(page):
        log("  → Cloudflare заблокував, пропускаємо")
        return None, None

    h1 = _first(page.css("h1"))
    name = _text(h1) if h1 else None
    price = _extract_price(page)
    sku = _extract_sku(page)

    if price is None:
        log("  → ціну не знайдено, посилання застаріло")
        return None, None

    if name and score_title(name, label) < DEFAULT_THRESHOLD:
        log(f"  → сторінка не збігається з товаром «{label[:40]}» (заголовок: {name[:40]})")
        return None, None

    log(f"  ✓ Знайдено за прямим посиланням: {(name or '')[:60]} — {price} ₴")
    return _build_result(supplier, name, price, saved_url, sku), saved_url


def scrape(supplier, label, log, saved_url=None) -> tuple[dict | None, str | None]:
    """Returns (item_dict | None, product_url | None)."""
    if saved_url:
        result, url = _scrape_saved_url(supplier, label, log, saved_url)
        if result:
            return result, url
        log("  → переходимо до пошуку")

    from scrapers.query_variations import generate_variations

    query = normalize_search_query(label)
    if not query:
        log("  → порожній запит, нічого шукати")
        return None, None

    queries = generate_variations(query, max_variations=6)
    for query_idx, q in enumerate(queries):
        if not q:
            continue

        url = SEARCH_URL.format(q=quote_plus(q))
        if query_idx > 0:
            log(f"  → повторна спроба: '{q}'")
        else:
            log(f"  Пошук: {url}")
        try:
            page = fetch_html(url, timeout=60, mode=_FETCH_MODE)
        except Exception as exc:
            log(f"  → помилка пошуку ({exc})")
            continue

        if _cloudflare_blocked(page):
            log("  → Cloudflare заблокував пошук, пропускаємо")
            return None, None

        cards = page.css(CARD_SELECTOR)
        log(f"  → {len(cards)} карток-результатів")
        if not cards:
            continue

        best = pick_best_card(cards, label, title_selector=TITLE_SELECTOR, log_fn=log)
        if best is None:
            log("  → жодна картка не збіглася з назвою")
            continue

        name, product_url = _extract_title_and_url(best)
        price = _extract_price(best)

        if not product_url:
            log("  → не вдалося витягти URL товару")
            continue

        if price is None:
            log("  → ціна відсутня у картці")
            return None, product_url

        # Open detail page once for SKU
        sku = None
        try:
            detail = fetch_html(product_url, timeout=30, mode=_FETCH_MODE)
            if _cloudflare_blocked(detail):
                log("  → Cloudflare на сторінці товару, без артикула")
            else:
                sku = _extract_sku(detail)
                if sku:
                    log(f"  → артикул: {sku}")
        except Exception as exc:
            log(f"  → не вдалося завантажити сторінку товару ({exc})")

        log(f"  ✓ Знайдено: {(name or '')[:60]} — {price} ₴")
        return _build_result(supplier, name, price, product_url, sku), product_url

    log("  → товар не знайдено за жодним варіантом запиту")
    return None, None
