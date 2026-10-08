"""
Shared Scrapling helpers for PriceScout site scrapers.

All Scrapling-facing code lives here so individual scrapers only deal with
CSS selectors + lightweight picking logic. Fetching goes through Scrapling:
plain HTTP (FETCH_MODE_FAST) or a Patchright / camoufox browser
(FETCH_MODE_DYNAMIC / FETCH_MODE_STEALTH) for JS-heavy or protected sites.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from typing import Iterable, Optional

from scrapling.fetchers import StealthyFetcher, DynamicFetcher

# Scrapling's lightweight HTTP fetcher (no browser launch) — used for
# server-rendered sites where the full Patchright stack just wastes seconds.
try:
    from scrapling.fetchers import Fetcher as _FastFetcher
except ImportError:  # very old scrapling versions
    _FastFetcher = None

from matching.matcher import (
    normalize_text as matcher_normalize,
    calculate_match_score,
    find_best_match,
    find_top_matches,
    MatchResult,
    DEFAULT_THRESHOLD,
)


# ── Fetching ──────────────────────────────────────────────────

# Thread-safe URL cache (TTL-based). OrderedDict preserves insertion order
# so TTL eviction and the hard cap are both O(1) amortized — no sorting needed.
_fetch_cache: OrderedDict[str, tuple[float, object]] = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_TTL = 300  # seconds — long enough to span a whole batch
_CACHE_MAX = 500  # hard cap so the cache can't grow without bound

# Per-URL locks prevent multiple threads launching browsers for the same URL
# simultaneously (double-checked locking). Capped at _URL_LOCKS_MAX entries to
# avoid unbounded memory growth over very long batch runs.
_url_locks: dict[str, threading.Lock] = {}
_url_locks_guard = threading.Lock()
_URL_LOCKS_MAX = 2000


def _get_url_lock(url: str) -> threading.Lock:
    with _url_locks_guard:
        if url not in _url_locks:
            # Simple purge when the dict gets too large. Safe to do here
            # because we hold _url_locks_guard and no thread is mid-lookup.
            if len(_url_locks) >= _URL_LOCKS_MAX:
                _url_locks.clear()
            _url_locks[url] = threading.Lock()
        return _url_locks[url]


def _cache_get(url: str):
    with _cache_lock:
        entry = _fetch_cache.get(url)
        if entry and (time.time() - entry[0]) < _CACHE_TTL:
            return entry[1]
        return None


def _cache_set(url: str, result):
    with _cache_lock:
        now = time.time()
        _fetch_cache[url] = (now, result)
        _fetch_cache.move_to_end(url)  # keep insertion-order intact

        # Evict TTL-expired entries from the oldest end — O(k) not O(n log n)
        cutoff = now - _CACHE_TTL
        while _fetch_cache:
            oldest_key, (oldest_ts, _) = next(iter(_fetch_cache.items()))
            if oldest_ts < cutoff:
                del _fetch_cache[oldest_key]
            else:
                break  # remaining entries are newer

        # Hard cap: drop oldest entries until within budget
        while len(_fetch_cache) > _CACHE_MAX:
            _fetch_cache.popitem(last=False)


# Fetcher modes:
#   "fast"     — plain HTTP via Scrapling's Fetcher. ~10–50× faster than the
#                browser path; suitable for server-rendered sites (most
#                OpenCart-based stores fall in here).
#   "dynamic"  — DynamicFetcher (Patchright/Playwright). Needed when the
#                product cards are injected by JS after page load
#                (SPA-style search, AJAX live-search, etc.).
#   "stealth"  — StealthyFetcher (camoufox). Use when "dynamic" gets blocked
#                by Cloudflare or aggressive anti-bot heuristics.
FETCH_MODE_FAST = "fast"
FETCH_MODE_DYNAMIC = "dynamic"
FETCH_MODE_STEALTH = "stealth"


def _do_fetch(url: str, mode: str, timeout: int, headless: bool, wait_ms: int):
    if mode == FETCH_MODE_FAST and _FastFetcher is not None:
        # Plain HTTP path. No `wait_ms` or `headless` — they have no meaning
        # without a browser. Scrapling's Fetcher returns the same Adaptor
        # surface as the dynamic fetchers, so downstream code is unchanged.
        try:
            return _FastFetcher.get(url, timeout=timeout, stealthy_headers=True)
        except TypeError:
            # Older scrapling: `stealthy_headers` not supported.
            return _FastFetcher.get(url, timeout=timeout)
    if mode == FETCH_MODE_STEALTH:
        return StealthyFetcher.fetch(
            url,
            headless=headless,
            network_idle=True,
            timeout=timeout * 1000,
            page_action=lambda page: page.wait_for_timeout(wait_ms),
        )
    # Fall back to dynamic for everything else (including FETCH_MODE_FAST
    # when the fast fetcher isn't available).
    return DynamicFetcher.fetch(
        url,
        headless=headless,
        network_idle=True,
        timeout=timeout * 1000,
        page_action=lambda page: page.wait_for_timeout(wait_ms),
    )


def fetch_html(
    url: str,
    timeout: int = 30,
    headless: bool = True,
    wait_ms: int = 5000,
    mode: str = FETCH_MODE_DYNAMIC,
):
    """
    Fetch a page and return the Scrapling Response/Adaptor.

    `mode` controls which fetcher is used. Server-rendered sites should
    pass ``mode="fast"`` to skip the multi-second browser warm-up.

    Per-URL locking prevents multiple threads from launching separate fetches
    for the same URL simultaneously (double-checked locking).
    """
    # Cache key includes the mode so a fast-fetched response (with a
    # different DOM in the case of partially-JS pages) can't be confused
    # with a dynamic-fetched one.
    cache_key = f"{mode}::{url}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    with _get_url_lock(cache_key):
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        result = _do_fetch(url, mode, timeout, headless, wait_ms)
        _cache_set(cache_key, result)
        return result


# ── Price parsing ─────────────────────────────────────────────

_PRICE_STRIP = re.compile(r"[^\d.,\-]")


def parse_price(raw: Optional[str]) -> Optional[float]:
    """
    Convert a raw price string like '1 299,99 грн' or '$1,299.99' into a float.
    Returns None on empty/unparseable input.

    Algorithm:
      1. Strip anything that is not a digit, '.', ',', or '-'.
      2. The rightmost '.' or ',' is the decimal separator; the other
         (if any) is the thousands separator and gets dropped.
      3. Convert to float; failure → None.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    cleaned = _PRICE_STRIP.sub("", s).strip()
    if not cleaned or cleaned in ("-", ".", ","):
        return None

    last_dot = cleaned.rfind(".")
    last_comma = cleaned.rfind(",")

    if last_dot == -1 and last_comma == -1:
        normalized = cleaned
    elif last_dot > last_comma:
        # '.' is the decimal separator, drop ',' thousands
        normalized = cleaned.replace(",", "")
    elif last_comma > last_dot:
        # ',' is the decimal separator, drop '.' thousands, swap ','→'.'
        normalized = cleaned.replace(".", "").replace(",", ".")
    else:
        normalized = cleaned

    try:
        return float(normalized)
    except (ValueError, TypeError):
        return None


# ── Title scoring / card picking ──────────────────────────────

_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)

# Ukrainian normalization: ґ↔г, і↔i, ї→і, є→е, etc.
_NORM_MAP = str.maketrans({
    "ґ": "г", "і": "и", "ї": "и", "є": "е",
    "ё": "е", "'": "", "\u2019": "", "\u02bc": "",
})


def _normalize_ua(text: str) -> str:
    """Lowercase + collapse Ukrainian letter variants for fuzzy matching."""
    return text.lower().translate(_NORM_MAP)


def _words(text: str) -> list[str]:
    if not text:
        return []
    parts = _WORD_RE.split(_normalize_ua(text))
    return [p for p in parts if len(p) >= 2]


def score_title(title: Optional[str], label: str) -> float:
    """Fuzzy match score between a candidate title and the search label.

    Uses the matcher module for combined fuzzy scoring (partial_ratio,
    token_sort_ratio, token_set_ratio) with transliteration support.

    Returns a float 0..120 (higher = better match).
    Legacy callers that check ``score >= 1`` still work because the new
    matcher returns scores in the range 0..120 and a meaningful match
    always exceeds 1.
    """
    if not title:
        return 0.0
    return calculate_match_score(label, title)


def pick_best_card(
    cards: Iterable,
    label: str,
    *,
    title_selector: Optional[str] = None,
    min_words: int = 1,
    min_ratio: float = 0.3,
    threshold: float = DEFAULT_THRESHOLD,
    log_fn=None,
):
    """
    Walk a sequence of Scrapling card adaptors, score each by title overlap
    with `label`, and return the highest scorer that clears the threshold.

    `title_selector` is an optional CSS selector applied to each card to
    extract its title. If None, the card's own text is used.
    """
    ranked = pick_top_cards(
        cards, label,
        title_selector=title_selector,
        threshold=threshold,
        top_n=1,
        log_fn=log_fn,
    )
    return ranked[0] if ranked else None


def pick_top_cards(
    cards: Iterable,
    label: str,
    *,
    title_selector: Optional[str] = None,
    threshold: float = DEFAULT_THRESHOLD,
    top_n: int = 5,
    log_fn=None,
) -> list:
    """Like :func:`pick_best_card` but returns up to ``top_n`` cards ordered
    by match score, all of which clear the threshold and the matcher's
    key-token verification.

    The caller iterates the list and falls through to the next-best card
    when the top scorer is missing required data (no price, no href, etc.) —
    classifieds boards and aggregators routinely return "Договірна" first.
    """
    card_list = list(cards)
    if not card_list:
        return []
    titles = [_extract_title(c, title_selector) or "" for c in card_list]
    matches = find_top_matches(label, titles, threshold=threshold, top_n=top_n, log_fn=log_fn)
    return [card_list[m.index] for m in matches]


def _extract_title(card, title_selector: Optional[str]) -> str:
    if title_selector:
        try:
            matches = card.css(title_selector)
            if matches:
                text = _text_of(matches.first)
                if text:
                    return text
        except Exception:
            pass
    # fallback: entire card text
    return _text_of(card)


def _text_of(node) -> str:
    """Best-effort plain-text extractor for a Scrapling Adaptor element."""
    for attr in ("get_all_text", "text"):
        try:
            val = getattr(node, attr)
        except Exception:
            continue
        if callable(val):
            try:
                val = val()
            except Exception:
                continue
        if val is None:
            continue
        s = str(val).strip()
        if s:
            return s
    return ""


# ── Search query helpers ──────────────────────────────────────

_TRAIL_PARENS = re.compile(r"\s*\([^)]*\)\s*$", re.UNICODE)
_WS = re.compile(r"\s+", re.UNICODE)


def normalize_search_query(label: str) -> str:
    """
    Prep a material label for a site's `?q=` param:
      - collapse whitespace
      - drop a trailing parenthetical note like '(кг)' or '(брак)' once
    """
    if not label:
        return ""
    cleaned = _TRAIL_PARENS.sub("", label).strip()
    cleaned = _WS.sub(" ", cleaned)
    return cleaned

# ── Generic search-and-extract for thin scraper wrappers ──────

from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote_plus, urljoin


@dataclass
class SiteConfig:
    """Per-site configuration for the generic search_and_extract helper."""
    name: str                          # supplier display name
    domain: str                        # e.g. "buddvir.ua"
    search_url_template: str           # uses {q} placeholder
    card_selectors: list[str]          # tried in order; first non-empty wins
    title_selector: str                # CSS inside a card to get the title
    price_selectors: list[str]         # tried in order inside a card
    url_selector: Optional[str] = None # if None, href from title element
    sku_selectors: list[str] = field(default_factory=list)
    sku_text_patterns: list[str] = field(default_factory=lambda: [
        r'(?:Код|Артикул|SKU)[:\s]+([A-Za-z0-9][A-Za-z0-9\-]{3,})',
    ])
    fetch_timeout: int = 45
    check_cloudflare: bool = False
    wait_ms: int = 5000  # ms to wait after page load for AJAX content (browser modes only)
    # Default to the (slow) browser fetcher to preserve behaviour for any
    # caller that hasn't been switched yet. Server-rendered sites should
    # override this to ``FETCH_MODE_FAST`` to skip browser warm-up.
    fetcher_mode: str = FETCH_MODE_DYNAMIC


def _first(matches):
    if not matches:
        return None
    try:
        return matches.first
    except Exception:
        return matches[0] if len(matches) > 0 else None


def _cloudflare_blocked(page) -> bool:
    status = getattr(page, "status", 200)
    if status and status in (403, 503, 520, 521, 522):
        return True
    try:
        title_el = _first(page.css("title"))
        if title_el:
            t = _text_of(title_el).lower()
            if any(w in t for w in ("cloudflare", "attention required", "just a moment")):
                return True
    except Exception:
        pass
    return False


def _extract_price_from_node(node, selectors: list[str]) -> Optional[float]:
    """Try each price selector in order; check attributes then text."""
    for sel in selectors:
        el = _first(node.css(sel))
        if el is None:
            continue
        # Try common numeric attributes first
        for attr_name in ("content", "data-price-amount", "value", "data-price"):
            attr_val = el.attrib.get(attr_name)
            if attr_val:
                p = parse_price(attr_val)
                if p is not None:
                    return p
        # Fallback to text
        p = parse_price(_text_of(el))
        if p is not None:
            return p
    return None


def _extract_url_from_card(card, cfg: SiteConfig) -> Optional[str]:
    """Get product URL from a card element."""
    el = None
    if cfg.url_selector:
        el = _first(card.css(cfg.url_selector))
    if el is None:
        el = _first(card.css(cfg.title_selector))
    if el is None:
        return None
    href = el.attrib.get("href")
    if not href:
        return None
    return urljoin(f"https://{cfg.domain}", href)


def _extract_sku_from_page(page, cfg: SiteConfig) -> Optional[str]:
    """Try CSS selectors then regex patterns on the page text."""
    for sel in cfg.sku_selectors:
        el = _first(page.css(sel))
        if el is not None:
            txt = _text_of(el) or el.attrib.get("content")
            if txt and txt.strip():
                return txt.strip()
    # Regex fallback on full page text
    try:
        full_text = page.get_all_text() or ""
    except Exception:
        full_text = ""
    for pattern in cfg.sku_text_patterns:
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def search_and_extract(
    cfg: SiteConfig,
    label: str,
    log,
    saved_url: Optional[str] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """
    Generic search → card pick → detail SKU flow.
    Returns (result_dict, product_url) or (None, None).
    """

    # ── Saved-URL fast path ───────────────────────────────────
    if saved_url:
        log(f"  Пряме посилання: {saved_url}")
        try:
            page = fetch_html(saved_url, timeout=cfg.fetch_timeout, wait_ms=cfg.wait_ms, mode=cfg.fetcher_mode)
        except Exception as exc:
            log(f"  → помилка завантаження ({exc})")
            return None, None

        if cfg.check_cloudflare and _cloudflare_blocked(page):
            log("  → Cloudflare заблокував, пропускаємо")
            return None, None

        status = getattr(page, "status", 200)
        if status and status >= 400:
            log(f"  → HTTP {status}, посилання застаріло")
            return None, None

        price = _extract_price_from_node(page, cfg.price_selectors)
        if price is None:
            log("  → ціну не знайдено, посилання застаріло")
            # fall through to search
        else:
            h1 = _first(page.css("h1"))
            name = _text_of(h1) if h1 else None
            # Validate that the saved URL really points at this product —
            # if the page is a category page or a stale URL pointing at a
            # different SKU, fall through to a fresh search.
            if not name or score_title(name, label) < DEFAULT_THRESHOLD:
                log(f"  → сторінка не схожа на товар «{label[:40]}» (заголовок: {(name or '')[:40]})")
            else:
                sku = _extract_sku_from_page(page, cfg)
                log(f"  ✓ Знайдено за прямим посиланням: {(name or '')[:60]} — {price} ₴")
                return _build(cfg, name, price, saved_url, sku), saved_url

    # ── Search flow ───────────────────────────────────────────
    from scrapers.query_variations import generate_variations

    base_query = normalize_search_query(label)
    if not base_query:
        log("  → порожній запит")
        return None, None

    queries = generate_variations(base_query, max_variations=6)
    for query_idx, query in enumerate(queries):
        if not query:
            continue

        url = cfg.search_url_template.format(q=quote_plus(query))
        if query_idx > 0:
            log(f"  → повторна спроба: '{query}'")
        else:
            log(f"  Пошук: {url}")
        try:
            page = fetch_html(url, timeout=cfg.fetch_timeout, wait_ms=cfg.wait_ms, mode=cfg.fetcher_mode)
        except Exception as exc:
            log(f"  → помилка пошуку ({exc})")
            continue

        if cfg.check_cloudflare and _cloudflare_blocked(page):
            log("  → Cloudflare заблокував пошук, пропускаємо")
            return None, None

        # Find cards using the first selector that returns results
        cards = None
        for sel in cfg.card_selectors:
            found = page.css(sel)
            if found and len(found) > 0:
                cards = found
                break
        if not cards:
            log("  → карток не знайдено")
            continue

        log(f"  → {len(cards)} карток")

        ranked = pick_top_cards(cards, label, title_selector=cfg.title_selector, log_fn=log, top_n=5)
        if not ranked:
            log("  → жодна картка не збіглася з назвою")
            continue

        # Walk top candidates: marketplace listings often have "договірна"
        # (no price) on the highest scorer, so falling through to the next
        # one rescues queries that otherwise return None for no good reason.
        chosen = None
        for best in ranked:
            name = _text_of(_first(best.css(cfg.title_selector))) if cfg.title_selector else _text_of(best)
            product_url = _extract_url_from_card(best, cfg)
            price = _extract_price_from_node(best, cfg.price_selectors)
            if product_url and price is not None:
                chosen = (name, product_url, price, best)
                break

        if chosen is None:
            log("  → серед топ-кандидатів немає картки з ціною/URL")
            continue

        name, product_url, price, best = chosen

        # Optional detail page for SKU
        sku = None
        if cfg.sku_selectors or cfg.sku_text_patterns:
            try:
                detail = fetch_html(product_url, timeout=cfg.fetch_timeout, wait_ms=cfg.wait_ms, mode=cfg.fetcher_mode)
                if not (cfg.check_cloudflare and _cloudflare_blocked(detail)):
                    sku = _extract_sku_from_page(detail, cfg)
                    if sku:
                        log(f"  → артикул: {sku}")
            except Exception as exc:
                log(f"  → не вдалося завантажити сторінку товару ({exc})")

        log(f"  ✓ Знайдено: {(name or '')[:60]} — {price} ₴")
        return _build(cfg, name, price, product_url, sku), product_url

    log("  → товар не знайдено за жодним варіантом запиту")
    return None, None


def _build(cfg: SiteConfig, name, price, url, sku) -> dict:
    return {
        "name":         name or "",
        "price":        price,
        "currency":     "UAH",
        "unit":         None,
        "brand":        None,
        "sku":          sku,
        "specs":        None,
        "supplier":     cfg.name,
        "url":          url,
        "date_scraped": date.today().isoformat(),
    }


# ── Text-based fallback extraction ────────────────────────────
# For sites where CSS selectors don't work (JS-rendered content that
# DynamicFetcher captures as text but not as structured DOM elements).

# Match patterns like:
#   "1 299.99 грн", "622 грн", "1245,74 ₴", "1 234 567,89 грн"
# But reject malformed prices like "1 023 67 грн" (space between non-thousands
# groups) — they would parse to inflated values like 102367.
#
# A valid integer part is either:
#   - a single digit run (e.g. "622", "1023", "123456"), OR
#   - one to three digits followed by groups of exactly three digits separated
#     by a single space (e.g. "1 023", "1 234 567").
_PRICE_INT_RE = r'(?:\d{1,3}(?:\s\d{3})+|\d+)'
_PRICE_LINE_RE = re.compile(
    r'(' + _PRICE_INT_RE + r'(?:[.,]\d{1,2})?)\s*(?:грн\.?|₴|UAH|uah)',
    re.IGNORECASE
)


def text_based_extract(
    cfg: SiteConfig,
    label: str,
    log,
    saved_url: Optional[str] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """
    Fallback extraction that works on the full page text rather than
    CSS-selected card elements. Used for JS-heavy sites where cards
    don't appear in the DOM as structured elements.

    Strategy:
      1. Fetch the search page (or saved URL).
      2. Get the full page text.
      3. Split into lines, find lines that look like product names.
      4. For each candidate, look for a price nearby (within 3 lines).
      5. Score candidates against the label and pick the best.
      6. Try to find a product URL from the page links.
    """
    # ── Fetch ─────────────────────────────────────────────────
    if saved_url:
        log(f"  Пряме посилання: {saved_url}")
        try:
            page = fetch_html(saved_url, timeout=cfg.fetch_timeout, wait_ms=cfg.wait_ms, mode=cfg.fetcher_mode)
        except Exception as exc:
            log(f"  → помилка завантаження ({exc})")
            return None, None

        if cfg.check_cloudflare and _cloudflare_blocked(page):
            log("  → Cloudflare заблокував, пропускаємо")
            return None, None

        # Saved URL points at a single product page — extract directly
        # from the page H1 / configured selectors instead of running fuzzy
        # search over the entire text (which can wrongly pick up items
        # from "related products" blocks).
        result = _extract_from_saved_url_page(page, label, cfg, log)
        if result:
            result["url"] = saved_url
            return result, saved_url
        log("  → не знайдено за прямим посиланням, переходимо до пошуку")

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

        url = cfg.search_url_template.format(q=quote_plus(query))
        if query_idx > 0:
            log(f"  → повторна спроба: '{query}'")
        else:
            log(f"  Пошук: {url}")
        try:
            page = fetch_html(url, timeout=cfg.fetch_timeout, wait_ms=cfg.wait_ms, mode=cfg.fetcher_mode)
        except Exception as exc:
            log(f"  → помилка пошуку ({exc})")
            continue

        if cfg.check_cloudflare and _cloudflare_blocked(page):
            log("  → Cloudflare заблокував пошук, пропускаємо")
            return None, None

        # First try CSS-based extraction (in case selectors work)
        cards = None
        for sel in cfg.card_selectors:
            found = page.css(sel)
            if found and len(found) > 0:
                cards = found
                break

        if cards and len(cards) > 0:
            log(f"  → {len(cards)} карток")
            for best in pick_top_cards(cards, label, title_selector=cfg.title_selector, log_fn=log, top_n=5):
                name = _text_of(_first(best.css(cfg.title_selector))) if cfg.title_selector else _text_of(best)
                product_url = _extract_url_from_card(best, cfg)
                price = _extract_price_from_node(best, cfg.price_selectors)
                if product_url and price is not None:
                    sku = None
                    if cfg.sku_selectors or cfg.sku_text_patterns:
                        try:
                            detail = fetch_html(product_url, timeout=cfg.fetch_timeout, wait_ms=cfg.wait_ms, mode=cfg.fetcher_mode)
                            sku = _extract_sku_from_page(detail, cfg)
                            if sku:
                                log(f"  → артикул: {sku}")
                        except Exception:
                            pass
                    log(f"  ✓ Знайдено: {(name or '')[:60]} — {price} ₴")
                    return _build(cfg, name, price, product_url, sku), product_url

        # ── Text-based fallback ───────────────────────────────────
        text = ""
        try:
            text = page.get_all_text() or ""
        except Exception:
            pass

        if not text or len(text) < 100:
            log("  → сторінка порожня")
            continue

        result = _text_find_product(text, label, cfg, log)
        if result:
            # Try to find a URL from page links
            product_url = _find_product_url_from_page(page, result.get("name", ""), cfg)
            if product_url:
                result["url"] = product_url
            return result, product_url

    log("  → товар не знайдено в тексті сторінки")
    return None, None


def _extract_from_saved_url_page(
    page, label: str, cfg: SiteConfig, log
) -> Optional[dict]:
    """
    Extract product data from a single product page reached via a saved URL.

    Strategy:
      1. Prefer the page H1 for the title (most reliable on a product page).
         `cfg.title_selector` is usually a *card* selector (e.g. ``a[href]``)
         which would match the first navigation link on a category page —
         we only use it as a last-resort fallback.
      2. Extract the price via `cfg.price_selectors` and validate that the
         saved URL really points at a product matching the label. If the
         page is actually a category listing (multiple products, none of
         which match the label well), bail out and let the caller fall
         through to a fresh search.
    """
    name: Optional[str] = None
    price: Optional[float] = None

    # 1. Prefer H1 (real product pages always have one)
    try:
        h1 = page.css("h1")
        if h1:
            name = _text_of(h1[0]).strip() or None
    except Exception:
        pass

    # Fallback: configured title selector (rarely needed — only when the
    # page lacks an H1, e.g. some custom landing pages)
    if not name and cfg.title_selector:
        try:
            title_el = _first(page.css(cfg.title_selector))
            if title_el:
                name = _text_of(title_el).strip() or None
        except Exception:
            pass

    # Try price from configured selectors
    if cfg.price_selectors:
        try:
            price = _extract_price_from_node(page, cfg.price_selectors)
        except Exception:
            price = None

    # 2. Text fallback for price
    if price is None:
        try:
            text = page.get_all_text() or ""
        except Exception:
            text = ""
        if text:
            for line in text.split("\n"):
                if "доставк" in line.lower():
                    continue
                m = _PRICE_LINE_RE.search(line)
                if m:
                    p = parse_price(m.group(1))
                    if p and p > 10:  # filter trivial "0 грн" / delivery noise
                        price = p
                        break

    if name is None or price is None or price <= 0:
        return None

    # 3. Sanity-check: the title from the saved URL must actually look like
    # the label. Otherwise the URL is stale or points at a category page;
    # let the caller fall through to a fresh search.
    if score_title(name, label) < DEFAULT_THRESHOLD:
        log(f"  → сторінка не схожа на товар «{label[:40]}» (заголовок: {name[:40]})")
        return None

    sku: Optional[str] = None
    if cfg.sku_selectors or cfg.sku_text_patterns:
        try:
            sku = _extract_sku_from_page(page, cfg)
        except Exception:
            sku = None

    log(f"  ✓ Знайдено за посиланням: {name[:60]} — {price} ₴")
    return _build(cfg, name, price, None, sku)


def _text_find_product(
    text: str, label: str, cfg: SiteConfig, log
) -> Optional[dict]:
    """
    Parse page text to find a product matching the label.
    Returns a result dict or None.
    """
    lines = text.split("\n")
    lines = [l.strip() for l in lines if l.strip()]

    # Skip lines that are clearly navigation/UX/footer copy, not product names
    _NOISE_PREFIXES = (
        "пошук", "категорі", "фільтр", "сортув", "показ",
        "меню", "каталог", "купити", "у наяв", "в налич",
        "доставк", "оплат", "знижк", "акція",
        "Код товару", "артикул", "sku", "комент",
        "відгук", "головна", "порівнять", "додати",
        "при покупц", "безкоштов",
    )

    # Build candidates: lines that look like product names (5-100 chars, contain letters)
    name_price_pairs: list[tuple[str, float]] = []
    candidate_names: list[str] = []

    for i, line in enumerate(lines):
        if not (5 <= len(line) <= 120):
            continue
        if not re.search(r'[а-яА-ЯіІїЇєЄґҐa-zA-Z]', line):
            continue
        low = line.lower()
        if any(low.startswith(p) for p in _NOISE_PREFIXES):
            continue
        # The line itself should not be a pure price line
        if _PRICE_LINE_RE.match(line):
            continue

        # Check if there's a price within the next 5 lines
        price = None
        for j in range(max(0, i-2), min(len(lines), i+5)):
            neighbour = lines[j]
            if "доставк" in neighbour.lower():
                continue
            price_match = _PRICE_LINE_RE.search(neighbour)
            if price_match:
                raw_price = price_match.group(1)
                p = parse_price(raw_price)
                if p and p > 10:  # filter trivial "0 грн" noise
                    price = p
                    break
        if price and price > 0:
            name_price_pairs.append((line, price))
            candidate_names.append(line)

    if not candidate_names:
        return None

    # Use the matcher to find the best match
    result = find_best_match(
        label, candidate_names,
        threshold=DEFAULT_THRESHOLD,
        top_n=3,
        log_fn=log,
    )

    if result is None:
        return None

    best_name, best_price = name_price_pairs[result.index]
    log(f"  ✓ Знайдено (текст): {best_name[:60]} — {best_price} ₴")
    return _build(cfg, best_name, best_price, None, None)


def _find_product_url_from_page(page, product_name: str, cfg: SiteConfig) -> Optional[str]:
    """Try to find a product URL from page links that matches the product name."""
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
            if cfg.domain not in href and not href.startswith("/"):
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
            best_url = f"https://{cfg.domain}{best_url}"
        return best_url
    except Exception:
        pass
    return None