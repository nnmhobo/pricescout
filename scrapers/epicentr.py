"""
Scraper: Епіцентр К (epicentrk.ua) on Scrapling.

Flow:
  1. If `saved_url` is provided, fetch it directly, extract price + SKU.
     On empty/4xx fall back to the search flow.
  2. Search via `https://epicentrk.ua/ua/search/?q={query}`.
     Cards are marked with `[itemtype="https://schema.org/Product"]`.
  3. Pick the best card by title overlap with the label.
  4. SKU lives on the detail page (`[itemprop="sku"]`), so we fetch the
     chosen card's product URL once for a clean SKU.

No Playwright, no Claude.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote_plus, urljoin

from scrapers._scrapling_base import (
    fetch_html,
    normalize_search_query,
    parse_price,
    pick_best_card,
    score_title,
    FETCH_MODE_FAST,
)
from matching.matcher import DEFAULT_THRESHOLD

# Epicentr is fully server-rendered with schema.org product markup — the
# fast HTTP fetcher is enough; no need to warm a browser per query.
_FETCH_MODE = FETCH_MODE_FAST

DOMAIN = "https://epicentrk.ua"
SEARCH_URL = "https://epicentrk.ua/ua/search/?q={q}"

# Probed selectors — see debug/epicentr_probe.html
CARD_SELECTOR = '[itemtype="https://schema.org/Product"]'
NAME_SELECTOR = '[itemprop="name"]'
URL_SELECTOR = 'a[itemprop="url"]'
PRICE_MAIN_SELECTOR = '[data-product-price-main] [itemprop="price"]'
PRICE_FALLBACK_SELECTOR = '[itemprop="price"]'
SKU_SELECTOR = '[itemprop="sku"]'

# Regex fallbacks for SKU in detail-page text (when itemprop is missing)
_SKU_LABELLED_PATTERNS = [
    r'КОД\s+([A-Za-z0-9]{6,})',
    r'Артикул[:\s]+([A-Za-z0-9][A-Za-z0-9\-]{4,})',
    r'Арт(?:икул)?[.:\s]+([A-Za-z0-9][A-Za-z0-9\-]{4,})',
    r'Код товару[:\s]+(\d{6,})',
    r'SKU[:\s]+([A-Za-z0-9\-]{5,})',
    r'Код[:\s]+(\d{6,10})',
]


# ── Utility extractors ────────────────────────────────────────

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


def _extract_price(node) -> float | None:
    el = _first(node.css(PRICE_MAIN_SELECTOR)) or _first(node.css(PRICE_FALLBACK_SELECTOR))
    if el is None:
        return None
    attr_price = el.attrib.get("content") or el.attrib.get("value")
    if attr_price:
        parsed = parse_price(attr_price)
        if parsed is not None:
            return parsed
    return parse_price(_text(el))


def _extract_name(node) -> str | None:
    el = _first(node.css(NAME_SELECTOR))
    if el is None:
        return None
    # Name lives inside an <a> inside the <p itemprop="name">
    return _text(el) or None


def _extract_url(node) -> str | None:
    el = _first(node.css(URL_SELECTOR))
    if el is None:
        el = _first(node.css(NAME_SELECTOR + " a"))
    if el is None:
        return None
    href = el.attrib.get("href")
    if not href:
        return None
    return urljoin(DOMAIN, href)


def _extract_sku_from_page(page) -> str | None:
    el = _first(page.css(SKU_SELECTOR))
    if el is not None:
        txt = _text(el) or el.attrib.get("content")
        if txt:
            return txt.strip()
    return None


def _extract_sku_from_text(text: str) -> str | None:
    for pattern in _SKU_LABELLED_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    m = re.search(r'(?<!\d)(\d{8,10})(?!\d)', text)
    if m:
        val = m.group(1)
        if val not in ('20240101', '20250101', '20260101'):
            return val
    return None


def _build_result(
    supplier: dict,
    name: str | None,
    price: float | None,
    url: str | None,
    sku: str | None,
) -> dict:
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


# ── Saved-URL fast path ───────────────────────────────────────

def _scrape_saved_url(supplier, label, log, saved_url) -> tuple[dict | None, str | None]:
    log(f"  Пряме посилання: {saved_url}")
    try:
        page = fetch_html(saved_url, timeout=30, mode=_FETCH_MODE)
    except Exception as exc:
        log(f"  → помилка завантаження ({exc})")
        return None, None

    status = getattr(page, "status", 200)
    if status and status >= 400:
        log(f"  → HTTP {status}, посилання застаріло")
        return None, None

    name_el = _first(page.css("h1")) or _first(page.css(NAME_SELECTOR))
    name = _text(name_el) if name_el else None

    price = _extract_price(page)
    sku = _extract_sku_from_page(page)
    if not sku:
        sku = _extract_sku_from_text(page.get_all_text() or "")

    if price is None:
        log("  → ціну не знайдено, посилання застаріло")
        return None, None

    if name and score_title(name, label) < DEFAULT_THRESHOLD:
        log(f"  → сторінка не збігається з товаром «{label[:40]}» (заголовок: {name[:40]})")
        return None, None

    log(f"  ✓ Знайдено за прямим посиланням: {(name or '')[:60]} — {price} ₴")
    result = _build_result(supplier, name, price, saved_url, sku)
    return result, saved_url


# ── Public entrypoint ─────────────────────────────────────────

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
            page = fetch_html(url, timeout=45, mode=_FETCH_MODE)
        except Exception as exc:
            log(f"  → помилка пошуку ({exc})")
            continue

        cards = page.css(CARD_SELECTOR)
        log(f"  → {len(cards)} карток-результатів")
        if not cards:
            continue

        best = pick_best_card(cards, label, title_selector=NAME_SELECTOR, log_fn=log)
        if best is None:
            log("  → жодна картка не збіглася з назвою")
            continue

        name = _extract_name(best)
        product_url = _extract_url(best)
        price = _extract_price(best)
        sku = _extract_sku_from_page(best)

        if not product_url:
            log("  → не вдалося витягти URL товару")
            continue

        if price is None:
            log("  → ціна відсутня у картці")
            return None, product_url

        # Fetch detail page only if we still need the SKU
        if not sku:
            try:
                detail = fetch_html(product_url, timeout=30, mode=_FETCH_MODE)
                sku = _extract_sku_from_page(detail)
                if not sku:
                    sku = _extract_sku_from_text(detail.get_all_text() or "")
                if sku:
                    log(f"  → артикул: {sku}")
            except Exception as exc:
                log(f"  → не вдалося завантажити сторінку товару ({exc})")

        log(f"  ✓ Знайдено: {(name or '')[:60]} — {price} ₴")
        result = _build_result(supplier, name, price, product_url, sku)
        return result, product_url

    log("  → товар не знайдено за жодним варіантом запиту")
    return None, None
