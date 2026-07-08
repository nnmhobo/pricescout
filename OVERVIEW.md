# PriceScout — Technical Overview (Agentic Coding Reference)

This document is the coding reference for PriceScout. It covers every module, all data flows, the full API surface, the database schema, and the gotchas to know before editing the codebase. Read this before touching any file.

> **Verified against code on 2026-07-04.** If you change behavior described here, update this file in the same session. Known drift traps are marked ⚠ throughout.

---

## 1. Purpose

PriceScout is a local Flask web app (Windows, single-user) that:

1. Imports construction-material line items from АВК-5 estimate files (`.xls`/`.xlsx`)
2. Searches 13 Ukrainian supplier websites for each material
3. Shows a side-by-side price comparison table and exports to Excel

All scraping is done with **Scrapling** (HTTP fetcher + optional Chromium via Scrapling's Dynamic/Stealthy fetchers). There is **no Claude API call** in the scraping pipeline. Fuzzy matching of product names uses **rapidfuzz**.

---

## 2. Directory Structure

```
pricescout/
│
├── app.py                  # Flask app + index route (no factory function; module-level `app`)
├── README.md               # User-facing readme, English (renamed from README_EN.md)
├── README_UA.md            # User-facing readme, Ukrainian
├── START.bat               # Windows launcher (venv + deps + `scrapling install`)
├── requirements.txt        # flask, scrapling[fetchers], lxml, xlrd, pandas, openpyxl, python-dotenv, rapidfuzz, requests
├── .env                    # (not committed) env overrides
├── pricescout.db           # SQLite database (WAL mode)
│
├── core/
│   ├── core.py             # Shared in-memory state dict, log(), save/load_last_run(), normalize_label()
│   ├── runner.py           # Scrape orchestrator — ThreadPoolExecutor fan-out
│   ├── item_db.py          # All SQLite access (init_db, CRUD, migrations)
│   └── suppliers.py        # SUPPLIER_REGISTRY + build_suppliers() → SUPPLIERS
│
├── routes/
│   ├── scrape.py           # /api/scrape, /api/scrape/batch, /api/stop, /api/status, /api/results, /api/discover, /api/config
│   ├── items.py            # /api/items CRUD, /api/availability, /api/items/<id>/price-history
│   ├── exports.py          # /api/export/excel, /api/exports, /api/export/price-matrix
│   ├── kostoris.py         # /api/kostoris/parse, /api/kostoris/import, /api/kostoris/last
│   └── projects.py         # /api/projects CRUD + summary + export
│
├── scrapers/
│   ├── _scrapling_base.py  # Fetch helpers + cache, price parser, SiteConfig, search_and_extract, text_based_extract
│   ├── query_variations.py # generate_variations() — search query alternatives (UA→RU, synonyms, brand codes)
│   ├── query_simplifier.py # simplify_label() — shortens spec-style labels ("Болти ... 12 мм" → "Болти 12")
│   ├── epicentr.py         # Епіцентр К     — custom, FAST
│   ├── ars.py              # АРС            — custom, STEALTH
│   ├── buddvir.py          # Будівельний Двір — text_based_extract, FAST
│   ├── kub.py              # КУБ            — custom, DYNAMIC (SPA, wait_ms=10000, filter_name= param)
│   ├── venbud.py           # Вен Буд        — custom, DYNAMIC
│   ├── budpostach.py       # Будпостач      — text_based_extract, FAST
│   ├── m2.py               # М2             — search_and_extract, FAST (+ single-word retry fallback)
│   ├── vista.py            # Віста          — search_and_extract, FAST
│   ├── megatrade.py        # Мегатрейд СМ   — text_based_extract, FAST
│   ├── budia.py            # Будія          — text_based_extract, FAST
│   ├── teplodim.py         # ТеплоДiм       — search_and_extract, FAST (HVAC specialist)
│   ├── prom.py             # Prom.ua        — search_and_extract, FAST (marketplace)
│   └── olx.py              # OLX            — search_and_extract, FAST (classifieds)
│
├── matching/
│   ├── matcher.py          # Fuzzy matcher (rapidfuzz, transliteration, synonyms)
│   ├── monitorable.py      # is_monitorable(label) — keyword blocklist
│   ├── category_routing.py # Category → supplier ID list mapping + label-keyword override
│   └── search_label_converter.py  # convert_label() + convert_all_items() CLI to fill items.search_label
│
├── parsers/
│   └── kostoris_parser.py  # АВК-5 Excel parser → list of material dicts
│
├── templates/
│   └── index.html          # Single-page app shell (Jinja2, all panels inline)
│
├── static/
│   ├── css/app.css         # All styles (dark/light mode via [data-theme] attr)
│   └── js/app.js           # All frontend logic (~2000 lines, vanilla JS, top-level script)
│
├── data/
│   ├── last_run.json       # Persisted results from most recent scrape run
│   └── last_import.json    # Persisted last кошторис parse result
│
├── exports/                # Generated Excel files (served by /api/exports/<filename>)
├── debug/                  # HTML snapshots dir (created at startup, dev aid)
│
├── tests/                  # 10 test files, all pure-logic, no network (see §16)
└── scripts/                # probe2.py, probe3_elektro.py, probe_new_sites.py — one-off discovery scripts
```

---

## 3. Database Schema

**File:** `pricescout.db` — SQLite, WAL mode, `PRAGMA foreign_keys=ON`.

All access goes through `core/item_db.py`, which uses a `@contextmanager get_conn()` helper that auto-commits or auto-rolls-back and opens a **new connection per call** (`check_same_thread=False`).

### `items`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | ⚠ NOT a UUID. `add_item`: `datetime.now().strftime("%Y%m%d%H%M%S%f")`. `batch_add_items`: `"%Y%m%d%H%M%S" + f"{idx:06d}"` |
| label | TEXT UNIQUE | Material name (display form). Dedupe key for imports. |
| created | TEXT | ISO date `YYYY-MM-DD` |
| source | TEXT | `'manual'` or `'kostoris'` |
| avk_code | TEXT | АВК-5 resource code (e.g. `С111-2`). `add_item` rejects duplicates by code. |
| category | TEXT | Derived from code by the parser; used for supplier routing |
| qty | REAL | Quantity from estimate |
| unit | TEXT | Unit of measure (м², кг, шт, …) |
| estimate_unit_price | REAL | Unit price from кошторис |
| monitorable | INT | 1=yes, 0=skip (set by `is_monitorable()` at insert) |
| manual_price | REAL | User-set override price (item level, rarely used) |
| search_label | TEXT | Shorter search query override. ⚠ NOT settable via PATCH /api/items — only via `matching/search_label_converter.py` CLI or direct DB write. |
| project_id | TEXT | ⚠ Legacy column. The `project_items` junction table is the source of truth; routes only write the junction. |

### `supplier_entries`
| Column | Type | Notes |
|---|---|---|
| item_id | TEXT | PK part; FK → items.id ON DELETE CASCADE |
| supplier_id | TEXT | PK part; e.g. `'epicentr'`, `'kub'` |
| url | TEXT | Last known product URL |
| found | INT | 1=product exists on this supplier, 0=not found |
| last_checked | TEXT | `YYYY-MM-DD HH:MM` |
| last_price | REAL | Price from last scrape |
| manual_price | REAL | User override price for this result |
| comment | TEXT | User note for this result |

### `projects`
| Column | Type |
|---|---|
| id | TEXT PK (timestamp string) |
| name | TEXT NOT NULL |
| created | TEXT |
| description | TEXT |
| avk_file | TEXT |

### `project_items`
| Column | Type | Notes |
|---|---|---|
| project_id | TEXT, PK part | |
| item_id | TEXT, PK part | |
| added | TEXT (ISO datetime) | |
| position | INTEGER | Row order of the imported кошторис file. NULL for pre-feature links (ordered by label as fallback). Manual adds append MAX+1. |
| qty | REAL | **Per-project** quantity — overrides `items.qty` in `get_project_items()` so two projects can share a material with different amounts. |
| estimate_unit_price | REAL | Per-project estimate price (same override rule). |

A project mirrors ONE imported file: importing into a project **replaces** its link set ("sync to file") via `batch_add_items` — existing items (matched by label) are linked too, not just newly inserted ones.

### `price_history`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| item_id | TEXT | FK → items.id ON DELETE CASCADE (added by schema v3) |
| supplier_id | TEXT | |
| price | REAL | |
| checked_at | TEXT | `YYYY-MM-DD HH:MM` |

⚠ There is **no `url` column** in `price_history`. A row is inserted on every scrape where `found and price` — even if the price is unchanged.

### `settings`
Key-value store (`key TEXT PK, value TEXT`). Used for one-time migration flags: `monitorable_version` (=2), `schema_version` (=3).

**Migrations:** `_migrate(conn)` in `item_db.py` runs on every `init_db()` (startup). Column additions are idempotent (`PRAGMA table_info` check). One-time data migrations (monitorable recompute v2; indexes + price_history FK rebuild + `dd.mm.yyyy`→ISO date normalization v3) are guarded by the `settings` flags. Safe to run repeatedly.

---

## 4. In-Memory State

### `core.state` (dict in `core/core.py`)

Created at module import by `_make_state()`, which pre-loads `results`/`label`/`last_run` from `data/last_run.json`. **Resets on server restart** (except the JSON-loaded keys). Persists across page reloads.

| Key | Type | Meaning |
|---|---|---|
| `running` | bool | True while a scrape is in progress |
| `stop_requested` | bool | Set by `POST /api/stop`; checked cooperatively in the runner |
| `log` | list[str] | Full log of the current/last run (cleared at each batch start) |
| `results` | list[dict] | Flat result list from current/last run |
| `last_run` | str | `dd.mm.YYYY HH:MM` of last completed run |
| `error` | str\|None | Error message if the run crashed |
| `label` | str | Run label, e.g. `"Черга (12 матеріалів)"` |
| `parallel_items` | int\|None | Parallelism used for current batch |
| `limit` | int\|None | Effective item count of current batch |
| `total_items` | int\|None | Total items requested (before limit) |
| `batch_started_at` | str\|None | ISO datetime; ⚠ not present in `_make_state()` — added by `_run_batch()` at runtime, so use `.get()` |

### `core.runner.item_states` (dict in `core/runner.py`)

Per-item state for the current batch. Keys are `item_id` strings. Cleared and repopulated at every batch start.

```python
item_states[item_id] = {"log": [], "results": [], "done": False, "error": None}
```

### `core.runner._session_cache`

`{(item_id, frozenset(supplier_ids)): [results]}` — ⚠ **cleared at the start of every batch** (`_run_batch` calls `_session_cache.clear()`), so it only dedupes repeated item IDs *within one run*, not across runs. Not populated in discovery mode. The key includes the active supplier set so changing suppliers never returns stale results.

### Thread-safety notes (do not "fix" silently)

- Both `state` and `item_states` are plain dicts mutated from worker threads; the GIL makes single-key writes safe. **Mutate in place; never rebind these names.**
- ⚠ Known race #1: `/api/scrape` and `/api/scrape/batch` check `state["running"]` in the route, but `running=True` is set inside the spawned thread — two fast requests can start overlapping batches.
- ⚠ Known race #2: `/api/status` iterates `item_states.values()` while `_run_batch` may `clear()`/`update()` it → possible `RuntimeError: dictionary changed size during iteration` on a poll landing mid-reset.

---

## 5. API Endpoints

All routes are Flask Blueprints registered in `app.py`. All return JSON unless noted.

### Scrape routes (`routes/scrape.py`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/scrape` | Single-item scrape. Body: `{item_id?, label?, suppliers:[{id, enabled}]}`. If `item_id` missing, looks the item up by `label` and **creates it** if not found. Internally runs a batch of one (`parallel_items=1`). |
| POST | `/api/scrape/batch` | Start batch. Body: `{item_ids:[], suppliers:[{id, enabled}], parallel_items?, limit?, project_id?, label?, single_price?, best_price?, supplier_order?:[ids], fill_missing?}`. `project_id`: per-project qty for totals + results in `item_ids` (file) order. `single_price` alone: suppliers probed SEQUENTIALLY per item in `supplier_order` priority, first price wins. `single_price+best_price`: all suppliers queried, only the cheapest kept in results (DB keeps all). `fill_missing`: items with no price get a stub row (`price:0, url:"", supplier:"—", name:"не знайдено"`) so Excel has one row per position. |
| POST | `/api/stop` | Sets `state["stop_requested"]=True` if running. Returns immediately. |
| GET | `/api/status` | Poll run status. Optional `?log_offset=N` → log lines from index N; without it, last 100 lines. |
| POST | `/api/discover` | Discovery run: all suppliers, ignores SKIP_STALE_DAYS + session cache. Body like batch (no parallel/limit); forces `parallel_items=1`. |
| GET | `/api/config` | `{max_parallel_items, default_parallel_items, skip_stale_days, monitor_all_items}` |
| GET | `/api/results` | `state["results"]` as JSON array |
| PATCH | `/api/results/<item_id>/<supplier_id>` | Persist manual price/comment override. Body: `{manual_price?, comment?}` (null/"" clears). Re-applies all overrides to `state["results"]` in memory and re-sorts; returns `{status, result}`. |

**`GET /api/status` response:**
```json
{
  "running": bool,
  "log": ["[HH:MM:SS] ..."],
  "log_total": int,
  "count": int,              // len(state.results)
  "last_run": "dd.mm.YYYY HH:MM",
  "error": null,
  "label": "...",
  "parallel_items": int, "limit": int, "total_items": int,
  "done_items": int,         // items with item_states[id].done == True
  "found_items": int,        // items with ≥1 result
  "batch_started_at": "ISO string",
  "project_id": "id or null", // set for project runs (frontend restores Проекти mode)
  "run_options": {"single_price", "best_price", "fill_missing", "supplier_order"}, // restored+locked by UI on reload
  "item_ids": ["...", ...]   // keys of item_states (frontend queue restore, preserves order)
}
```

### Items routes (`routes/items.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/items` | All items with their supplier entries. ⚠ No query params — no `project_id` filter exists. |
| POST | `/api/items` | Create item. Body: `{label}` — ⚠ **only `label` is read**; qty/unit/category etc. are NOT accepted here (they come from кошторис import). |
| GET | `/api/items/<item_id>` | Single item with supplier entries. 404 if missing. |
| PATCH | `/api/items/<item_id>` | Update item. ⚠ Allowed fields only: `monitorable`, `manual_price`, `qty`, `unit`, `estimate_unit_price`, `project_id`. `label`, `category`, `search_label` are silently ignored. |
| DELETE | `/api/items/<item_id>` | Delete (cascades to supplier_entries + price_history). |
| GET | `/api/availability` | ⚠ Returns `{coverage: {sid: {checked, found}}, items: [{id, label, category, monitorable, suppliers:{sid:{found,last_price,last_checked,...}}}]}` — NOT a `matrix` key. Items list only includes items with ≥1 supplier_entry. |
| GET | `/api/availability/coverage` | Per-supplier `{sid: {checked, found}}` only. |
| GET | `/api/items/<item_id>/price-history` | Optional `?supplier_id=`. Returns `{supplier_id: [{price, date}]}` grouped by supplier. |

### Export routes (`routes/exports.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/export/excel` | Build Excel from current `state["results"]`; saves a copy to `exports/` and streams it. 400 if no results. |
| GET | `/api/exports` | List saved exports: `[{filename, size_kb, created}]`. |
| GET | `/api/exports/<filename>` | Download a saved export. |
| DELETE | `/api/exports/<filename>` | Delete an export file. |
| GET | `/api/export/price-matrix` | All items × all suppliers matrix from DB `last_price` (+ min/max/spread columns, min-price cells highlighted). 400 if no availability data. |

`_safe_export_path(filename)` strips characters, resolves inside `EXPORTS_DIR`, and rejects escapes — use it for any filename param.

### Kostoris routes (`routes/kostoris.py`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/kostoris/parse` | Multipart upload (`file`). Validates extension (`.xls`/`.xlsx`) and size (1 KB–20 MB), writes to a **temp file**, calls `parsers.kostoris_parser.parse(path)`. Returns `{total, retail, items, filename}` and saves it to `data/last_import.json`. Does NOT touch the DB. |
| POST | `/api/kostoris/import` | Body: `{items: [ORDERED {name, code?, category?, qty?, unit?, unit_price?}], project_id? \| new_project_name?, filename?}` (legacy alt: `{names: [...]}`). `new_project_name` creates the project first (`filename` stored as `avk_file`). Bulk-inserts via `batch_add_items`: new items created, existing (by label) reused, ALL linked to the project with positions (sync-to-file). Returns `{added, linked, skipped, project_id, project_name}`. |
| GET | `/api/kostoris/last` | Returns `data/last_import.json` content or `null`. |

### Projects routes (`routes/projects.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/projects` | All projects + `item_count`, `items_with_price`. |
| POST | `/api/projects` | Body: `{name, description?, avk_file?}` |
| GET | `/api/projects/<id>` | Project + `item_count`. |
| PATCH | `/api/projects/<id>` | Update `name`/`description`/`avk_file`. |
| DELETE | `/api/projects/<id>` | Delete project + its junction rows (items survive). |
| GET | `/api/projects/<id>/items` | Items in **file order** (`project_items.position`), enriched with `best_price`, `best_supplier`, `total_best`, `total_estimate`, `saving_pct` (honours per-result `manual_price`). Per-project qty/estimate price already spliced in by `get_project_items()`. |
| POST | `/api/projects/<id>/items` | Body: `{item_id}` → junction insert. |
| DELETE | `/api/projects/<id>/items/<item_id>` | Junction delete. |
| GET | `/api/projects/<id>/summary` | `{project, item_count, items_with_price, total_estimate, total_best, saving, saving_pct}` |
| GET | `/api/projects/<id>/export` | Excel export: estimate vs best-price comparison per item, one column per supplier. |

---

## 6. Scraping Pipeline (`core/runner.py`)

### Entry points (both spawn a daemon thread running `_run_batch`)

- `start_scrape(item_id, active_supplier_ids)` — batch of one, `parallel_items=1`.
- `start_batch(item_ids, active_supplier_ids, parallel_items=None, limit=None, discovery_mode=False)`

There is **no `_run_single()`** — single scrapes are one-item batches.

### `_run_batch()` flow

```
1. _session_cache.clear()
2. item_ids = apply_limit(item_ids, limit); workers = clamp_parallel(parallel_items)
   (discovery_mode with no explicit parallel_items → workers = 1)
3. state: running=True, stop_requested=False, log=[], batch_started_at, parallel_items,
   limit=len(item_ids), total_items=<requested count>, label="Черга (N матеріалів)"
4. item_states.clear() + repopulate for the effective ids
5. active_suppliers = SUPPLIERS filtered by active_supplier_ids + enabled
6. Outer ThreadPoolExecutor(max_workers=workers):
     submit _run_single_item(iid, active_suppliers, discovery_mode) per item
     (submission loop breaks early if stop_requested)
7. After pool drains: collect item_states results in item_ids order,
   state["results"] = sort_results(apply_overrides(run_results))
   state["last_run"] = now; save_last_run(...)
8. finally: state["running"] = False
```

### `_run_single_item()` flow

```
1. Return immediately if stop_requested; load item via get_item()
2. label = item.search_label or item.label  (display_label stays item.label —
   results carry the ORIGINAL кошторис label in item_label)
3. Session-cache hit (non-discovery) → copy results, done=True, return
4. Routing: get_suppliers_for_item(item, active_ids) → routed subset
5. Smart skip (non-discovery): drop suppliers whose entry has found=0 and
   last_checked younger than SKIP_STALE_DAYS (parsed as "%Y-%m-%d %H:%M")
6. Skip whole item if monitorable=False or routed list empty (cache [] and done)
7. Re-check stop_requested; inner ThreadPoolExecutor
   (max_workers = min(len(routed), MAX_INNER_WORKERS[_DISCOVERY]))
   → _scrape_one_supplier(supplier, label, item, ilog) per supplier
8. Per result: enrich (item_id, supplier_id, item_label=display_label, qty,
   unit_estimate, total_price=qty*price) and update_supplier_entry(...);
   not-found → update_supplier_entry(found=False)
9. Cache results (non-discovery), done=True
```

`sort_results()` orders by `(item_label, supplier)` using a UA-folding sort key (ґ→г, і/ї→и, є→е). `apply_overrides()` splices `manual_price`/`comment` from `supplier_entries` into result rows (`price` replaced, original kept in `original_price`, `total_price` recomputed).

### Scraper contract

Every scraper module exports:

```python
def scrape(
    supplier: dict,       # {"id", "name", "url", "enabled", "scrape"}
    label: str,           # search query (already search_label if set)
    log: Callable,        # log(msg: str) — per-item logger
    saved_url: str|None = None,  # previously found product URL (fast path)
) -> tuple[dict|None, str|None]:   # (result, product_url)
```

**Result dict shape** (see `_build()` / `_build_result()`):
```python
{
    "name": str, "price": float, "currency": "UAH",
    "unit": None, "brand": None,          # currently always None from scrapers
    "sku": str|None, "specs": None,
    "supplier": str,                       # supplier display name
    "url": str|None,
    "date_scraped": "YYYY-MM-DD",
}
```

Return `(None, None)` when not found. The runner enriches rows afterwards (see step 8 above); scrapers must not set `item_id`/`item_label`/`qty` themselves.

**Saved-URL fast path convention:** if `saved_url` is given, fetch it first; validate that the page still matches the label (`score_title(name, label) >= DEFAULT_THRESHOLD`) and has a price; otherwise fall through to search.

---

## 7. Scrapling Base (`scrapers/_scrapling_base.py`)

### Fetch modes (exact constant names)

| Constant | Value | Fetcher | Use |
|---|---|---|---|
| `FETCH_MODE_FAST` | `"fast"` | `scrapling.fetchers.Fetcher` (plain HTTP) | Server-rendered pages. 10–50× faster. |
| `FETCH_MODE_DYNAMIC` | `"dynamic"` | `DynamicFetcher` (Chromium) | JS-rendered/SPA pages. **Default of `fetch_html`.** |
| `FETCH_MODE_STEALTH` | `"stealth"` | `StealthyFetcher` (camoufox) | Anti-bot / Cloudflare sites (ars). |

⚠ The constant is `FETCH_MODE_STEALTH` — there is no `FETCH_MODE_STEALTHY`.

### `fetch_html(url, timeout=30, headless=True, wait_ms=5000, mode=FETCH_MODE_DYNAMIC)`

- Thread-safe TTL cache: key `f"{mode}::{url}"`, TTL 300 s, hard cap 500 entries (OrderedDict, oldest evicted).
- Per-URL `threading.Lock` (double-checked) prevents duplicate concurrent fetches of the same URL; lock dict capped at 2000 (cleared wholesale when full).
- ⚠ There is **no per-domain rate limiting** — only identical-URL dedupe. Up to `parallel_items` threads can hit one site's search endpoint simultaneously.

### Other helpers

| Function | Purpose |
|---|---|
| `parse_price(raw)` | `"1 299,99 грн"` → `1299.99`. Rightmost `.`/`,` = decimal separator; other = thousands. |
| `normalize_search_query(label)` | Collapse whitespace, drop one trailing `(...)` note. |
| `score_title(title, label)` | ⚠ Arg order: **(candidate title, query label)**. Delegates to `calculate_match_score(label, title)`. Returns 0..120. |
| `pick_best_card(cards, label, title_selector=, log_fn=)` | Best card above threshold or None. |
| `pick_top_cards(cards, label, ..., top_n=5)` | Ranked list; callers fall through when top card lacks price/URL (OLX "Договірна"). |
| `SiteConfig` | Dataclass: name, domain, search_url_template (`{q}`), card_selectors[], title_selector, price_selectors[], url_selector?, sku_selectors[], sku_text_patterns[], fetch_timeout=45, check_cloudflare=False, wait_ms=5000, fetcher_mode=FETCH_MODE_DYNAMIC. |
| `search_and_extract(cfg, label, log, saved_url)` | Generic flow: saved-URL fast path (with title validation) → query variations loop → card pick (top-5 fall-through) → optional detail-page SKU fetch. |
| `text_based_extract(cfg, label, log, saved_url)` | Same skeleton, but falls back to full-page-text parsing: candidate product-name lines (5–120 chars, noise prefixes skipped) + price within 2 lines before / 4 after (`_PRICE_LINE_RE`, rejects malformed thousand groups, filters "доставк", prices ≤10), then `find_best_match`; product URL recovered from page links. Used by OpenCart-ish sites where CSS selectors are brittle. |
| `_cloudflare_blocked(page)` | Status 403/503/520–522 or title contains cloudflare markers. |

### Query pipeline (order matters)

For each supplier attempt: `item.search_label or item.label` → `normalize_search_query()` → `scrapers.query_variations.generate_variations(query, max_variations=6)`:

1. Original
2. UA→RU letter substitution (і→и, ї→и, є→е, ґ→г, apostrophes dropped) — for OLX/Prom listings typed in Russian
3. Ceresit codes: `СТ-225`/`ct 225` → `"Ceresit CT 225"`, `"CT-225"`
4. Hyphen split: `"Грунт-фарба"` → `"Грунт фарба"`
5. Paint codes: `ГФ|ПФ|ХС|МА|МО|КО|ВД|АК|НЦ` + digits → `"ГФ-021"`, `"ГФ 021"`
6. `query_simplifier.simplify_label()` shortenings (spec-style noise stripping)
7. Compound roots (`"фарба грунтувальна"` → `"грунт-фарба"`), word reorder, synonym substitution, longest word alone

Scrapers iterate the variation list and stop at the first hit.

---

## 8. Matching System (`matching/matcher.py`)

```python
normalize_text(text) -> str
# lowercase; ё→е, ґ→г, ї/і→и, є→е, ы→и, э→е; drop ъ/ь/apostrophes;
# strip punctuation; collapse spaces

calculate_match_score(query, candidate) -> float   # 0..120
# base = max(direct, transliterated) weighted rapidfuzz combo:
#   0.35*partial_ratio + 0.30*token_sort_ratio + 0.35*token_set_ratio
# tried in both alphabets (Cyr↔Lat transliteration tables)
# + 15 bonus if normalized query is a substring of candidate (also transliterated)
# + up to 10 bonus for per-token containment (exact / 4-char prefix / synonym)

find_top_matches(query, candidates, threshold=DEFAULT_THRESHOLD, top_n=5, log_fn=None)
find_best_match(query, candidates, ...)  # first of find_top_matches or None
```

**`DEFAULT_THRESHOLD = 50`** ⚠ (not 65). Matches must ALSO pass `_verify_key_tokens()`:

- ≥40 % of significant query tokens (4+ chars) must appear in the candidate (substring, 4-char prefix, transliterated, or synonym).
- Numeric guard: if the query contains 2+ digit numbers (`CT-17`, `М100`), at least one must appear in the candidate — prevents CT-85 matching a CT-17 query.

`_SYNONYM_GROUPS` maps retail-construction synonyms across UA/RU (утеплювач↔утеплитель↔минвата, фарба↔краска, шпаклівка variants, etc.) — stored in normalized form (и/е). Extend the groups there when a legitimate match is being rejected.

### `matching/monitorable.py`

`is_monitorable(label: str) -> bool` — **takes exactly 1 argument.** Permissive: True unless the label matches a `SKIP_KW` keyword (energy carriers, industrial chemicals, sensors/alarm electronics, rags, hoisting, misc non-retail). Keywords starting with `^` are prefix-anchored (e.g. `"^вода"`). Keep `SKIP_KW` short.

⚠ **TEMPORARY override active:** `MONITOR_ALL_ITEMS=1` (default ON in code) makes `is_monitorable()` return True unconditionally, and `_migrate()` syncs all DB rows to `monitorable=1` when the mode changes (see §13). Also affects routing: explicit-skip categories fall back to `DEFAULT_SUPPLIERS` instead of marketplaces-only (see below), the flag is exposed as `monitor_all_items` in `/api/config`, and the frontend queue badge/estimate honor it (`monitorAll` in `renderMonitorTab()`).

### `matching/category_routing.py`

`get_suppliers_for_item(item, all_supplier_ids) -> list[str]` — routing order:

1. **Label override:** if the item label contains any `RETAIL_OVERRIDE_KW` keyword (шпаклівка, штукатурка, ceresit, knauf, …) → route to `GENERAL_SUPPLIERS` regardless of category.
2. Otherwise `CATEGORY_ROUTING.get(category, DEFAULT_SUPPLIERS)` (DEFAULT = GENERAL_SUPPLIERS).
3. Explicitly **empty** categories (Автоматизація (КВП), Енергоносії, Спеціальні роботи, Вантажопідйомне устаткування, Інше устаткування) → specialists skipped entirely. ⚠ TEMPORARY: with `MONITOR_ALL_ITEMS=1` these fall back to `DEFAULT_SUPPLIERS` so every item gets searched.
4. Marketplace tail: `prom`/`olx` (if enabled) are **always appended after** the specialist list — including for empty categories, where they are the only suppliers tried.
5. Everything is intersected with the enabled supplier set, preserving order.

Groups: `GENERAL_SUPPLIERS` (9 retail), `MARKETPLACE_SUPPLIERS` (prom, olx), `HVAC_SUPPLIERS` (teplodim), `ELECTRICAL_SUPPLIERS` (epicentr, kub, m2), `PLUMBING_SUPPLIERS` (6), `INSULATION_SUPPLIERS` (8). ⚠ `HARDWARE_SUPPLIERS` is defined but not referenced by `CATEGORY_ROUTING` — currently dead config.

---

## 9. АВК-5 Parser (`parsers/kostoris_parser.py`)

Reads `.xls` via `xlrd` (manual cell copy → DataFrame) or `.xlsx` via `pandas.read_excel(sheet_name=0, header=None)`. The upload route hands it a **temp file path** (no in-memory byte munging).

**Column layout (0-indexed):** col 1 = resource code, col 2 = name, col 3 = unit, col 4 = qty, col 6 = unit price.

- `CODE_RE = re.compile(r'^[&+]?[СCКк\d][\dА-Яа-яA-Za-z]')` — row must look like a resource code; `варіант N` suffixes stripped.
- Rows deduped by lowercased name (duplicates only logged to console).
- Categories derived from the numeric code prefix: К→Конструкції збірні; С111→Підлоги/покрівлі; С112→Пиломатеріали; С113→Трубопроводи; С114→Теплоізоляція; С121/С124→метал; С123→Вікна та двері; С130 (sub-code 62 → Вентиляція, else Теплопостачання); С151–152→Кабельні системи; equipment ranges 1100–1999 (опалення, вентиляція, сантехніка, електрика, КВП, крани…); С100-XXXX by sub-code; fallback `Матеріали будівельні`.
- Each row → `{code, name, unit, qty, unit_price, retail, category}` where `retail = is_monitorable(name)` ⚠ (field is named `retail` in parse output but becomes `monitorable` after import).

---

## 10. Suppliers Registry (`core/suppliers.py`)

```python
SUPPLIER_REGISTRY: list[tuple[id, name, url, module, enabled]]  # 13 entries
SUPPLIERS = build_suppliers()   # module-level, built at import
```

`build_suppliers()` imports each scraper module; a failed import prints a warning and **skips that supplier** (no crash). `enabled=True` means "available to toggle in the UI", not "on by default". Marketplaces (prom, olx) were added 2026-05-18.

**To add a supplier:** create `scrapers/<id>.py` with the `scrape()` contract (usually just a `SiteConfig` + `search_and_extract`/`text_based_extract` wrapper — see `vista.py` for the minimal pattern), add one registry tuple, optionally add routing in `category_routing.py`.

---

## 11. Frontend (`static/js/app.js`)

~2000 lines, vanilla JS, plain top-level script (no IIFE, no modules, no build step). Cache-busted via `?v={mtime}` (newer of app.js/app.css mtimes, computed by `_asset_version()` in app.py).

### Key globals

| Variable | Purpose |
|---|---|
| `allItems` / `allItemsData` | Item lists for dropdown / items panel |
| `importItems` / `selectedNames` | Last кошторис parse rows + selected-for-import set |
| `monitorQueue` / `monitorDone` / `monitorMode` | Batch queue, done counter, `'single'`\|`'batch'` |
| `batchRunning` / `batchStopped` | Batch poll-loop state / stop-clicked latch |
| `serverConfig` | `{max_parallel_items, default_parallel_items}` fetched from `/api/config` at boot |
| `availabilityData` | Cached `/api/availability` response `{coverage, items}` |
| `MAX_LOG_LINES = 800` | Batch log trim threshold |

⚠ There is **no `currentPanel` global** — active panel is tracked via DOM classes by `showPanel(name, btn)`.

### Key functions (verified line refs as of 2026-07-04)

| Function | Description |
|---|---|
| `showPanel(name, btn)` | Switch panel + nav highlight |
| `setMonitorMode(mode)` | `'single'`/`'batch'`/`'project'` sub-tabs. Single mode hosts the execution journal (`#t-body` terminal + `#log-sub` — there is NO separate Журнал nav tab; it was merged into Monitoring). Batch/project call `renderMonitorTab()`; project mode shows `#monitor-project-bar`. Monitoring is the default active panel on load. |
| `onMonitorProjectChange()` | Loads `/api/projects/<id>/items` (file order) into `monitorQueue`; `monitorProjectId` global tags the run. `runBatch()` then sends `project_id` + `label: "Проект: <name>"`. |
| `onSearchOptsChange()` / `renderSupplierOrderBox()` / `moveSupplierOrder()` | Batch toolbar checkboxes: `#opt-single-price` gates `#opt-best-price` (disabled+unchecked otherwise); single-without-best shows `#supplier-order-box` — active suppliers reorderable with ◀▶, order persisted in `localStorage['supplierOrder']`, sent as `supplier_order`. `#opt-fill-missing` → `fill_missing`. Checkbox states persist in `localStorage['searchOpts']`. |
| `updateRunLockUI()` / `runningMode` / `singleRunning` / `modeQueues` | ONE monitoring at a time across all three modes (single/batch/project): while a run is active, all Run buttons, option checkboxes, project selector and supplier order are disabled; guards in `runBatch()`/`startScrape()`. Черга and Проекти have SEPARATE queues (`modeQueues`, swapped in `setMonitorMode`); the run's log/progress/stop are shown only in `runningMode`'s view. On reload the run's options come back from `/api/status.run_options` and stay locked until the run ends. |
| `onImportProjectChange()` | Import tab: "+ Новий проект…" option in `#import-project-select` reveals `#import-new-project-name` (prefilled from `importFilename`); `doImport()` sends `new_project_name`. |
| `renderMonitorTab()` | Rebuild queue list, estimated time |
| `runBatch()` | POST `/api/scrape/batch` → poll loop (1500 ms, `?log_offset=`) |
| `stopBatch()` | POST `/api/stop`, sets `batchStopped=true`, disables button |
| `updateBatchProgress(done, total, startedAt)` | Progress bar + `X/N` counter |
| `appendBatchLog(lines)` / `batchLog(msg)` | Incremental log append + trim |
| `poll()` | Single-scrape poller, **1200 ms** interval |
| `updateRunBadges(d)` | Mirrors `label`/`last_run` from an `/api/status` payload into the header badges + sidebar. Called every tick by BOTH batch poll loops (and inlined in `poll()`) — without it the Results-tab chips show the previous run until refresh. |
| `loadResults()` | GET `/api/results` → render table |
| `_startElapsedTick(startedAt)` / `_stopElapsedTick()` | 1 s elapsed timer |

### Page-reload reconnect (startup block, ~line 200)

On load, GET `/api/status`; if `running`:
- `parallel_items && total_items > 1` → batch reconnect: `showPanel('monitor')` → `setMonitorMode('batch')` → **then** `updateBatchProgress(...)` (order matters: `setMonitorMode` → `renderMonitorTab()` would reset the progress display) → restore `monitorQueue` from `/api/items` filtered by `status.item_ids` → async `reconnectBatchPoll()` loop (1500 ms).
- Otherwise → single-item reconnect via `poll()`.

Startup also restores last results (`/api/results`) and last import preview (`/api/kostoris/last`).

### Batch poll exit condition

Both `runBatch()` and `reconnectBatchPoll()` break **only** on `s.running === false` — never on `batchStopped`. The UI waits for the server to fully drain before re-enabling Run and switching to Results.

### Stop button

Lives in `#btn-stop-batch-wrap` (hidden by default) — show/hide the **wrapper**. Tooltip `.stop-tip-box` is CSS-only, anchored to `.stop-tip-wrap:hover`, arrow points down via `::before`/`::after` border tricks.

---

## 12. Styling (`static/css/app.css`)

Theming via `[data-theme="dark"]` on `<html>`; palette in CSS custom properties (`--paper`, `--ink`, `--accent`, …).

Dark-mode filter-button fix (keep):
```css
[data-theme="dark"] .btn-sel-all { background: var(--paper2); color: var(--ink); border-color: var(--border2); }
```

---

## 13. Environment Variables (`.env`, read via python-dotenv)

| Variable | Default | Where used |
|---|---|---|
| `PORT` | `5000` | `app.py` |
| `MAX_PARALLEL_ITEMS` | `10` | `runner.py` outer pool cap. `DEFAULT_PARALLEL_ITEMS = min(cap, 5)`. ⚠ `app.py`'s startup banner re-reads it with default `"5"` — display only. |
| `MAX_INNER_WORKERS` | `8` | Suppliers per item in parallel |
| `MAX_INNER_WORKERS_DISCOVERY` | `10` | Inner workers in discovery mode (items run sequentially) |
| `SKIP_STALE_DAYS` | `30` | Days before a "not found" entry is re-checked |
| `MONITOR_ALL_ITEMS` | `1` (⚠ default ON in code) | TEMPORARY customer request 2026-07: bypasses the SKIP_KW blocklist — `is_monitorable()` always True + one-time startup sync sets every existing item `monitorable=1` (settings key `monitor_all_mode` in `_migrate()`). Default is ON so fresh installs from git behave the same without a .env. To revert: set `MONITOR_ALL_ITEMS=0` in .env (or flip the code default in matching/monitorable.py) + restart — flags are recomputed from labels. |

---

## 14. Excel Exports (`routes/exports.py`)

`_build_excel(results, label)` (pandas + openpyxl, in-memory):

- One flat sheet "Ціни"; ⚠ **no blank separator rows and no 🥇🥈🥉 emoji** — top-3 cheapest per `item_label` group get **whole-row fills** (gold `FFF4C7` / silver `E5E5E5` / bronze `F4DBC1`) + bold colored price cell. Ranks computed on *distinct* prices; ties share a rank. Prices ≤ 0 are excluded from ranking (fill_missing stub rows must never get a medal).
- Column order = `COLUMN_ORDER`: Матеріал кошторису, Назва товару, Ціна за од., Валюта, Од., К-сть (кошторис), Од. (кошторис), Загальна ціна, Бренд, Артикул, Характеристики, Постачальник, Коментар, Посилання, Дата. ⚠ There is no `#`, no estimate-price and no Diff% column in this export.
- Dark header row, auto column widths, saved to `exports/<label>_<timestamp>.xlsx` and streamed.

`/api/export/price-matrix` builds item × supplier `last_price` matrix with Мін/Макс/Знайдено/Розкид % columns; min-price cells highlighted green. `/api/projects/<id>/export` adds estimate-vs-best comparison per project.

---

## 15. Critical Conventions & Gotchas

### NEVER use the Edit tool or `replace_all` on large Cyrillic files

`app.js`, `app.css`, `index.html` contain Cyrillic + CRLF. String-match edits have corrupted them with null bytes (`\x00`) on Windows before. Edit these files via Python instead:

```bash
python3 - <<'EOF'
import pathlib
p = pathlib.Path('/path/to/file')
data = p.read_bytes().replace(b'\x00', b'')
text = data.decode('utf-8')
text = text.replace('old string', 'new string')
p.write_bytes(text.encode('utf-8'))
EOF
```
For CRLF files: normalize `\r\n`→`\n` before replacing, restore after.

### Other rules

- **`is_monitorable(label)` takes exactly 1 argument.** `is_monitorable(name, category)` → TypeError.
- **`state` / `item_states` reset on server restart**; `data/last_run.json` repopulates the Results tab. Mutate the dicts in place, never rebind.
- **WAL flag:** `_wal_enabled` global in `item_db.py` avoids re-running `PRAGMA journal_mode=WAL` per connection. Don't reset it.
- **`done_items` vs `found_items`:** use `done_items` for progress (all supplier futures finished). `found_items` counts items with ≥1 result.
- **Saved-URL fast path:** scrapers must try the stored `supplier_entries.url` first and validate the title against the label before trusting it; fall back to search on 4xx/no-price/low score.
- **Discovery mode:** ignores SKIP_STALE_DAYS + session cache, runs items sequentially (`parallel_items=1`) with `MAX_INNER_WORKERS_DISCOVERY` inner workers, does NOT populate the session cache.
- **Overrides survive re-scrapes:** `update_supplier_entry()` is a single UPSERT (`ON CONFLICT DO UPDATE`) that never touches `manual_price`/`comment` — keep it that way; a SELECT-then-REPLACE here reintroduces a lost-update window vs. concurrent PATCH overrides.
- **No per-domain politeness:** the fetch layer dedupes identical URLs only. Don't raise `MAX_PARALLEL_ITEMS` casually — 10 items × same routed site = 10 concurrent hits on that site.
- **`score_title(title, label)`** — candidate first, query second. Easy to swap accidentally.
- **`update_item()` whitelist** silently drops unknown fields — adding a new editable item field requires extending `_FLOAT_FIELDS`/`_INT_FIELDS`/`_TEXT_FIELDS` in `item_db.py`.

### Known issues & dead code (as of 2026-07-04)

**Correctness / concurrency:**

1. ⚠ Check-then-act race on `state["running"]` in scrape routes (see §4).
2. ⚠ `/api/status` may hit "dict changed size" while a batch is (re)initializing `item_states` (see §4).
3. ⚠ `m2.py` single-word search fallback passes the word as the *matching label* (`search_and_extract(CONFIG, word, log)`) — candidates are scored against one generic word, so a wrong product can be saved as `found=1`, and its URL then becomes the trusted `saved_url` on later runs (self-perpetuating). Fix: keep the word as the search query but score candidates against the full original label (venbud.py's fallback already does this correctly — copy that pattern).
4. Runner ignores the second element of a scraper's `(None, url)` return — on not-found it re-writes the previously saved DB URL; returning a fresh URL without a result has no effect.
5. `kostoris_parser` assumes ≥7 columns (`row[6]`); narrower sheets raise and surface as HTTP 500 from `/api/kostoris/parse`.

**Performance (worth doing, none urgent):**

6. No per-domain rate limiting in `fetch_html` — up to `parallel_items` threads can hit one site's search simultaneously (ban risk). A per-domain semaphore (2–3) would be the highest-value change.
7. `/api/scrape` finds an item by label via `load_items()` (full items + supplier_entries dump per request) — add a `get_item_by_label()` query.
8. `price_history` inserts a row on every run even when the price is unchanged — no dedup or pruning.
9. No `busy_timeout` PRAGMA; heavy batches (up to `parallel_items × MAX_INNER_WORKERS` writer threads) rely on WAL + sqlite3's default 5 s connect timeout.
10. KUB: DYNAMIC fetch (timeout 90 s, wait 10 s) × up to 6 query variations — one not-found item can hold an inner worker for minutes. Consider capping variations for browser-mode sites.
11. `venbud.py` AJAX search POSTs via `requests` directly, bypassing the fetch cache/lock layer — repeated variations re-POST every time.
12. `fetch_html` cache holds up to 500 parsed page objects in memory (TTL 300 s) — can be heavy on long discovery runs.

**Dead / legacy:**

13. `HARDWARE_SUPPLIERS` in category_routing.py is unused.
14. `items.project_id` column is legacy; junction table `project_items` is authoritative.

---

## 16. Tests

Run: `python -m pytest tests/ -v` — no network, pure logic.

| Test file | Covers |
|---|---|
| `test_matcher.py` | normalize_text, calculate_match_score, find_best_match |
| `test_price_parsing.py` | parse_price edge cases |
| `test_query_simplifier.py` | simplify_label variants |
| `test_query_variations.py` | generate_variations expansion |
| `test_result_overrides.py` | apply_overrides() splice logic |
| `test_result_sort.py` | sort_results() UA-folded grouping |
| `test_batch_controls.py` | clamp_parallel(), apply_limit() |
| `test_safe_export_path.py` | export path traversal prevention |
| `test_session_cache.py` | fetch cache TTL + eviction |
| `test_excel_medals.py` | top-3 medal rank assignment |

---

## 17. Startup Sequence

```
START.bat
  → checks Python ≥3.10 on PATH
  → creates .venv (first run)
  → pip install -r requirements.txt + `scrapling install`
    (fallback: python -m playwright install chromium) — once, marked by .venv\.setup_done
  → opens http://localhost:5000 via PowerShell after 5 s
  → python app.py
      → load_dotenv()
      → Flask(__name__) + register 5 blueprints
      → AT IMPORT TIME: init_db() (tables + _migrate()), ensure_exports_dir(), ensure_debug_dir()
      → app.run(debug=False, host="0.0.0.0", port=PORT, threaded=True)
```

⚠ `init_db()` runs at module import (so WSGI servers get it too). ⚠ Binds `0.0.0.0` — LAN-exposed, no auth.
