"""
elektro.in.ua deep probe — wait longer for JS to populate, scroll, capture XHR.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from scrapling.fetchers import DynamicFetcher
from urllib.parse import quote_plus

DEBUG = Path(__file__).parent / "debug"
DEBUG.mkdir(exist_ok=True)


def action_with_xhr_capture(page):
    """Wait long, scroll to trigger any lazy load, capture all responses."""
    responses = []
    def on_response(resp):
        try:
            url = resp.url
            if any(k in url.lower() for k in ('search', 'product', 'ajax', 'live', 'catalog')):
                responses.append((resp.status, url))
        except Exception:
            pass
    page.on("response", on_response)

    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass

    page.wait_for_timeout(5000)
    # Scroll down to trigger lazy load
    for _ in range(3):
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(1500)

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3000)

    print(f"    captured {len(responses)} relevant XHRs:")
    for status, url in responses[:15]:
        short = url[:140]
        print(f"      [{status}] {short}")


for q in ["кабель", "автомат"]:
    url = f"https://elektro.in.ua/ua/index.php?route=product/search&search={quote_plus(q)}"
    print(f"\n=== elektro :: {q!r} ===")
    print(f"    {url}")
    try:
        page = DynamicFetcher.fetch(
            url, headless=True, network_idle=True, timeout=60000,
            page_action=action_with_xhr_capture,
        )
    except Exception as exc:
        print(f"    ERROR: {exc}")
        continue
    body = page.body if hasattr(page, "body") else ""
    if callable(body): body = body()
    body = str(body) if body else ""
    out = DEBUG / f"elektro_deep_{q}.html"
    out.write_text(body, encoding="utf-8", errors="ignore")
    print(f"    saved {out.name} ({len(body)} chars)")

    # Check for products now
    for sel in [".product-thumb", ".product-layout", "[itemtype*='Product']",
                ".product", ".product-card", "div.item-product",
                ".product-grid > div", ".product-list-item"]:
        try:
            found = page.css(sel)
            if found and len(found) > 0:
                print(f"    cards via {sel}: {len(found)}")
        except Exception:
            pass
