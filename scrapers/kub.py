"""
Scraper: КУБ (kub.in.ua) — Scrapling.
Search: /ua/search?filter_name=...
KUB is a heavy SPA — needs 10+ seconds for AJAX to load search results.
Uses a custom fetch with extended wait time.

Key discovery: KUB uses `filter_name` parameter (NOT `q`) for search.
The `?q=` param always returns "Немає товарів".
"""
import re
from datetime import date
from urllib.parse import quote_plus

from scrapers._scrapling_base import (
    fetch_html, normalize_search_query, parse_price,
    score_title, _text_of,
)
from matching.matcher import find_best_match, DEFAULT_THRESHOLD

DOMAIN = "kub.in.ua"
# IMPORTANT: KUB uses filter_name, NOT q
SEARCH_URL = "https://kub.in.ua/ua/search?filter_name={q}"

# CSS selectors for KUB product cards
CARD_SELECTOR = ".product-item"
TITLE_SELECTOR = ".name"
PRICE_SELECTOR = ".price"

# Price pattern for KUB: "1263 грн." or "622 грн."
_PRICE_RE = re.compile(r'(\d[\d\s]*(?:[.,]\d{1,2})?)\s*грн\.?', re.IGNORECASE)

# KUB is an SPA — search results render via AJAX. Use the shared cache-aware
# fetcher with an extended wait so the SPA has time to populate the DOM.
def _fetch_kub(url: str):
    return fetch_html(url, timeout=90, wait_ms=10000)


def scrape(supplier, label, log, saved_url=None):
    """Returns (item_dict | None, product_url | None)."""

    # ── Saved URL fast path ───────────────────────────────────
    if saved_url:
        log(f"  Пряме посилання: {saved_url}")
        try:
            page = _fetch_kub(saved_url)
            result = _extract_from_product_page(page, label)
            if result:
                result["url"] = saved_url
                log(f"  ✓ Знайдено за посиланням: {result['name'][:60]} — {result['price']} ₴")
                return result, saved_url
        except Exception as exc:
            log(f"  → помилка ({exc})")
        log("  → переходимо до пошуку")

    # ── Search ────────────────────────────────────────────────
    from scrapers.query_variations import generate_variations

    base_query = normalize_search_query(label)
    if not base_query:
        log("  → порожній запит")
        return None, None

    queries = generate_variations(base_query, max_variations=6)
    for query_idx, query in enumerate(queries):
        if not query:
            continue

        url = SEARCH_URL.format(q=quote_plus(query))
        if query_idx > 0:
            log(f"  → повторна спроба: '{query}'")
        else:
            log(f"  Пошук: {url}")
        try:
            page = _fetch_kub(url)
        except Exception as exc:
            log(f"  → помилка пошуку ({exc})")
            continue

        # ── Try CSS-based card extraction first ───────────────────
        result, product_url = _extract_from_cards(page, label, log)
        if result:
            return result, product_url

        # ── Fallback: text-based extraction ───────────────────────
        text = page.get_all_text() or ""
        if len(text) < 200:
            log("  → сторінка порожня")
            continue

        result = _find_in_text(text, label)
        if result:
            # Try to find product URL from page links
            product_url = _find_url(page, result["name"])
            if product_url:
                result["url"] = product_url
            log(f"  ✓ Знайдено (текст): {result['name'][:60]} — {result['price']} ₴")
            return result, product_url

    log("  → товар не знайдено за жодним варіантом запиту")
    return None, None


def _extract_from_cards(page, label: str, log):
    """Try CSS-based extraction from .product-item cards."""
    cards = page.css(CARD_SELECTOR)
    if not cards or len(cards) == 0:
        return None, None

    log(f"  → {len(cards)} карток")

    # Collect all card data: (name, price, url, card)
    card_data = []
    card_names = []

    for card in cards:
        # Extract title
        title_el = card.css(TITLE_SELECTOR)
        if not title_el:
            continue
        name = _text_of(title_el[0]).strip()
        if not name:
            continue

        # Extract price
        price_el = card.css(PRICE_SELECTOR)
        price = None
        if price_el:
            price_text = _text_of(price_el[0])
            # .price may contain extra text — extract with regex first
            m = _PRICE_RE.search(price_text)
            if m:
                price = parse_price(m.group(1))
            if price is None:
                price = parse_price(price_text)

        if not price or price <= 0:
            # Try regex on card text, skip delivery noise
            card_text = _text_of(card)
            for _cline in card_text.split('\n'):
                if 'доставка' in _cline.lower():
                    continue
                m = _PRICE_RE.search(_cline)
                if m:
                    p = parse_price(m.group(1))
                    if p and p > 10:
                        price = p
                        break

        if not price or price <= 0:
            continue

        # Extract URL
        links = card.css("a[href]")
        card_url = None
        if links:
            href = links[0].attrib.get("href", "")
            if href:
                if href.startswith("/"):
                    card_url = f"https://{DOMAIN}{href}"
                elif DOMAIN in href:
                    card_url = href

        card_data.append((name, price, card_url))
        card_names.append(name)

    if not card_names:
        log("  → жодна картка не збіглася з назвою")
        return None, None

    # Use matcher to find best card
    match = find_best_match(label, card_names, threshold=DEFAULT_THRESHOLD, top_n=3, log_fn=log)
    if match is None:
        log("  → жодна картка не збіглася з назвою")
        return None, None

    best_name, best_price, best_url = card_data[match.index]

    result = {
        "name": best_name,
        "price": best_price,
        "currency": "UAH",
        "unit": None,
        "brand": None,
        "sku": None,
        "specs": None,
        "supplier": "КУБ",
        "url": best_url,
        "date_scraped": date.today().isoformat(),
    }

    log(f"  ✓ Знайдено: {best_name[:60]} — {best_price} ₴")
    return result, best_url


def _extract_from_product_page(page, label: str):
    """Extract product info from a direct product page."""
    text = page.get_all_text() or ""
    if not text:
        return None

    # Try to get title from h1
    h1 = page.css("h1")
    name = _text_of(h1[0]).strip() if h1 else None

    # Try to get price
    price = None
    price_el = page.css(PRICE_SELECTOR)
    if price_el:
        price_text = _text_of(price_el[0])
        # .price may contain extra text like "Сума:622 грн.Вага:7кг..." — use regex
        m = _PRICE_RE.search(price_text)
        if m:
            price = parse_price(m.group(1))
        if price is None:
            price = parse_price(price_text)

    if not price:
        # Line-by-line to skip "доставка від 600 грн" delivery banner in the header
        for _line in text.split('\n'):
            _line = _line.strip()
            if not _line or 'доставка' in _line.lower():
                continue
            m = _PRICE_RE.search(_line)
            if m:
                p = parse_price(m.group(1))
                if p and p > 10:
                    price = p
                    break

    if not name or not price or price <= 0:
        return None

    # Verify the product matches the label
    if score_title(name, label) < DEFAULT_THRESHOLD:
        return None

    return {
        "name": name,
        "price": price,
        "currency": "UAH",
        "unit": None,
        "brand": None,
        "sku": None,
        "specs": None,
        "supplier": "КУБ",
        "url": None,
        "date_scraped": date.today().isoformat(),
    }


def _find_in_text(text: str, label: str):
    """Parse page text to find a product matching the label with a price.
    
    Skips header/footer noise and page titles to avoid false matches.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Skip lines that are clearly not product names
    _SKIP_PREFIXES = ("пошук -", "пошук в", "показати", "сортувати", "фільтр",
                      "купити в 1", "купити", "у наявності", "при покупці",
                      "безкоштовна доставка", "економ доставка", "код товару")

    candidates = []
    for i, line in enumerate(lines):
        # Skip very short or very long lines
        if not (10 <= len(line) <= 150):
            continue
        # Must contain letters
        if not re.search(r'[а-яА-ЯіІїЇєЄґҐa-zA-Z]', line):
            continue
        # Skip header/navigation/action lines
        if line.lower().startswith(_SKIP_PREFIXES):
            continue
        # Skip lines that are just category names or navigation
        if line.startswith("Каталог") or line.startswith("Меню"):
            continue

        # The line itself should NOT be a price line (we want product names)
        if _PRICE_RE.match(line.strip()):
            continue

        # Look for price in nearby lines (within 5 lines forward, 2 back)
        price = None
        for j in range(max(0, i - 2), min(len(lines), i + 6)):
            price_line = lines[j]
            # Skip delivery-related price lines
            if "доставка" in price_line.lower():
                continue
            m = _PRICE_RE.search(price_line)
            if m:
                p = parse_price(m.group(1))
                if p and p > 10:  # filter out "0 грн" and tiny values
                    price = p
                    break

        if price:
            candidates.append((line, price))

    if not candidates:
        return None

    # Use matcher to find best candidate
    candidate_names = [name for name, _ in candidates]
    match = find_best_match(label, candidate_names, threshold=DEFAULT_THRESHOLD, top_n=3)
    if match is None:
        return None

    best_name, best_price = candidates[match.index]

    return {
        "name": best_name,
        "price": best_price,
        "currency": "UAH",
        "unit": None,
        "brand": None,
        "sku": None,
        "specs": None,
        "supplier": "КУБ",
        "url": None,
        "date_scraped": date.today().isoformat(),
    }


def _find_url(page, product_name: str):
    """Try to find a product URL from page links."""
    try:
        links = page.css("a[href]")
        if not links:
            return None

        link_texts = []
        link_hrefs = []
        for link in links:
            href = link.attrib.get("href", "")
            if not href or len(href) < 10:
                continue
            if DOMAIN not in href and not href.startswith("/"):
                continue
            link_texts.append(_text_of(link))
            link_hrefs.append(href)

        if not link_texts:
            return None

        match = find_best_match(product_name, link_texts, threshold=DEFAULT_THRESHOLD)
        if match is None:
            return None

        best_url = link_hrefs[match.index]
        if best_url.startswith("/"):
            best_url = f"https://{DOMAIN}{best_url}"
        return best_url
    except:
        pass
    return None
