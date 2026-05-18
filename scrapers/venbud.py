"""
Scraper: Вен Буд (venbud.ua) — Scrapling.
Search: AJAX live search endpoint (OpenCart oct_live_search module).

The standard search page doesn't render product results (SPA issue).
Instead, we POST to the live search AJAX endpoint which returns HTML
with product cards that we can parse.
"""
import re
from datetime import date
from urllib.parse import quote_plus

from scrapers._scrapling_base import (
    normalize_search_query, parse_price, score_title, _text_of, fetch_html,
)
from matcher import find_best_match, DEFAULT_THRESHOLD

DOMAIN = "venbud.ua"
AJAX_URL = "https://venbud.ua/index.php?route=octemplates/module/oct_live_search"

# Price pattern: "1 023.67 ₴" or "1 023.67 грн"
_PRICE_RE = re.compile(r'(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(?:₴|грн\.?|UAH)', re.IGNORECASE)


def _fetch_ajax_search(query: str):
    """
    Fetch search results via the AJAX live search endpoint.
    Uses DynamicFetcher to navigate to the site first (for cookies/session),
    then makes the AJAX request via page evaluation.
    """
    import requests

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html, */*; q=0.01',
        'Accept-Language': 'uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7',
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Referer': 'https://venbud.ua/',
        'Origin': 'https://venbud.ua',
    }

    resp = requests.post(
        AJAX_URL,
        data=f"key={quote_plus(query)}",
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.text


def _parse_ajax_results(html: str, label: str):
    """
    Parse the AJAX live search HTML response to find the best matching product.
    Returns (result_dict, product_url) or (None, None).
    """
    if not html or len(html) < 50:
        return None, None

    # Extract product items from the HTML
    # Each item has: title link, price, SKU code, product URL
    items = re.findall(
        r'<a[^>]*href="([^"]*)"[^>]*class="ds-livesearch-item-title[^"]*"[^>]*>([^<]+)</a>',
        html
    )

    if not items:
        return None, None

    # Extract prices - they appear as "1 023.67 ₴" in .ds-price-new
    prices = re.findall(
        r'<div[^>]*class="ds-price-new[^"]*"[^>]*>([^<]+)</div>',
        html
    )

    # Extract SKU codes - format: <span>Код товару: </span>20118
    skus = re.findall(
        r'class="ds-livesearch-item-code[^"]*"[^>]*>[^<]*<span>[^<]*</span>\s*(\d+)',
        html
    )

    # Build candidates
    candidates = []
    for i, (url, name) in enumerate(items):
        name = name.strip()
        price = None
        if i < len(prices):
            price_text = prices[i].strip()
            price = parse_price(price_text)

        sku = None
        if i < len(skus):
            sku = skus[i].strip()

        if price and price > 0:
            candidates.append((name, price, url, sku))

    if not candidates:
        return None, None

    # Use matcher to find best candidate
    candidate_names = [name for name, _, _, _ in candidates]
    match = find_best_match(label, candidate_names, threshold=DEFAULT_THRESHOLD, top_n=3)
    if match is None:
        return None, None

    best_name, best_price, best_url, best_sku = candidates[match.index]

    result = {
        "name": best_name,
        "price": best_price,
        "currency": "UAH",
        "unit": None,
        "brand": None,
        "sku": best_sku,
        "specs": None,
        "supplier": "Вен Буд",
        "url": best_url,
        "date_scraped": date.today().isoformat(),
    }
    return result, best_url


def scrape(supplier, label, log, saved_url=None):
    """Returns (item_dict | None, product_url | None)."""

    # ── Saved URL fast path ───────────────────────────────────
    if saved_url:
        log(f"  Пряме посилання: {saved_url}")
        try:
            page = fetch_html(saved_url, timeout=45)
            text = page.get_all_text() or ""
            price_match = _PRICE_RE.search(text)
            if price_match:
                price = parse_price(price_match.group(1))
                if price and price > 0:
                    h1 = page.css("h1")
                    name = _text_of(h1[0]) if h1 and len(h1) > 0 else label
                    if score_title(name, label) < DEFAULT_THRESHOLD:
                        log(f"  → сторінка не збігається з товаром «{label[:40]}» (заголовок: {name[:40]})")
                    else:
                        log(f"  ✓ Знайдено за посиланням: {name[:60]} — {price} ₴")
                        return {
                            "name": name,
                            "price": price,
                            "currency": "UAH",
                            "unit": None,
                            "brand": None,
                            "sku": None,
                            "specs": None,
                            "supplier": "Вен Буд",
                            "url": saved_url,
                            "date_scraped": date.today().isoformat(),
                        }, saved_url
        except Exception as exc:
            log(f"  → помилка ({exc})")
        log("  → переходимо до пошуку")

    # ── AJAX Search ───────────────────────────────────────────
    query = normalize_search_query(label)
    if not query:
        log("  → порожній запит")
        return None, None

    # Try the full query first
    result, product_url = _try_ajax_search(query, label, log)
    if result:
        return result, product_url

    # If no results at all, try individual words (longest first)
    words = [w for w in query.split() if len(w) >= 4]
    tried = {query.lower()}
    for word in sorted(words, key=len, reverse=True):
        if word.lower() in tried:
            continue
        tried.add(word.lower())
        log(f"  → повторна спроба: '{word}'")
        result, product_url = _try_ajax_search(word, label, log)
        if result:
            return result, product_url

    log("  → товар не знайдено")
    return None, None


def _try_ajax_search(query: str, label: str, log) -> tuple:
    """Try AJAX search with given query, return (result, url) or (None, None)."""
    log(f"  Пошук (AJAX): {query}")
    try:
        html = _fetch_ajax_search(query)
    except Exception as exc:
        log(f"  → помилка AJAX пошуку ({exc})")
        return None, None

    if not html or len(html) < 50:
        log("  → порожня відповідь")
        return None, None

    result, product_url = _parse_ajax_results(html, label)
    if result:
        log(f"  ✓ Знайдено: {result['name'][:60]} — {result['price']} ₴")
        return result, product_url

    return None, None
