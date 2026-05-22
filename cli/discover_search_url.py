"""
Drive Patchright/Playwright headlessly to discover the *real* search URL
for each candidate site:

  1. Open the homepage (full JS rendering).
  2. Find a search <input>.
  3. Type a query, press Enter.
  4. Wait for navigation OR XHR.
  5. Print the final page URL (this is the search URL template).
  6. Also dump the first 30 anchor hrefs that look like product links.

Run once. Output guides the SiteConfig templates.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

# Use scrapling's bundled browser; speak to it directly via the page handle.
from scrapling.fetchers import DynamicFetcher

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


SITES = [
    ("teplodim",  "https://teplodim.com.ua/",     "котел"),
    ("santehmag", "https://santehmag.com.ua/",   "змішувач"),
    ("elektroin", "https://elektro.in.ua/",       "кабель"),
]


def make_action(query: str):
    def action(page):
        # Wait for the homepage to settle a bit
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Common search input selectors
        candidates = [
            'input[name="search"]',
            'input[name="q"]',
            'input[name="query"]',
            'input[type="search"]',
            'input[placeholder*="оиск"]',
            'input[placeholder*="ошук"]',
            'input[placeholder*="earch"]',
            'input.search-input',
            '#search input',
            '.search input',
        ]
        used = None
        for sel in candidates:
            try:
                loc = page.locator(sel).first
                if loc and loc.count() > 0:
                    loc.fill(query, timeout=5000)
                    used = sel
                    break
            except Exception:
                continue

        if used is None:
            return  # no search input found

        print(f"    used selector: {used}")
        # Submit: try pressing Enter
        try:
            loc = page.locator(used).first
            loc.press("Enter", timeout=5000)
        except Exception:
            pass

        # Wait for either navigation or new XHR/results
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
    return action


def probe(name: str, homepage: str, query: str) -> None:
    print(f"\n=== {name} :: search='{query}' ===")
    print(f"    homepage: {homepage}")
    try:
        page = DynamicFetcher.fetch(
            homepage,
            headless=True,
            network_idle=True,
            timeout=60000,
            page_action=make_action(query),
        )
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return

    final_url = getattr(page, "url", None) or homepage
    print(f"    final URL: {final_url}")

    # Save final HTML
    debug = Path(__file__).parent / "debug"
    debug.mkdir(exist_ok=True)
    out = debug / f"{name}_search_final.html"
    try:
        body = page.body if hasattr(page, "body") else ""
        if callable(body):
            body = body()
        if body:
            out.write_text(str(body), encoding="utf-8", errors="ignore")
            print(f"    saved {out.name} ({len(str(body))} chars)")
    except Exception as exc:
        print(f"    save failed: {exc}")

    # Print a few anchor hrefs to spot product links
    try:
        links = page.css("a[href]")
        prod_links: list[str] = []
        domain = urlparse(homepage).netloc
        for link in (links or [])[:200]:
            href = link.attrib.get("href", "")
            if not href:
                continue
            if href.startswith("#") or href.startswith("javascript:"):
                continue
            if domain not in href and not href.startswith("/"):
                continue
            # Product-page heuristic: contains /product/ /tovar/ /goods/ or 4+ digits
            low = href.lower()
            if any(k in low for k in ("/product", "/tovar", "/goods", "/item", "_p", "-p-", "id=", "product_id=")):
                prod_links.append(href)
        prod_links = list(dict.fromkeys(prod_links))[:10]
        if prod_links:
            print("    product-looking links:")
            for u in prod_links:
                print(f"      {u}")
    except Exception:
        pass


def main() -> None:
    for site_name, homepage, query in SITES:
        try:
            probe(site_name, homepage, query)
        except Exception as exc:
            print(f"  FATAL: {exc}")


if __name__ == "__main__":
    main()
