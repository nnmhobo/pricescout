# PriceScout — Technical Overview (Agentic Coding Reference)

This document is the coding reference for PriceScout. It covers every module, all data flows, the full API surface, the database schema, and the gotchas to know before editing the codebase. Read this before touching any file.

> **Verified against code on 2026-10-08** (commit `1e431df`, branch `dev`). If you change behavior described here, update this file in the same session. Known drift traps are marked ⚠ throughout. User-facing docs: `README.md` (English, the single README) and `ЯК ЗАПУСТИТИ.txt` (Ukrainian quick start for the customer).

---

## 1. Purpose

PriceScout is a local Flask web app (Windows, single-user) that:

1. Imports construction-material line items from АВК-5 estimate files (`.xls`/`.xlsx`) in two layouts chosen explicitly by the user — **КД_ПВР** («Підсумкова відомість ресурсів») and **КД_РЛМТ** («Відомість матеріальних ресурсів…», split into Розділ 1 / Розділ 2)
2. Searches 13 registered Ukrainian supplier websites for each material (routed by category — see §8)
3. Shows a side-by-side price comparison table and exports to Excel; projects mirror one imported file (row order, per-project qty, КД_РЛМТ sections) and export an estimate-vs-best-price comparison

All scraping is done with **Scrapling** (plain HTTP fetcher, or a Chromium/Patchright browser via Scrapling's Dynamic/Stealthy fetchers). There are no LLM/API calls anywhere in the app (an `ANTHROPIC_API_KEY` line left in an old local `.env` is unused). Fuzzy matching of product names uses **rapidfuzz**.

---

## 2. Directory Structure

```
pricescout/
│
├── app.py                  # Flask app + index route (no factory function; module-level `app`)
├── README.md               # The single README (English): overview, features, setup, user guide
├── ЯК ЗАПУСТИТИ.txt        # Ukrainian quick start for the customer (UTF-8 with BOM, CRLF)
├── OVERVIEW.md             # This file
├── START.bat               # Silent launcher → `pythonw setup_gui.py` (console only if Python missing)
├── setup_gui.py            # tkinter installer/launcher window — STDLIB ONLY (runs on system Python before the venv exists)
├── requirements.txt        # flask, scrapling[fetchers], lxml, xlrd, pandas, openpyxl, python-dotenv, rapidfuzz, requests
├── .env                    # (not committed) env overrides
├── pricescout.db           # (not committed) SQLite database (WAL mode)
├── .github/workflows/
│   └── notify-release-mail.yml  # push to main → GitHub Release + email to customer (§18)
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
│   ├── exports.py          # /api/export/excel, /api/exports (+ typed download/delete), /api/export/price-matrix, /api/exports/add-urls
│   ├── kostoris.py         # /api/kostoris/parse, /api/kostoris/import, /api/kostoris/last (doc_type: pvr | rlmt)
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
│   ├── venbud.py           # Вен Буд        — custom: search via AJAX live-search POST (`requests`), saved URL via fetch_html (DYNAMIC default)
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
│   ├── kostoris_parser.py  # КД_ПВР parser → list of material dicts (§9)
│   ├── rlmt_parser.py      # КД_РЛМТ parser → same contract + `section` (1|2) per item/occurrence (§9)
│   └── category_codes.py   # derive_category(code) — shared by both parsers (single source of truth)
│
├── cli/
│   ├── discover.py         # Discovery run from the command line (all suppliers × all items)
│   └── discover_search_url.py  # dev helper: find a site's real search URL with a headless browser
│
├── templates/
│   └── index.html          # Single-page app shell (Jinja2, all panels inline)
│
├── static/
│   ├── css/app.css         # All styles (dark/light mode via [data-theme] attr)
│   └── js/app.js           # All frontend logic (~2560 lines, vanilla JS, top-level script)
│
├── data/
│   ├── last_run.json       # Persisted results from most recent scrape run
│   └── last_import.json    # Persisted last кошторис parse result
│
├── exports/                # Generated Excel files; monitoring/ = run exports + matrices, urls/ = URL-enriched кошториси, root = legacy
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
| id | TEXT PK | ⚠ NOT a UUID. `add_item`: `datetime.now().strftime("%Y%m%d%H%M%S%f")`. `batch_add_items`: `"%Y%m%d%H%M%S%f"` + 6-digit counter, checked against existing ids; new entries are re-resolved by label after the insert so links never point at another item (fixed 2026-10, see Known issue #16) |
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
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | timestamp string `%Y%m%d%H%M%S%f` |
| name | TEXT NOT NULL | |
| created | TEXT | ISO date |
| description | TEXT | |
| avk_file | TEXT | source file name when created from an import |
| project_type | TEXT NOT NULL DEFAULT `'pvr'` | `'pvr'` (КД_ПВР) or `'rlmt'` (КД_РЛМТ). Set at creation (`create_project(..., project_type=)`), invalid values fall back to `'pvr'`. ⚠ **Immutable** — deliberately NOT in `update_project()`'s field whitelist. Pre-2026-08 projects got `'pvr'` via the DEFAULT. |

### `project_items`
| Column | Type | Notes |
|---|---|---|
| project_id | TEXT NOT NULL | |
| item_id | TEXT NOT NULL | |
| added | TEXT (ISO datetime) | |
| position | INTEGER | Row order of the imported кошторис file. NULL for pre-feature links (ordered by label as fallback). Manual adds append MAX+1. |
| qty | REAL | **Per-project** quantity — overrides `items.qty` in `get_project_items()` so two projects can share a material with different amounts. |
| estimate_unit_price | REAL | Per-project estimate price (same override rule). |
| section | INTEGER | КД_РЛМТ only: 1 = Розділ 1 (ціноутворюючі), 2 = Розділ 2 (неціноутворюючі). NULL for КД_ПВР rows and manual adds; the project export treats NULL as section 2. Returned by `get_project_items()` as `section`. |

⚠ **No PRIMARY KEY** (rebuilt 2026-07, detected via table SQL in `_migrate`): keep-order imports may store the SAME item at several positions — one per source row, each with its own qty/price (expanded from the parser's `occurrences`). Manual adds enforce uniqueness in code (`add_item_to_project`).

A project mirrors ONE imported file: importing into a project **replaces** its link set ("sync to file") via `batch_add_items(entries, project_id, keep_duplicates)` — existing items (matched by label) are linked too, not just newly inserted ones. `keep_duplicates=True` → 1:1 file mirroring (URL column aligns with the source Excel); `False` → one link per material with summed qty (UI default since 2026-08: the «зберегти порядок файлу (з повторами)» checkbox is unchecked). `section` is threaded through both modes (entry-level `section` in merge mode, `occurrences[].section` in keep mode). Monitoring always runs UNIQUE ids (frontend dedupes `item_ids`; runner sums the duplicate rows' quantities for result totals).

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
Key-value store (`key TEXT PK, value TEXT`). Used for one-time migration flags: `monitorable_version` (=2), `schema_version` (=3), and `monitor_all_mode` (`'all'`/`'filtered'` — last applied `MONITOR_ALL_ITEMS` mode, see §13).

**Migrations:** `_migrate(conn)` in `item_db.py` runs on every `init_db()` (startup). Column additions are idempotent (`PRAGMA table_info` check) — including `projects.project_type` and `project_items.position/qty/estimate_unit_price/section`. The `project_items` PK→rowid rebuild is detected by table SQL. One-time data migrations (monitorable recompute v2; indexes + price_history FK rebuild + `dd.mm.yyyy`→ISO date normalization v3; monitor-all sync when the mode changes) are guarded by the `settings` flags. Safe to run repeatedly.

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
| `project_id` | str\|None | Project of the current run (project mode), else None. Runtime-only key — use `.get()` |
| `run_options` | dict\|None | `{single_price, best_price, fill_missing, supplier_order, active_suppliers}` of the current run, so a page reload can restore + lock the toolbar. Runtime-only key — use `.get()` |

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
| POST | `/api/discover` | Discovery run: all suppliers, ignores SKIP_STALE_DAYS + session cache. Body like batch (no parallel/limit); forces `parallel_items=1`. ⚠ No UI button calls it — use the API or `python cli/discover.py` (which drives `core.runner` directly). Category routing (§8) still applies in discovery. |
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
  "run_options": {"single_price", "best_price", "fill_missing", "supplier_order", "active_suppliers"}, // restored+locked by UI on reload (incl. sidebar toggles)
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
| GET | `/api/export/excel` | Build Excel from current `state["results"]`; saves a copy to `exports/monitoring/` and streams it. 400 if no results. |
| GET | `/api/exports` | List saved exports: `[{filename, type, size_kb, created}]`, newest first. `type` ∈ `monitoring` (runs + price matrices, saved in `exports/monitoring/`), `urls` (`exports/urls/`), `root` (legacy pre-split files). |
| GET/DELETE | `/api/exports/<etype>/<filename>` | Typed download/delete (path-traversal-safe per subdir). |
| GET/DELETE | `/api/exports/<filename>` | Legacy root-dir download/delete. |
| POST | `/api/exports/add-urls` | **URL enrichment**: multipart `file` (.xls/.xlsx АВК-5) + form `column` (Excel letter; empty = append after last column) + `dups` (`all` = every repeat row gets the URL 1:1, `first` = only first occurrence). Rows matched by АВК code, fallback exact name; URL = cheapest supplier's product page (`_best_url_for_item`). .xlsx keeps formatting; .xls converted values-only. Saves to `exports/urls/`, returns `{filename, download, filled, rows, dup_skipped, not_found, converted_from_xls}`. Layout auto-detected by `_detect_layout()` (a «Розділ N» marker in column A → КД_РЛМТ): code is column B in both, name is column C (КД_ПВР) or D (КД_РЛМТ, after «Варіант ціни»); response also carries `layout`. |
| GET | `/api/export/price-matrix` | All items × all suppliers matrix from DB `last_price` (+ min/max/spread columns, min-price cells highlighted). 400 if no availability data. |

`_safe_export_path(filename)` strips characters, resolves inside `EXPORTS_DIR`, and rejects escapes — use it for any filename param.

### Kostoris routes (`routes/kostoris.py`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/kostoris/parse` | Multipart upload (`file`) + form `doc_type` (`pvr` default \| `rlmt`; anything else → `pvr`). Validates extension (`.xls`/`.xlsx`) and size (1 KB–20 MB), writes to a **temp file**, dispatches to `parsers.kostoris_parser.parse` (pvr) or `parsers.rlmt_parser.parse` (rlmt). Returns `{total, rows_total, merged, retail, items, filename, doc_type}` (total = unique materials; merged = repeat rows whose qty was summed; rlmt items/occurrences carry `section`) and saves it to `data/last_import.json`. A file of the other layout → 400 with the parser's mismatch message. Does NOT touch the DB. |
| POST | `/api/kostoris/import` | Body: `{items: [ORDERED {name, code?, category?, qty?, unit?, unit_price?, section?, occurrences?}], doc_type?, project_id? \| new_project_name?, filename?, keep_order?}` (legacy alt: `{names: [...]}`). `new_project_name` creates the project first with `project_type = doc_type` (`filename` stored as `avk_file`). An existing `project_id` must have the same type → else **400** naming both types (404 if missing). `keep_order: true` → project stores EVERY source row (duplicates included, from items' `occurrences`); else merge+sum. Bulk-inserts via `batch_add_items`: new items created, existing (by label) reused, ALL linked with positions (+ `section`) (sync-to-file). Returns `{added, linked, skipped, keep_order, doc_type, project_id, project_name}`. |
| GET | `/api/kostoris/last` | Returns `data/last_import.json` content or `null`. |

### Projects routes (`routes/projects.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/projects` | All projects (incl. `project_type`) + `item_count` (link rows — keep-order projects count repeats), `items_with_price`. |
| POST | `/api/projects` | Body: `{name, description?, avk_file?, project_type?}` (`pvr` default; invalid → `pvr`) |
| GET | `/api/projects/<id>` | Project (incl. `project_type`) + `item_count`. |
| PATCH | `/api/projects/<id>` | Update `name`/`description`/`avk_file`. ⚠ `project_type` cannot be changed. |
| DELETE | `/api/projects/<id>` | Delete project + its junction rows (items survive). |
| GET | `/api/projects/<id>/items` | Items in **file order** (`project_items.position`), enriched with `best_price`, `best_supplier`, `total_best`, `total_estimate`, `saving_pct` (honours per-result `manual_price`). Per-project qty/estimate price already spliced in by `get_project_items()`. |
| POST | `/api/projects/<id>/items` | Body: `{item_id}` → junction insert. |
| DELETE | `/api/projects/<id>/items/<item_id>` | Junction delete. |
| GET | `/api/projects/<id>/summary` | `{project, item_count, items_with_price, total_estimate, total_best, saving, saving_pct}` |
| GET | `/api/projects/<id>/export` | Excel export in file order: estimate vs best-price comparison per item, one column per supplier, plus `Постачальник (мін.)` and `Посилання` (cheapest supplier's URL as plain text, empty when no price — customer copies this column against the source кошторис). For `project_type == 'rlmt'` rows are grouped under merged, styled title rows «Розділ 1. Ціноутворюючі матеріали» / «Розділ 2. Неціноутворюючі матеріали» (section NULL → 2; empty section omitted; no subtotal rows), each in file order. ⚠ openpyxl `merge_cells()` keeps only the anchor cell's value — the title is written to column A explicitly. |

---

## 6. Scraping Pipeline (`core/runner.py`)

### Entry points (both spawn a daemon thread running `_run_batch`)

- `start_scrape(item_id, active_supplier_ids)` — batch of one, `parallel_items=1`.
- `start_batch(item_ids, active_supplier_ids, parallel_items=None, limit=None, discovery_mode=False, project_id=None, run_label=None, single_price=False, best_price=False, supplier_order=None, fill_missing=False)`

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

Groups: `GENERAL_SUPPLIERS` (10 retail: epicentr, ars, buddvir, kub, venbud, budpostach, m2, vista, megatrade, budia), `MARKETPLACE_SUPPLIERS` (prom, olx), `HVAC_SUPPLIERS` (teplodim), `ELECTRICAL_SUPPLIERS` (epicentr, kub, m2), `PLUMBING_SUPPLIERS` (6), `INSULATION_SUPPLIERS` (8). ⚠ `HARDWARE_SUPPLIERS` is defined but not referenced by `CATEGORY_ROUTING` — dead config.

⚠ **Every registered supplier must be reachable by some rule.** Until 2026-10 `budpostach` sat only in the unused `HARDWARE_SUPPLIERS`, so Будпостач was never queried (its sidebar toggle had no effect); it is now in `GENERAL_SUPPLIERS`. `tests/test_category_routing.py` fails if any registry id becomes unreachable again.

The parser's fallback category `Матеріали будівельні` (unknown codes) is not a `CATEGORY_ROUTING` key (that key is `Будівельні матеріали`), so such items take the `DEFAULT_SUPPLIERS` path — same list, by design or by accident.

---

## 9. Estimate Parsers (`parsers/`)

Two layouts, one contract: `parse(filepath: str) -> list[dict]`. The user picks the layout (`doc_type`) in the import UI; the route dispatches to the matching parser. Both read `.xls` via `xlrd` (manual cell copy → DataFrame) or `.xlsx` via `pandas.read_excel(sheet_name=0, header=None)`, and get a **temp file path** from the upload route. In the `.xls` path `_parse_df()` is called **outside** the xlrd `try/except`, so the parser's own `ValueError`s (layout mismatch) reach the user unwrapped.

Shared rules:
- `CODE_RE = re.compile(r'^[&+]?[СCКк\d][\dА-Яа-яA-Za-z]')` — only rows with a resource code are items (labour totals, headers, «Разом:» and page-number rows fail it); `варіант N` suffixes stripped.
- Repeated materials are MERGED into one entry, quantities SUMMED when units match; `rows` = merged source rows; `occurrences = [{seq, qty, unit_price[, section]}]` keeps every source row (file ordinal) for keep-order project imports. Parse response exposes `rows_total`/`merged`; the UI shows the merge note and an ×N badge.
- Category via `parsers/category_codes.derive_category(code)` (single source of truth, extracted 2026-08): К→Конструкції збірні; С111→Підлоги/покрівлі; С112→Пиломатеріали; С113→Трубопроводи; С114→Теплоізоляція; С121/С124→метал; С123→Вікна та двері; С130 (sub-code 62 → Вентиляція, else Теплопостачання); С151–152→Кабельні системи; equipment ranges 1100–1999; С100-XXXX by sub-code; fallback `Матеріали будівельні`.
- Item dict: `{code, name, unit, qty, unit_price, retail, category, rows, occurrences}` where `retail = is_monitorable(name)` ⚠ (named `retail` in parse output, becomes `monitorable` after import).

### `kostoris_parser.py` — КД_ПВР («Підсумкова відомість ресурсів»)
- Columns (0-indexed): 1 = code, 2 = name, 3 = unit, 4 = qty, 6 = unit price (first line of a «за од.\nвсього» cell).
- Merge key: lowercased name.
- Mismatch guard: any col-0 cell matching `^Розділ\s*\d` → `ValueError` ("схоже на файл КД_РЛМТ").

### `rlmt_parser.py` — КД_РЛМТ («Відомість матеріальних ресурсів із зазначенням відсоткової частки»)
- Columns (0-indexed): 0 = № / section markers / «Разом:», 1 = code, 2 = «Варіант ціни» (ignored), 3 = name, 4 = unit, 5 = qty, 6 = unit price (single number), 7 = total, 8–9 = % shares (ignored).
- Rows are scanned in order; a col-0 match of `^Розділ\s*(\d+)` sets `current_section` (marker rows are not items). Every item and occurrence carries `section` (1 = ціноутворюючі ≥60 % of cost, 2 = неціноутворюючі ≤40 %).
- Merge key: `(lowercased name, section)` — a material is never merged across sections.
- Mismatch guard: no `Розділ` marker at all → `ValueError` ("схоже на файл КД_ПВР").

⚠ Both parsers index `row[6]` and assume ≥7 columns; narrower sheets raise and surface as HTTP 500 (Known issue #5).

---

## 10. Suppliers Registry (`core/suppliers.py`)

```python
SUPPLIER_REGISTRY: list[tuple[id, name, url, module, enabled]]  # 13 entries
SUPPLIERS = build_suppliers()   # module-level, built at import
```

`build_suppliers()` imports each scraper module; a failed import prints a warning and **skips that supplier** (no crash). `enabled=True` means "available to toggle in the UI"; the template renders every enabled toggle checked and the frontend then restores the user's saved selection. Marketplaces (prom, olx) were added 2026-05-18. ⚠ Being registered does not mean being queried — routing (§8) decides which suppliers each item gets.

**To add a supplier:** create `scrapers/<id>.py` with the `scrape()` contract (usually just a `SiteConfig` + `search_and_extract`/`text_based_extract` wrapper — see `vista.py` for the minimal pattern), add one registry tuple, optionally add routing in `category_routing.py`.

---

## 11. Frontend (`static/js/app.js`)

~2560 lines, vanilla JS, plain top-level script (no IIFE, no modules, no build step). Cache-busted via `?v={mtime}` (newer of app.js/app.css mtimes, computed by `_asset_version()` in app.py).

### Key globals

| Variable | Purpose |
|---|---|
| `allItems` / `allItemsData` | Item lists for dropdown / items panel |
| `importItems` / `selectedNames` | Last кошторис parse rows + selected-for-import set |
| `importDocType` / `importFilename` | Import file type `'pvr'`\|`'rlmt'` (restored from `/api/kostoris/last.doc_type` at boot) / last parsed file name |
| `projCreateType` | Type picked in the Projects panel's «+ Новий проект» form |
| `monitorQueue` / `monitorDone` / `monitorMode` | Active queue, done counter, `'single'`\|`'batch'`\|`'project'` |
| `modeQueues` / `monitorProjectId` / `runningMode` | Separate queues for Черга / Проекти, selected project, mode that owns the active run |
| `batchRunning` / `batchStopped` / `singleRunning` | Batch poll-loop state / stop-clicked latch / single-scrape running |
| `allProjects` / `activeProjectId` | `/api/projects` cache / project open in the Projects panel |
| `serverConfig` | `{max_parallel_items, default_parallel_items, skip_stale_days, monitor_all_items}` fetched from `/api/config` at boot (static fallback `{5, 3}` until then) |
| `availabilityData` | Cached `/api/availability` response `{coverage, items}` |
| `MAX_LOG_LINES = 800` | Batch log trim threshold |

⚠ There is **no `currentPanel` global** — active panel is tracked via DOM classes by `showPanel(name, btn)`.

### Key functions (search by name — line numbers drift)

| Function | Description |
|---|---|
| `showPanel(name, btn)` | Switch panel + nav highlight |
| `setMonitorMode(mode)` | `'single'`/`'batch'`/`'project'` sub-tabs. Single mode hosts the execution journal (`#t-body` terminal + `#log-sub` — there is NO separate Журнал nav tab; it was merged into Monitoring). Batch/project call `renderMonitorTab()`; project mode shows `#monitor-project-bar`. Monitoring is the default active panel on load. |
| `onMonitorProjectChange()` | Loads `/api/projects/<id>/items` (file order) into `monitorQueue`; `monitorProjectId` global tags the run. `runBatch()` then sends `project_id` + `label: "Проект: <name>"`. |
| `onSearchOptsChange()` / `renderSupplierOrderBox()` / `moveSupplierOrder()` | Batch toolbar checkboxes: `#opt-single-price` gates `#opt-best-price` (disabled+unchecked otherwise); single-without-best shows `#supplier-order-box` — active suppliers reorderable with ◀▶, order persisted in `localStorage['supplierOrder']`, sent as `supplier_order`. `#opt-fill-missing` → `fill_missing`. Checkbox states persist in `localStorage['searchOpts']`; sidebar supplier toggles persist in `localStorage['activeSuppliers']` (template renders all-checked, `restoreSupplierSelection()` re-applies at boot; during a run the server's `run_options.active_suppliers` wins). Паралельно + К-сть товарів persist in `localStorage['batchParallel'/'batchLimit']` via `saveBatchControls()`/`applyBatchControls()` — saved ONLY in explicit change handlers (never render passes); the `/api/config` option rebuild re-applies them; during a run `pendingRunControls` (from status `parallel_items`/`limit`/`total_items`) wins and the controls are locked. |
| `updateRunLockUI()` / `runningMode` / `singleRunning` / `modeQueues` | ONE monitoring at a time across all three modes (single/batch/project): while a run is active, all Run buttons, option checkboxes, project selector, supplier order AND the sidebar supplier toggles are locked (sidebar via `pointer-events` + `onSupplierToggle()` revert-guard — NOT via `disabled`, which marks not-implemented suppliers and is filtered by `getEnabledIds()`); guards in `runBatch()`/`startScrape()`/`toggleAllSuppliers()`. Черга and Проекти have SEPARATE queues (`modeQueues`, swapped in `setMonitorMode`); the run's log/progress/stop are shown only in `runningMode`'s view. On reload the run's options come back from `/api/status.run_options` and stay locked until the run ends. |
| `setDocType(t)` / `_setToggleActive(id, t)` | Import tab КД_ПВР/КД_РЛМТ toggle (`#doc-type-toggle`): sets `importDocType`, updates the drop-zone hint (`DOC_TYPE_SUB_TEXT`), **resets an already-parsed preview** (it belongs to the old type) and re-filters the project dropdown. |
| `parseKostoris(file)` | POST `/api/kostoris/parse` with `file` + `doc_type`; renders stats, category chips and the preview table. |
| `renderImportTable()` | Preview rows: ×N merge badge, `§1`/`§2` `.sec-badge` for КД_РЛМТ rows. |
| `doImport(toProject)` | POST `/api/kostoris/import` with `items` (incl. `section`, `occurrences`), `doc_type`, and for projects `project_id`/`new_project_name` + `keep_order` (`#import-keep-order`, **unchecked by default**). |
| `populateImportProjectSelect()` / `onImportProjectChange()` | Project dropdown lists only projects whose `project_type` equals `importDocType` (the server also rejects a mismatch with 400); "+ Новий проект…" reveals `#import-new-project-name` (prefilled from `importFilename`). |
| `setProjCreateType(t)` / `createProject()` / `_projTypeBadge(p)` | Projects panel create form with type toggle (sends `project_type`); ПВР/РЛМТ pill badge in the list and detail header. |
| `renderProjectsList()` / `viewProject(id)` / `_renderProjectDetail(id)` | Project cards; detail = KPI cards (Матеріалів / Кошторис / Мін. ціни / Економія) + items table + «＋ Додати матеріал» search panel + «▶ Моніторинг» (`_queueProjectItems` → Проекти mode) + «↓ Excel». |
| `renderItemsTab()` / `addSelectedToQueue()` | «База матеріалів» table, filters, selection → Черга queue (the only way to fill Черга; `addAllToQueue()` is unused). Row actions: manual price (`setManualPrice` → PATCH item), ▶ `selectItemForMonitoring`, 📈 `showPriceHistory` (modal with SVG `sparkline()` per supplier). |
| `renderResults(items, query)` | Groups by `item_label`, sorts each group by price, medals for top-3 distinct prices; inline `contenteditable` price/comment cells (`_attachCellEditor`/`_saveCell` → PATCH `/api/results/...`). No column sorting; the search filters by material label only. |
| `runAddUrls()` / `loadExports()` | Exports panel: URL enrichment upload; file list grouped `urls` vs monitoring/legacy. |
| `loadAvailability()` / `renderAvailability()` | Availability matrix + coverage header; `highlightSuppliersForItem()` marks the sidebar. |
| `renderMonitorTab()` | Rebuild queue list, estimated time |
| `runBatch()` | POST `/api/scrape/batch` → poll loop (1500 ms, `?log_offset=`) |
| `stopBatch()` | POST `/api/stop`, sets `batchStopped=true`, disables button |
| `updateBatchProgress(done, total, startedAt)` | Progress bar + `X/N` counter |
| `appendBatchLog(lines)` / `batchLog(msg)` | Incremental log append + trim |
| `poll()` | Single-scrape poller, **1200 ms** interval |
| `updateRunBadges(d)` | Mirrors `label`/`last_run` from an `/api/status` payload into the header badges + sidebar. Called every tick by BOTH batch poll loops (and inlined in `poll()`) — without it the Results-tab chips show the previous run until refresh. |
| `loadResults()` | GET `/api/results` → render table |
| `_startElapsedTick(startedAt)` / `_stopElapsedTick()` | 1 s elapsed timer |

### Page-reload reconnect (startup block, near the top of app.js)

On load, GET `/api/status`; if `running`:
- `parallel_items && total_items > 1` → batch reconnect: `showPanel('monitor')` → `setMonitorMode(runningMode)` (`'project'` when `status.project_id` is set, else `'batch'`) → restore + lock `run_options` and parallel/limit → **then** `updateBatchProgress(...)` (order matters: `setMonitorMode` → `renderMonitorTab()` would reset the progress display) → restore the run's queue from `/api/items` in `status.item_ids` order → async `reconnectBatchPoll()` loop (1500 ms).
- Otherwise → single-item reconnect via `poll()` (sidebar suppliers restored from `run_options`).

Startup also restores last results (`/api/results`) and the last import preview (`/api/kostoris/last`, including its `doc_type` toggle state).

### Batch poll exit condition

Both `runBatch()` and `reconnectBatchPoll()` break **only** on `s.running === false` — never on `batchStopped`. The UI waits for the server to fully drain before re-enabling Run and switching to Results.

### Stop button

Lives in `#btn-stop-batch-wrap` (hidden by default) — show/hide the **wrapper**. Tooltip `.stop-tip-box` is CSS-only, anchored to `.stop-tip-wrap:hover`, arrow points down via `::before`/`::after` border tricks.

---

## 12. Styling (`static/css/app.css`)

Theming via `[data-theme="dark"]` on `<html>`; palette in CSS custom properties (`--paper`, `--ink`, `--accent`, …).

Only theme variables are used by the 2026-08 additions — `.doc-type-btn`/`.doc-type-btn.active` (КД_ПВР/КД_РЛМТ toggles), `.sec-badge` (§1/§2 in the import preview); the project-type badge reuses `.pill` + `.pill-teal`/`.pill-gold` — so they need no dark overrides.

Dark-mode filter-button fix (keep):
```css
[data-theme="dark"] .btn-sel-all { background: var(--paper2); color: var(--ink); border-color: var(--border2); }
```

---

## 13. Environment Variables (`.env`, read via python-dotenv)

| Variable | Default | Where used |
|---|---|---|
| `PORT` | `8765` | `app.py` + `setup_gui.py` (keep the two defaults in sync). ⚠ Was 5000 — changed because other Windows software constantly POSTs to localhost:5000 (405 log noise / port conflicts). |
| `MAX_PARALLEL_ITEMS` | `10` | `runner.py` outer pool cap. `DEFAULT_PARALLEL_ITEMS = min(cap, 5)`. ⚠ `app.py`'s startup banner re-reads it with default `"5"` — display only. |
| `MAX_INNER_WORKERS` | `8` | Suppliers per item in parallel (the «Паралельно» tooltip in index.html should not hard-code a number) |
| `MAX_INNER_WORKERS_DISCOVERY` | `10` | Inner workers in discovery mode (items run sequentially) |
| `SKIP_STALE_DAYS` | `30` | Days before a "not found" entry is re-checked |
| `MONITOR_ALL_ITEMS` | `1` (⚠ default ON in code) | TEMPORARY customer request 2026-07: bypasses the SKIP_KW blocklist — `is_monitorable()` always True + one-time startup sync sets every existing item `monitorable=1` (settings key `monitor_all_mode` in `_migrate()`). Default is ON so fresh installs from git behave the same without a .env. To revert: set `MONITOR_ALL_ITEMS=0` in .env (or flip the code default in matching/monitorable.py) + restart — flags are recomputed from labels. |

There is no `.env.example`. `ANTHROPIC_API_KEY` (a leftover of the pre-Scrapling LLM pipeline) may still sit in old local `.env` files — nothing reads it.

---

## 14. Excel Exports (`routes/exports.py`, `routes/projects.py`)

`_build_excel(results, label)` (pandas + openpyxl, in-memory):

- One flat sheet "Ціни"; ⚠ **no blank separator rows and no 🥇🥈🥉 emoji** — top-3 cheapest per `item_label` group get **whole-row fills** (gold `FFF4C7` / silver `E5E5E5` / bronze `F4DBC1`) + bold colored price cell. Ranks computed on *distinct* prices; ties share a rank. Prices ≤ 0 are excluded from ranking (fill_missing stub rows must never get a medal).
- Column order = `COLUMN_ORDER`: Матеріал кошторису, Назва товару, Ціна за од., Валюта, Од., К-сть (кошторис), Од. (кошторис), Загальна ціна, Бренд, Артикул, Характеристики, Постачальник, Коментар, Посилання, Дата. ⚠ There is no `#`, no estimate-price and no Diff% column in this export.
- Dark header row, auto column widths, saved to `exports/monitoring/<label>_<timestamp>.xlsx` and streamed. The UI's 🥇🥈🥉 emoji exist only in the Results tab.

`/api/export/price-matrix` builds item × supplier `last_price` matrix (sheet «Прайс-матриця») with Мін/Макс/Знайдено (сайтів)/Розкид % columns; min-price cells highlighted green; saved to `exports/monitoring/price_matrix_<timestamp>.xlsx`.

`/api/projects/<id>/export` (`routes/projects.py`, sheet «Кошторис», not saved to disk): Код АВК-5, Матеріал, Категорія, Од., К-сть, Ціна кошт., Сума кошт., one column per enabled supplier (`last_price`), Мін. ціна, Постачальник (мін.), Посилання, Сума мін., Економія % (green if positive, red if negative). КД_РЛМТ projects get the two section title rows (see §5).

`/api/exports/add-urls` writes into a copy of the uploaded estimate → `exports/urls/` (see §5).

---

## 15. Critical Conventions & Gotchas

### Cyrillic + CRLF files: verify bytes after every edit

Tracked text files are UTF-8 with **CRLF** in the working tree (`ЯК ЗАПУСТИТИ.txt` also has a BOM; git normalizes some to LF in the index — on a non-Windows checkout `git status` can show EOL-only "changes", check with `git diff --ignore-cr-at-eol`). String-match edits have corrupted `app.js`/`app.css`/`index.html` with null bytes (`\x00`) on Windows before. Whatever tool you edit with, afterwards check: valid UTF-8, zero `\x00`, no bare `\n` in CRLF files. The safe fallback is a Python byte-level edit:

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
- **A project mirrors ONE file layout:** `project_type` is immutable; importing a КД_РЛМТ file into a КД_ПВР project (or vice versa) is rejected by the server and hidden in the UI dropdown. The КД_РЛМТ section export depends on every link having come from the same layout.
- **Parsers share `category_codes.derive_category()`** — change category logic there, never copy it into a parser.

### Known issues & dead code (as of 2026-10-08)

**Correctness / concurrency:**

1. ⚠ Check-then-act race on `state["running"]` in scrape routes (see §4).
2. ⚠ `/api/status` may hit "dict changed size" while a batch is (re)initializing `item_states` (see §4).
3. ⚠ `m2.py` single-word search fallback passes the word as the *matching label* (`search_and_extract(CONFIG, word, log)`) — candidates are scored against one generic word, so a wrong product can be saved as `found=1`, and its URL then becomes the trusted `saved_url` on later runs (self-perpetuating). Fix: keep the word as the search query but score candidates against the full original label (venbud.py's fallback already does this correctly — copy that pattern).
4. Runner ignores the second element of a scraper's `(None, url)` return — on not-found it re-writes the previously saved DB URL; returning a fresh URL without a result has no effect.
5. Both parsers assume ≥7 columns (`row[6]`); narrower sheets raise and surface as HTTP 500 from `/api/kostoris/parse`.

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

**Found 2026-10-08 (documented, not yet fixed):**

15. ✅ *Fixed 2026-10:* Будпостач was never queried (only in the unused `HARDWARE_SUPPLIERS`) — now in `GENERAL_SUPPLIERS`, guarded by `tests/test_category_routing.py`.
16. ✅ *Fixed 2026-10:* item-ID collision in `batch_add_items()` — second-resolution ids could repeat across two imports in the same second, and `INSERT OR IGNORE` then linked the project to a different, older item. Now microsecond ids + uniqueness check + re-resolve by label; covered by `tests/test_batch_add_items.py`.
17. ✅ *Fixed 2026-10:* URL enrichment read the name from column C, which is «Варіант ціни» in КД_РЛМТ files (name matches silently failed) — layout is now auto-detected; covered by `tests/test_url_enrichment.py`.
18. Unused code: JS `addAllToQueue()`, `origShowPanel`, `toggleAll()`; Python `get_items_for_supplier()`, `get_item_projects()`, `get_price_history_bulk()` (`item_db.py`).
19. `index.html`'s static «Паралельно» options (1–3, default 3) are only a fallback — they are rebuilt from `/api/config` (1..`MAX_PARALLEL_ITEMS`, default `DEFAULT_PARALLEL_ITEMS`) at boot.

---

## 16. Tests

Run: `python -m pytest tests/ -v` — no network, pure logic. ⚠ `test_price_parsing.py` imports `scrapers._scrapling_base`, which imports `scrapling` at module level — it errors at collection where `scrapling` isn't installed (run `--ignore=tests/test_price_parsing.py` there). The parsers and the project/kostoris routes have no tests yet.

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
| `test_session_cache.py` | runner `_session_cache`: key includes the supplier set; not populated in discovery mode |
| `test_excel_medals.py` | top-3 medal rank assignment |
| `test_category_routing.py` | every registered supplier is reachable by routing; disabled suppliers never returned |
| `test_url_enrichment.py` | add-urls layout detection; КД_ПВР and КД_РЛМТ rows matched by code and by name |
| `test_batch_add_items.py` | temp SQLite DB: two imports at the same instant link their own items; existing labels reused |

---

## 17. Startup Sequence

```
START.bat  (silent: only errors if Python itself is missing)
  → start pythonw setup_gui.py
setup_gui.py  (tkinter window, STDLIB ONLY — system Python, pre-venv)
  → checks Python ≥3.10 (messagebox on failure)
  → if http://localhost:PORT already answers → "вже запущено", open browser, exit setup path
  → first run (.venv\.setup_done missing): venv → pip install uv → `python -m uv pip
    install -r requirements.txt` (parallel downloads, ~5-10× faster; falls back to
    plain pip on any uv failure) → scrapling.exe install (fallback: python -m
    playwright install chromium) — with progress steps + collapsible log; marker
    touched on success. Browser downloads remain the longest step (~hundreds of MB).
  → Popen(.venv\Scripts\python.exe app.py, CREATE_NO_WINDOW), streams server output
    into the log, waits for the HTTP endpoint (≤90 s), opens the browser
  → window = server controller: «Відкрити у браузері» / «Зупинити» / «Детальніше ▾»
    (log); closing the window terminates the server process. Steps shown: «Створення
    середовища» → «Встановлення компонентів» → «Завантаження браузера» → «Запуск
    PriceScout». Borderless window (custom title bar, drag, taskbar/minimize and Win11
    rounded corners via ctypes), "PS" brand icon embedded as base64 PNGs.
app.py
  → load_dotenv()
  → Flask(__name__) + register 5 blueprints
  → AT IMPORT TIME: init_db() (tables + _migrate()), ensure_exports_dir(), ensure_debug_dir()
  → app.run(debug=False, host="0.0.0.0", port=PORT, threaded=True)
```

⚠ `init_db()` runs at module import (so WSGI servers get it too). ⚠ Binds `0.0.0.0` — LAN-exposed, no auth. ⚠ `setup_gui.py` must stay stdlib-only — it executes before any dependency exists.

---

## 18. CI / Release (`.github/workflows/notify-release-mail.yml`)

Trigger: push to `main` (or manual `workflow_dispatch`). Steps: checkout → `git archive` → `PriceScout.zip` → `softprops/action-gh-release` creates release `v<run_number>` with the zip → `dawidd6/action-send-mail` emails the asset download link (Ukrainian text) via `smtp.zoho.eu:465`.

- Secrets: `SMTP_USERNAME`, `SMTP_PASSWORD`; repository variable: `CUSTOMER_EMAIL`. Nothing sensitive is stored in the file.
- Day-to-day work happens on `dev`; merging `dev` → `main` is what ships a release to the customer.
- There is no test/lint job in CI — run `pytest` locally before merging.
