# PriceScout — Technical Overview (Agentic Coding Reference)

This document is a complete coding reference for PriceScout. It covers every file, all data flows, the full API surface, database schema, and all gotchas to know before editing the codebase. Read this before touching any file.

---

## 1. Purpose

PriceScout is a local Flask web app (Windows, single-user) that:

1. Imports construction-material line items from АВК-5 estimate files (`.xls`/`.xlsx`)
2. Searches 13 Ukrainian supplier websites for each material
3. Shows a side-by-side price comparison table and exports to Excel

All scraping is done with **Scrapling** (HTTP fetcher + optional Chromium via Scrapling's DynamicFetcher). There is **no Claude API call** in the scraping pipeline. Fuzzy matching of product names uses **rapidfuzz**.

---

## 2. Directory Structure

```
pricescout/
│
├── app.py                  # Flask factory + index route
├── START.bat               # Windows launcher (venv + deps + scrapling install)
├── requirements.txt        # pip deps
├── .env                    # (not committed) env overrides
├── pricescout.db           # SQLite database (WAL mode)
│
├── core/
│   ├── core.py             # Shared in-memory state dict, log(), save/load_last_run()
│   ├── runner.py           # Scrape orchestrator — ThreadPoolExecutor fan-out
│   ├── item_db.py          # All SQLite access (init_db, CRUD, migrations)
│   └── suppliers.py        # SUPPLIER_REGISTRY + build_suppliers() factory
│
├── routes/
│   ├── scrape.py           # /api/scrape, /api/scrape/batch, /api/stop, /api/status, /api/results, /api/discover, /api/config
│   ├── items.py            # /api/items CRUD, /api/availability, /api/price-history
│   ├── exports.py          # /api/export/excel, /api/exports, /api/export/price-matrix
│   ├── kostoris.py         # /api/kostoris/parse, /api/kostoris/import, /api/kostoris/last
│   └── projects.py         # /api/projects CRUD + /api/projects/<id>/summary + export
│
├── scrapers/
│   ├── _scrapling_base.py  # Shared fetch helpers, price parser, fuzzy pick helpers
│   ├── epicentr.py         # Епіцентр К
│   ├── ars.py              # АРС
│   ├── buddvir.py          # Будівельний Двір
│   ├── kub.py              # КУБ
│   ├── venbud.py           # Вен Буд
│   ├── budpostach.py       # Будпостач
│   ├── m2.py               # М2
│   ├── vista.py            # Віста
│   ├── megatrade.py        # Мегатрейд СМ
│   ├── budia.py            # Будія
│   ├── teplodim.py         # ТеплоДiм (HVAC specialist)
│   ├── prom.py             # Prom.ua (marketplace)
│   └── olx.py              # OLX (classifieds)
│
├── matching/
│   ├── matcher.py          # Fuzzy matcher (rapidfuzz, Cyrillic normalization)
│   ├── monitorable.py      # is_monitorable(label) — keyword blocklist
│   ├── category_routing.py # Category → supplier ID list mapping
│   └── search_label_converter.py  # Converts display labels to search queries
│
├── parsers/
│   └── kostoris_parser.py  # АВК-5 Excel parser → list of material dicts
│
├── templates/
│   └── index.html          # Single-page app shell (Jinja2, all panels inline)
│
├── static/
│   ├── css/app.css         # All styles (dark/light mode via data-theme attr)
│   └── js/app.js           # All frontend logic (~3000 lines, vanilla JS)
│
├── data/
│   ├── last_run.json       # Persisted results from most recent scrape run
│   └── last_import.json    # Persisted last кошторис import data
│
├── exports/                # Generated Excel files (served by /api/exports/<filename>)
├── debug/                  # HTML snapshots from failed fetches (dev aid)
│
├── tests/
│   ├── test_matcher.py
│   ├── test_price_parsing.py
│   ├── test_query_simplifier.py
│   ├── test_query_variations.py
│   ├── test_result_overrides.py
│   ├── test_result_sort.py
│   ├── test_batch_controls.py
│   ├── test_safe_export_path.py
│   ├── test_session_cache.py
│   └── test_excel_medals.py
│
└── scripts/                # One-off discovery / probe scripts (not used in production)
```

---

## 3. Database Schema

**File:** `pricescout.db` — SQLite, WAL mode, `PRAGMA foreign_keys=ON`.

All access goes through `core/item_db.py` which uses a `@contextmanager get_conn()` helper that auto-commits or auto-rolls-back.

### `items`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | UUID generated at insert |
| label | TEXT UNIQUE | Material name (display form) |
| created | TEXT | ISO date string |
| source | TEXT | `'manual'` or `'kostoris'` |
| avk_code | TEXT | АВК-5 resource code (e.g. `С111-2`) |
| category | TEXT | Derived from code; used for supplier routing |
| qty | REAL | Quantity from estimate |
| unit | TEXT | Unit of measure (м², кг, шт, …) |
| estimate_unit_price | REAL | Unit price from кошторис |
| monitorable | INT | 1=yes, 0=skip (set by `is_monitorable()`) |
| manual_price | REAL | User-set override price (rarely used at item level) |
| search_label | TEXT | Alternative search query override |
| project_id | TEXT | FK to `projects.id` (nullable) |

### `supplier_entries`
| Column | Type | Notes |
|---|---|---|
| item_id | TEXT | FK → items.id CASCADE DELETE |
| supplier_id | TEXT | e.g. `'epicentr'`, `'kub'` |
| url | TEXT | Last known product URL |
| found | INT | 1=product exists on this supplier, 0=not found |
| last_checked | TEXT | ISO datetime of last scrape |
| last_price | REAL | Price from last scrape |
| manual_price | REAL | User override price for this result |
| comment | TEXT | User note for this result |

### `projects`
| Column | Type |
|---|---|
| id | TEXT PK |
| name | TEXT |
| created | TEXT |

### `project_items`
| Column | Type |
|---|---|
| project_id | TEXT FK |
| item_id | TEXT FK |

### `price_history`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| item_id | TEXT | |
| supplier_id | TEXT | |
| price | REAL | |
| url | TEXT | |
| checked_at | TEXT | ISO datetime |

### `settings`
| Column | Type |
|---|---|
| key | TEXT PK |
| value | TEXT |

Used for `schema_version` tracking.

**Schema version:** managed by `_migrate(conn)` in `item_db.py`. It checks `PRAGMA table_info` and adds columns if missing. The migration is idempotent — safe to run on every startup.

---

## 4. In-Memory State

### `core.state` (dict, lives in `core/core.py`)

Created once at module import by `_make_state()`. **Resets on server restart.** Persists across page reloads.

| Key | Type | Meaning |
|---|---|---|
| `running` | bool | True while a scrape is in progress |
| `stop_requested` | bool | Set by `POST /api/stop`; checked between futures |
| `log` | list[str] | Full log of the current/last run |
| `results` | list[dict] | Flat result list from current/last run |
| `last_run` | str | ISO datetime of last completed run |
| `error` | str\|None | Error message if the run crashed |
| `label` | str | Item label (single-item runs) |
| `parallel_items` | int\|None | Parallelism used for current batch |
| `limit` | int\|None | Item count cap used for current batch |
| `total_items` | int\|None | Total items in current batch |
| `batch_started_at` | str\|None | ISO datetime when batch started |

### `core.runner.item_states` (dict, lives in `core/runner.py`)

Per-item state for batch runs. Keys are `item_id` strings.

```python
item_states[item_id] = {
    "log":     [],       # per-item log lines
    "results": [],       # per-item scrape results
    "done":    False,    # True when all suppliers for this item have been tried
    "error":   None,
}
```

Both dicts are **not thread-safe** in the strictest sense but Flask runs with `threaded=True` and Python's GIL protects simple attribute assignments. Do not replace these dicts — mutate them in place.

---

## 5. API Endpoints

All routes registered as Flask Blueprints. All return JSON.

### Scrape routes (`routes/scrape.py`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/scrape` | Start single-item scrape. Body: `{item_id, label, suppliers:[{id, enabled}]}` |
| POST | `/api/scrape/batch` | Start batch. Body: `{item_ids:[], suppliers:[], parallel_items?, limit?}` |
| POST | `/api/stop` | Set `state["stop_requested"] = True`. Returns immediately. |
| GET | `/api/status` | Poll run status. Optional `?log_offset=N` for incremental logs. Returns full state snapshot including `item_ids`. |
| POST | `/api/discover` | Full discovery run (all suppliers, ignores SKIP_STALE_DAYS cache). |
| GET | `/api/config` | Returns `{max_parallel_items, default_parallel_items, skip_stale_days}`. |
| GET | `/api/results` | Returns `state["results"]` as JSON array. |
| PATCH | `/api/results/<item_id>/<supplier_id>` | Override price or comment. Body: `{manual_price?, comment?}`. Re-applies all overrides and re-sorts in memory. |

**`GET /api/status` response shape:**
```json
{
  "running": bool,
  "log": ["[HH:MM:SS] ..."],
  "log_total": int,
  "count": int,
  "last_run": "ISO string",
  "error": null,
  "label": "...",
  "parallel_items": int,
  "limit": int,
  "total_items": int,
  "done_items": int,
  "found_items": int,
  "batch_started_at": "ISO string",
  "item_ids": ["id1", "id2", ...]
}
```

`done_items` = count of items where `item_states[id]["done"] == True`.
`found_items` = count of items with at least one result.
`item_ids` = keys of `item_states` (used by frontend to restore queue on page reload).

### Items routes (`routes/items.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/items` | All items. Optional `?project_id=` filter. |
| POST | `/api/items` | Create item. Body: `{label, category?, qty?, unit?, estimate_unit_price?, source?}` |
| GET | `/api/items/<item_id>` | Single item with supplier entries. |
| PATCH | `/api/items/<item_id>` | Update item fields (monitorable, qty, unit, etc.). |
| DELETE | `/api/items/<item_id>` | Delete item (cascades to supplier_entries, project_items, price_history). |
| GET | `/api/availability` | Full availability matrix: `{items:[...], suppliers:[...], matrix:{item_id:{supplier_id: bool}}}` |
| GET | `/api/availability/coverage` | Coverage summary per supplier (count of found items). |
| GET | `/api/items/<item_id>/price-history` | Price history rows for one item, all suppliers. |

### Export routes (`routes/exports.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/export/excel` | Generate and return Excel file from current `state["results"]`. Saves copy to `exports/`. |
| GET | `/api/exports` | List files in `exports/` dir. |
| GET | `/api/exports/<filename>` | Download a saved export file. |
| DELETE | `/api/exports/<filename>` | Delete an export file. |
| GET | `/api/export/price-matrix` | Price matrix export (all items × all suppliers, last prices from DB). |

### Kostoris routes (`routes/kostoris.py`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/kostoris/parse` | Accepts multipart file upload. Returns parsed material list. Does NOT save to DB. |
| POST | `/api/kostoris/import` | Saves selected items from a parse result into DB. Body: `{items:[...], project_id?}` |
| GET | `/api/kostoris/last` | Returns `data/last_import.json` (last parse result for UI restore). |

### Projects routes (`routes/projects.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/projects` | List all projects. |
| POST | `/api/projects` | Create project. Body: `{name}` |
| GET | `/api/projects/<id>` | Get project + items. |
| PATCH | `/api/projects/<id>` | Rename project. |
| DELETE | `/api/projects/<id>` | Delete project (does not delete items). |
| GET | `/api/projects/<id>/items` | Items in a project. |
| POST | `/api/projects/<id>/items` | Add item to project. Body: `{item_id}` |
| DELETE | `/api/projects/<id>/items/<item_id>` | Remove item from project. |
| GET | `/api/projects/<id>/summary` | Aggregated cost comparison (scraped vs estimate). |
| GET | `/api/projects/<id>/export` | Excel export for project. |

---

## 6. Scraping Pipeline

### Entry points

- **Single item:** `runner.start_scrape(item_id, active_supplier_ids)` — spawns a daemon thread that calls `_run_single()`.
- **Batch:** `runner.start_batch(item_ids, active_supplier_ids, parallel_items, limit, discovery_mode)` — spawns a daemon thread that calls `_run_batch()`.

### `_run_batch()` flow

```
start_batch() → daemon thread → _run_batch():
  1. Set state["running"] = True, reset item_states
  2. Apply limit: item_ids = item_ids[:limit] if limit else item_ids
  3. ThreadPoolExecutor(max_workers=parallel_items) outer pool
  4. For each item_id (submitted as futures):
       → _scrape_item(item_id, active_supplier_ids, ...)
  5. as_completed(futures):
       - check state["stop_requested"] between futures
       - mark item_states[id]["done"] = True
       - append results to state["results"]
  6. state["running"] = False
  7. save_last_run(results, ...)
```

### `_scrape_item()` flow

```
_scrape_item(item_id, active_supplier_ids):
  1. Load item from DB (get_item)
  2. Determine which suppliers to try:
       → get_suppliers_for_item(item, active_supplier_ids)
       → filters by category routing
       → skips suppliers with found=False checked < SKIP_STALE_DAYS days ago
  3. ThreadPoolExecutor(max_workers=MAX_INNER_WORKERS) inner pool
  4. For each supplier: call supplier["scrape"](supplier, label, log, saved_url)
  5. Collect results, run apply_overrides(), update supplier_entries in DB
```

### Scraper contract

Every file in `scrapers/` must export one function:

```python
def scrape(
    supplier: dict,       # {"id": "epicentr", "name": "Епіцентр К", "url": "..."}
    label: str,           # Material name to search for
    log: Callable,        # log(msg: str) — writes to item log
    saved_url: str|None,  # Previously found product URL (fast path)
) -> tuple[dict|None, str|None]:
    # Returns: (result_dict_or_None, product_url_or_None)
```

**Result dict shape:**
```python
{
    "name":         str,   # Product title from site
    "price":        float,
    "currency":     "UAH",
    "unit":         str|None,
    "brand":        str|None,
    "sku":          str|None,
    "specs":        str|None,
    "supplier":     str,   # supplier["name"]
    "url":          str|None,
    "date_scraped": "YYYY-MM-DD",
}
```

Return `(None, None)` when the item is not found on that supplier.
Return `(None, saved_url)` to keep the existing URL but indicate no price today.

### `_scrapling_base.py` — shared helpers

| Function | Purpose |
|---|---|
| `fetch_html(url, timeout, mode)` | Thread-safe cached fetch. TTL=300s, max 500 entries. |
| `normalize_search_query(label)` | Strips units, codes, special chars for search URL. |
| `parse_price(text)` | Extracts float from "1 234,50 грн" style strings. |
| `pick_best_card(cards, label, ...)` | Runs fuzzy matching over a list of product cards, returns best hit above threshold. |
| `score_title(query, title)` | Calls `calculate_match_score` from matcher. |
| `FETCH_MODE_FAST` / `FETCH_MODE_STEALTHY` / `FETCH_MODE_DYNAMIC` | Constants for fetch strategy. |

**Fetch modes:**
- `FAST` — Scrapling's HTTP-only `Fetcher` (no browser). Works on server-rendered pages. Very fast.
- `STEALTHY` — Scrapling's `StealthyFetcher` (Chromium-based, stealth mode). For sites with bot detection.
- `DYNAMIC` — Scrapling's `DynamicFetcher` (full Chromium). For JS-heavy SPAs.

The URL-level cache prevents two threads from fetching the same URL concurrently (double-checked locking via per-URL `threading.Lock()`).

---

## 7. Matching System (`matching/`)

### `matcher.py`

Core fuzzy matching used by scrapers to decide if a search result matches the queried material.

**Key functions:**

```python
normalize_text(text: str) -> str
# Lowercases, strips punctuation, applies Cyrillic→Latin transliteration,
# normalizes Ru↔Ua variants (і↔и, є↔е, ї→и, ё→е, ы→и, э→е)

calculate_match_score(query: str, candidate: str) -> float
# Returns 0-100 score using rapidfuzz combination:
# max(partial_ratio, token_sort_ratio, token_set_ratio)
# with key-token verification (critical tokens from query must appear in candidate)

find_best_match(query, candidates, threshold=DEFAULT_THRESHOLD) -> MatchResult | None
find_top_matches(query, candidates, n=5, threshold=...) -> list[MatchResult]
```

`DEFAULT_THRESHOLD = 65` — below this score a match is rejected.

### `monitorable.py`

```python
is_monitorable(label: str) -> bool
```

Returns `False` if `label` contains any keyword from `SKIP_KW` list (Ukrainian energy carriers, industrial chemicals, sensors, alarm electronics, cranes, etc.). Returns `True` for everything else — permissive by design. Called during кошторис import and DB migration.

**Rule:** keep `SKIP_KW` short. Only add items that genuinely don't exist on Ukrainian retail construction sites.

### `category_routing.py`

```python
get_suppliers_for_item(item: dict, active_supplier_ids: list) -> list[str]
```

Maps `item["category"]` to a supplier subset. Returns the intersection of the routed list and `active_supplier_ids`. Falls back to all active suppliers if category is unknown.

**Category groups defined:**
- `GENERAL_SUPPLIERS` — all retail suppliers (9)
- `MARKETPLACE_SUPPLIERS` — prom, olx
- `HVAC_SUPPLIERS` — teplodim
- `ELECTRICAL_SUPPLIERS` — epicentr, kub, m2
- `PLUMBING_SUPPLIERS` — epicentr, kub, venbud, m2, vista, buddvir
- `INSULATION_SUPPLIERS` — epicentr, ars, buddvir, kub, venbud, m2, vista, budia
- `HARDWARE_SUPPLIERS` — epicentr, kub, buddvir, budpostach, m2, vista

To add routing for a new category: add a key to `CATEGORY_ROUTING` dict.

### `search_label_converter.py`

Converts display labels to cleaner search queries. Used when `item["search_label"]` is not set.

---

## 8. АВК-5 Parser (`parsers/kostoris_parser.py`)

Reads `.xls` (via `xlrd`) or `.xlsx` (via `openpyxl`) using `pandas`.

**Expected column layout (0-indexed):**
- Col 1: resource code (e.g. `С111-2`, `К1-3`)
- Col 2: material name
- Col 3: unit
- Col 4: quantity
- Col 6: unit price

**`CODE_RE`** filters rows: `r'^[&+]?[СCКк\d][\dА-Яа-яA-Za-z]'` — must look like a resource code.

Categories are derived from numeric prefixes of resource codes (С111→Підлоги, С113→Трубопроводи, С114→Теплоізоляція, С151-152→Електрика, etc.).

`is_monitorable(name)` is called per row — non-monitorable items get `monitorable=0` and are filtered out of the import preview by default. **Pass only `name` — the function takes 1 argument.**

**Critical:** the parser is called via `/api/kostoris/parse` which receives a multipart file upload. The file bytes are read as-is. For `.xls` files with null bytes, strip them before parsing:

```python
raw = file.read().replace(b'\x00', b'')
```

---

## 9. Suppliers Registry (`core/suppliers.py`)

```python
SUPPLIER_REGISTRY: list[tuple[str, str, str, str, bool]] = [
    ("epicentr", "Епіцентр К", "https://epicentrk.ua", "scrapers.epicentr", True),
    ...
]
```

**To add a new supplier:**
1. Create `scrapers/<id>.py` with `def scrape(supplier, label, log, saved_url=None)`.
2. Add one tuple to `SUPPLIER_REGISTRY`.
3. Optionally add routing rules in `category_routing.py`.

`build_suppliers()` dynamically imports each scraper module at startup. Failed imports print a warning and skip the supplier rather than crashing.

---

## 10. Frontend (`static/js/app.js`)

~3000 lines, vanilla JS, no build step. Served with cache-busting via `?v={mtime}` query string (computed in `app.py`).

### Key globals

| Variable | Purpose |
|---|---|
| `monitorQueue` | Array of item objects selected for batch monitoring |
| `batchRunning` | True while a batch poll loop is active |
| `batchStopped` | True after user clicked stop (disables re-start until drain completes) |
| `currentPanel` | ID of currently visible panel |

### Key functions

| Function | Description |
|---|---|
| `showPanel(id, btn)` | Switch active panel, update nav button highlight |
| `setMonitorMode(mode)` | `'single'` or `'batch'` — toggles sub-tabs in Monitoring panel, calls `renderMonitorTab()` |
| `renderMonitorTab()` | Rebuilds the queue item list, computes estimated time/cost |
| `runBatch()` | POSTs to `/api/scrape/batch`, then enters poll loop |
| `appendBatchLog(lines)` | Appends lines to `#batch-log-body`, trims to MAX_LOG_LINES=800, auto-scrolls |
| `batchLog(msg)` | Single-line wrapper around `appendBatchLog` |
| `stopBatch()` | POSTs `/api/stop`, disables stop button, sets `batchStopped=true` |
| `updateBatchProgress(done, total, startedAt)` | Updates progress bar and `X/N матеріалів` counter |
| `poll()` | Single-item scrape poller (1.5s interval) |
| `loadResults()` | Fetches `/api/results` and re-renders results table |
| `_startElapsedTick(startedAt)` | Starts a 1s timer showing elapsed time in the progress bar |
| `_stopElapsedTick()` | Clears the elapsed timer |

### Page-reload reconnect (startup block)

On every page load, the app fetches `/api/status`. If `d.running === true`:
- `d.parallel_items && d.total_items > 1` → batch reconnect: calls `setMonitorMode('batch')`, restores queue from `/api/items` filtered by `d.item_ids`, starts `reconnectBatchPoll()` async loop.
- Otherwise → single-item reconnect: calls `poll()`.

**Order matters:** `updateBatchProgress()` must be called **after** `setMonitorMode('batch')` because `setMonitorMode` calls `renderMonitorTab()` which would reset the progress display.

### Batch poll loop exit condition

Both `runBatch()` and `reconnectBatchPoll()` break only on `s.running === false` from the server. They do **not** break on `batchStopped`. This ensures the UI waits for the server to fully drain before showing results and re-enabling the Run button.

### Stop button wrapper

The stop button lives inside `#btn-stop-batch-wrap` (a `<div>` with `display:none` by default). Show/hide the wrapper, not the button itself. The tooltip (`.stop-tip-box`) is a CSS-only hover tooltip anchored to `.stop-tip-wrap`.

---

## 11. Styling (`static/css/app.css`)

Theming via `[data-theme="dark"]` attribute on `<html>`. CSS custom properties (`--paper`, `--ink`, `--accent`, etc.) define the palette.

**Dark mode filter buttons fix:**
```css
[data-theme="dark"] .btn-sel-all {
  background: var(--paper2);
  color: var(--ink);
}
```

**Tooltip (above stop button):**
```css
.stop-tip-box {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  width: 220px;
  pointer-events: none;
  z-index: 200;
}
.stop-tip-wrap:hover .stop-tip-box { display: block; }
```
Arrow points **down** toward the button (uses `border-top-color` on `::before`/`::after`).

---

## 12. Environment Variables

All read at startup via `python-dotenv` from `.env` in the project root.

| Variable | Default | Where used |
|---|---|---|
| `PORT` | `5000` | `app.py` — Flask listen port |
| `MAX_PARALLEL_ITEMS` | `10` | `runner.py` — outer ThreadPool cap |
| `MAX_INNER_WORKERS` | `8` | `runner.py` — suppliers per item in parallel |
| `MAX_INNER_WORKERS_DISCOVERY` | `10` | `runner.py` — inner workers in discovery mode |
| `SKIP_STALE_DAYS` | `30` | `runner.py` — days before "not found" cache expires |

---

## 13. Excel Export (`routes/exports.py`)

`_build_excel(results, label)` builds an `.xlsx` in memory using `openpyxl`.

- Results are grouped by `item_label` with blank separator rows between materials.
- Top-3 cheapest prices per material get 🥇🥈🥉 in the leftmost cell.
- Columns: #, Material, Supplier, Price (UAH), Unit, Qty, Total, Estimate price, Diff%, URL, Comment.
- All files are saved to `exports/` with a timestamp filename and also returned directly to the browser.
- `_safe_export_path(filename)` prevents path traversal attacks (rejects `..` and absolute paths).

---

## 14. Critical Conventions & Gotchas

### NEVER use Edit tool or `replace_all` on large Cyrillic files

Files like `app.js`, `app.css`, `index.html` contain Cyrillic characters. The Edit tool's string matching can introduce **null bytes (`\x00`)** that silently corrupt the file on Windows when content is large. Always use Python bash string manipulation for edits on these files:

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

For files with CRLF line endings (Windows), normalize before replace and restore after:
```python
text = text.replace('\r\n', '\n')
# ... make replacements ...
text = text.replace('\n', '\r\n')
```

### `state` and `item_states` reset on server restart

These are in-memory Python dicts. Any page reload while the server is running preserves them. A server restart (closing START.bat, app crash) clears them. `last_run.json` on disk persists results across restarts for the Results tab.

### `is_monitorable()` takes exactly 1 argument

```python
# CORRECT:
is_monitorable(name)

# WRONG (will raise TypeError):
is_monitorable(name, category)
```

### WAL mode is set once per process

`_wal_enabled` global in `item_db.py` prevents redundant `PRAGMA journal_mode=WAL` on every connection. Do not reset it.

### `found_items` vs `done_items`

- `found_items`: items with at least one result (can jump to 100% at batch start if session cache has data from a previous run).
- `done_items`: items where all supplier futures have completed. Use `done_items` for progress display.

### Scraper `saved_url` fast path

If a supplier entry already has a `url` (from a previous successful scrape), the scraper should try that URL first. Only fall back to a search query if the saved URL returns 4xx or an empty page. This dramatically reduces scrape time on repeat runs.

### Discovery mode

`start_batch(..., discovery_mode=True)` ignores `SKIP_STALE_DAYS` and runs all suppliers for all items regardless of cache. Sets `parallel_items=1` (sequential) and uses `MAX_INNER_WORKERS_DISCOVERY` (higher) for the inner supplier pool.

---

## 15. Adding a New Scraper

1. Create `scrapers/<supplier_id>.py`.
2. Implement `scrape(supplier, label, log, saved_url=None) -> tuple[dict|None, str|None]`.
3. Import helpers from `scrapers/_scrapling_base.py` — use `fetch_html()`, `parse_price()`, `pick_best_card()`.
4. Choose fetch mode: prefer `FETCH_MODE_FAST` unless the site needs JS rendering.
5. Add entry to `SUPPLIER_REGISTRY` in `core/suppliers.py`.
6. Add routing rules to `category_routing.py` if the supplier only covers certain categories.
7. Test manually with `python -c "from scrapers.mysup import scrape; print(scrape({'id':'x','name':'X','url':'...'}, 'Цегла М100', print, None))"`.

---

## 16. Tests

Run with: `python -m pytest tests/ -v`

| Test file | Covers |
|---|---|
| `test_matcher.py` | normalize_text, calculate_match_score, find_best_match |
| `test_price_parsing.py` | parse_price edge cases |
| `test_query_simplifier.py` | normalize_search_query variations |
| `test_query_variations.py` | search query expansion |
| `test_result_overrides.py` | apply_overrides() price replacement logic |
| `test_result_sort.py` | sort_results() grouping |
| `test_batch_controls.py` | clamp_parallel(), apply_limit() — 17 cases |
| `test_safe_export_path.py` | path traversal prevention |
| `test_session_cache.py` | fetch cache TTL and eviction |
| `test_excel_medals.py` | 🥇🥈🥉 medal assignment logic |

No external services are called in tests — all mocked.

---

## 17. Startup Sequence

```
START.bat
  → activate .venv
  → pip install -r requirements.txt (first run only)
  → scrapling install (first run only)
  → python app.py
      → load_dotenv()
      → Flask(__name__)
      → register 5 blueprints
      → init_db() → creates tables, runs _migrate()
      → ensure_exports_dir(), ensure_debug_dir()
      → app.run(threaded=True, port=5000)
```

Browser opens via PowerShell `Start-Process` after 5-second delay (from START.bat).
