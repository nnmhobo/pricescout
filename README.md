# PriceScout — Construction Materials Price Monitor

PriceScout is a local web app that takes a Ukrainian construction cost estimate (кошторис exported from АВК-5), searches Ukrainian building-supply websites for every material in it, and produces Excel reports that compare estimate prices with the best market prices — keeping the original file's structure.

**Stack:** Python · Flask · SQLite · Scrapling · RapidFuzz · pandas / openpyxl · vanilla JavaScript · Tkinter launcher · pytest · GitHub Actions

> Українською: коротка інструкція для користувача — у файлі [`ЯК ЗАПУСТИТИ.txt`](ЯК%20ЗАПУСТИТИ.txt).

---

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Suppliers](#suppliers)
- [Getting started](#getting-started)
- [User guide](#user-guide)
- [Configuration](#configuration)
- [Command-line tools](#command-line-tools)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## Features

**Estimate import**
- Two estimate layouts, chosen explicitly at import time:
  - **КД_ПВР** — «Підсумкова відомість ресурсів» (summary resource sheet);
  - **КД_РЛМТ** — «Відомість матеріальних ресурсів» split into **Розділ 1** (price-forming materials, ≥60 % of cost) and **Розділ 2** (the rest, ≤40 %).
- A file that does not match the selected type is rejected with a clear message.
- Only rows with a resource code (materials and equipment) are taken; each gets a category derived from its code.
- Repeated rows of the same material are merged with summed quantities; the preview shows how many rows were merged.

**Price search**
- 13 supplier sites (retail chains plus Prom.ua / OLX marketplaces), queried in parallel.
- Suppliers are picked per material by category (e.g. heating equipment → HVAC specialist), not blindly.
- Several search queries per material (Ukrainian/Russian spelling, brand-code expansion, shortened spec strings), with a fuzzy matcher that rejects unrelated products.
- Saved product URLs are re-checked first; suppliers that recently returned "not found" are skipped for a configurable number of days.
- Run modes: all prices per material, **one price** (suppliers probed in your priority order until the first hit), or **cheapest price only**; optional zero-price rows for items that were not found.
- Batch runs keep going in the background; reloading the page reconnects to the running batch.

**Results and reports**
- Results grouped by material with 🥇🥈🥉 for the three cheapest offers; price and comment cells are editable inline and the edits survive later re-scrapes.
- Excel exports: run results (medal-coloured rows), item × supplier price matrix, and per-project comparison (estimate vs. cheapest price, supplier, link, saving %).
- **КД_РЛМТ projects export in their original two sections**, in the original row order.
- Upload an estimate and get it back with a column of product links filled in.
- Per-supplier price history with sparklines.

**Projects**
- A project mirrors one imported estimate: file row order, per-project quantities and estimate prices, project type (КД_ПВР / КД_РЛМТ).
- KPI summary: estimate total, total at best prices, saving.

**Desktop-friendly**
- Windows launcher window (Tkinter, standard library only) that creates the virtual environment, installs dependencies (via `uv`, falling back to `pip`), downloads the scraping browser, starts the server and opens the browser.

---

## How it works

```
Estimate (.xls/.xlsx)
   │  parsers/kostoris_parser.py (КД_ПВР) · parsers/rlmt_parser.py (КД_РЛМТ)
   ▼
SQLite (pricescout.db) ── items, projects, supplier_entries, price_history
   │
   ▼  core/runner.py — thread pool: items in parallel × suppliers in parallel
matching/category_routing.py → which suppliers to ask
scrapers/<supplier>.py + scrapers/_scrapling_base.py → fetch & extract
matching/matcher.py → does the found product really match the material?
   │
   ▼
Flask API (routes/*) ──► single-page UI (templates/index.html + static/js/app.js)
   │
   ▼
Excel exports (exports/monitoring, exports/urls) via pandas + openpyxl
```

| Layer | Files |
|---|---|
| Web app & API | `app.py`, `routes/scrape.py`, `routes/items.py`, `routes/kostoris.py`, `routes/projects.py`, `routes/exports.py` |
| Run orchestration, state, DB | `core/runner.py`, `core/core.py`, `core/item_db.py`, `core/suppliers.py` |
| Estimate parsing | `parsers/kostoris_parser.py`, `parsers/rlmt_parser.py`, `parsers/category_codes.py` |
| Matching & routing | `matching/matcher.py`, `matching/category_routing.py`, `matching/monitorable.py`, `matching/search_label_converter.py` |
| Scrapers | `scrapers/_scrapling_base.py`, `scrapers/query_variations.py`, `scrapers/query_simplifier.py`, one module per supplier |
| Frontend | `templates/index.html`, `static/js/app.js`, `static/css/app.css` (light/dark theme) |
| Launcher | `START.bat`, `setup_gui.py` |

A detailed technical reference (database schema, every API endpoint, runner flow, conventions, known issues) is in [`OVERVIEW.md`](OVERVIEW.md).

---

## Suppliers

| Supplier | Site | Scraper |
|---|---|---|
| Епіцентр К | epicentrk.ua | custom, plain HTTP |
| АРС | ars.ua | custom, stealth browser (Cloudflare) |
| Будівельний Двір | buddvir.ua | generic text extraction, plain HTTP |
| КУБ | kub.in.ua | custom, browser (JS-rendered search) |
| Вен Буд | venbud.ua | custom, AJAX live-search endpoint |
| Будпостач | budpostach.ua | generic text extraction, plain HTTP |
| М2 | m2.org.ua | generic CSS extraction + single-word fallback |
| Віста | vista.ua | generic CSS extraction |
| Мегатрейд СМ | megatrade-sm.com.ua | generic text extraction |
| Будія | budia.ua | generic text extraction |
| ТеплоДiм | teplodim.com.ua | generic CSS extraction (heating / HVAC) |
| Prom.ua | prom.ua | generic CSS extraction (marketplace) |
| OLX | olx.ua | generic CSS extraction (classifieds) |

Adding a supplier is usually one `SiteConfig` (search URL + CSS selectors) in a new `scrapers/<id>.py` and one line in `core/suppliers.py`.

> **Routing note:** which suppliers are asked depends on the material's category (`matching/category_routing.py`). ТеплоДiм is used for heating/ventilation categories; Prom.ua and OLX are appended after the retailers. Будпостач is currently not included in any active routing list, so it is never queried — see *Known issues* in `OVERVIEW.md`.

---

## Getting started

### Windows (end users)

1. Install **Python 3.10+** from [python.org/downloads](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"** in the installer.
2. Double-click **`START.bat`**. The PriceScout window opens and runs the setup steps: «Створення середовища» → «Встановлення компонентів» → «Завантаження браузера» → «Запуск PriceScout». The first launch takes about 5–10 minutes (the browser download is the longest step); later launches take seconds.
3. The browser opens **http://localhost:8765** automatically. The launcher window has «Відкрити у браузері», «Зупинити» and «Детальніше ▾» (setup log). Closing the window stops the server.

### Manual / development setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on Linux/macOS
pip install -r requirements.txt
scrapling install               # downloads the browsers used by browser-mode scrapers
python app.py                   # serves http://localhost:8765
```

The database (`pricescout.db`), `data/`, `exports/` and `debug/` are created on first start; schema migrations run automatically on every start.

---

## User guide

The top navigation has seven sections, in this order: **Моніторинг** (opens by default) · **Результати** · **База матеріалів** · **Експорти** · **Імпорт кошторису** · **Наявність** · **Проекти**. The left sidebar is always visible: a material name field, the saved-materials search, and the supplier toggles («Вимкнути всі» / «Увімкнути всі»). The 🌙 button switches light/dark theme.

### 1. Import an estimate — «Імпорт кошторису»

1. Pick the file type: **КД_ПВР** or **КД_РЛМТ** (default КД_ПВР).
2. Drop the `.xls`/`.xlsx` file on the drop zone or click it to choose a file. The file is parsed immediately.
3. Review the preview: counters show positions / selected, merged rows are marked ×N, КД_РЛМТ rows carry a §1/§2 section badge. Narrow the list with the category chips («Всі» / «Жодної») and the search box; untick rows you don't need.
4. Save:
   - **«↓ Додати вибрані до бази матеріалів»** — adds the selected materials to the shared materials database (duplicates by name are skipped).
   - **«→ Додати у проект»** — additionally links them to a project: pick an existing project of the same type or «+ Новий проект…» and enter a name. Importing into a project replaces its contents with the file's selection, in file order.
   - **«зберегти порядок файлу (з повторами)»** (off by default): when on, the project keeps every source row, repeats included, so a link column can be pasted 1:1 next to the original file. When off, repeats are merged and quantities summed.

The last parsed file stays in the import tab after a page reload.

### 2. Materials database — «База матеріалів»

All saved materials with category, АВК-5 code, source (кошторис / вручну), search status, availability (found/checked suppliers) and best price.

- «+ Додати вручну» adds a material by name.
- Filters by source, category, search status and price.
- Tick rows and press **«▶ Додати до черги моніторингу»** to queue them for a batch run.
- Per row: «Своя ціна» (fixed manual price), ▶ (search this material now), 📈 (price history), ✕ (delete).

### 3. Search prices — «Моніторинг»

Three modes:

- **Один матеріал** — type a name in the sidebar field «Назва матеріалу» (or pick a saved one) and press **«Запустити моніторинг»** in the sidebar. This tab shows the live log. «☆ Зберегти матеріал» saves the typed name to the database.
- **Черга** — the queue filled from «База матеріалів». Toolbar:
  - «К-сть товарів»: all, the first 5/10/20/50, or a custom number;
  - «Паралельно»: how many materials are searched at once (default 5, max `MAX_PARALLEL_ITEMS`);
  - «Пошук однієї ціни»: stop at the first supplier that has a price, probing suppliers in the order you arrange with ◀ ▶;
  - «Найменша ціна» (with one-price mode): ask all suppliers, keep only the cheapest;
  - «Ціна 0, якщо не знайдено»: add a zero-price row for every material without a price, so the Excel has one row per position;
  - «✕ Очистити» empties the queue; **«Запустити чергу»** starts the run.
- **Проекти** — choose a project; the queue is its materials in estimate order (repeats are searched once).

The queue shows each material's status (пошук / пропуск / поза лімітом), last best price and last check date, plus an estimated run time. While running, a progress bar, elapsed time and the log are shown; **«◼ Зупинити»** stops gracefully (requests already in flight finish, nothing is lost). Only one run can be active at a time, and its settings are locked until it ends. Reloading the page reconnects to the running batch.

### 4. Results — «Результати»

The last run's results (also restored after an app restart), grouped by material, cheapest first, with 🥇🥈🥉 on the three lowest distinct prices. Columns: product name (link), unit price, unit, estimate quantity and unit, total, brand, supplier, SKU, comment.

- Click a price to correct it, or the comment cell to add a note (Enter saves, Esc cancels). A ✎ mark shows a corrected price; corrections persist and go into exports.
- «Пошук по матеріалу…» filters by material name.
- **«↓ Завантажити Excel»** downloads the results (a copy is saved under `exports/monitoring/`).

### 5. Projects — «Проекти»

- **«+ Новий проект»**: name, optional description and type (КД_ПВР / КД_РЛМТ). Projects are usually created straight from the import tab.
- The project page shows KPI cards (Матеріалів, Кошторис, Мін. ціни, Економія) and a table with estimate price and total, best price and total, the supplier where it was found, and saving %.
- «＋ Додати матеріал» adds materials from the database; ✕ removes them.
- **«▶ Моніторинг»** opens the «Проекти» monitoring mode with this project.
- **«↓ Excel»** exports the comparison in estimate order, with one column per supplier, the cheapest supplier and its link. For a **КД_РЛМТ** project the export keeps the two sections («Розділ 1. Ціноутворюючі матеріали», «Розділ 2. Неціноутворюючі матеріали») as separate blocks.

### 6. Exports — «Експорти»

- Saved files are grouped into monitoring runs / price matrices and estimates with links, with download and delete buttons.
- **«Додати посилання у кошторис»**: upload an estimate and get a copy with a link column filled from the database (the cheapest supplier's product page). Rows are matched by resource code, then by exact name. You can choose the target column and whether repeated rows all get the link («Повтори: заповнювати всі (1:1)») or only the first one. `.xlsx` keeps its formatting; `.xls` is converted to `.xlsx` (values only). Name matching currently works for the КД_ПВР layout; КД_РЛМТ files match by code only.

### 7. Availability — «Наявність»

A matrix of materials × suppliers showing where each material was found (with prices) and per-supplier coverage in the header. Filters: full / partial / not found, plus search. **«↓ Прайс-матриця Excel»** exports all prices with min / max / spread columns.

---

## Configuration

Optional `.env` file in the project folder (restart to apply):

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8765` | Web server port (read by both `app.py` and the launcher) |
| `MAX_PARALLEL_ITEMS` | `10` | Upper limit for «Паралельно»; the UI default is `min(10, 5)` |
| `MAX_INNER_WORKERS` | `8` | Parallel supplier requests per material |
| `MAX_INNER_WORKERS_DISCOVERY` | `10` | The same for discovery runs |
| `SKIP_STALE_DAYS` | `30` | A supplier that returned "not found" is skipped for this many days |
| `MONITOR_ALL_ITEMS` | `1` | `1` = search every imported material; `0` = skip non-retail items (fuel, sensors, cranes, …) by a keyword list |

---

## Command-line tools

```bash
python cli/discover.py [--limit N] [--workers N] [--suppliers id1,id2]
```
Discovery: checks **every** supplier for **every** material, ignoring the "not found" cache, to build the availability matrix. (Also available as `POST /api/discover`; there is no UI button.)

```bash
python matching/search_label_converter.py
```
Fills the optional shorter search query (`items.search_label`) for long estimate names.

`cli/discover_search_url.py` and `scripts/probe*.py` are one-off helpers used while adding new supplier sites.

---

## Development

```bash
python -m pytest tests/ -v
```

The tests cover pure logic with no network: fuzzy matching, price parsing, query simplification and variations, result sorting and manual overrides, batch controls, the run session cache, Excel medal ranking, and the export path-traversal guard. `tests/test_price_parsing.py` imports the scraping base and needs `scrapling` installed.

`.github/workflows/notify-release-mail.yml`: every push to `main` creates a GitHub Release (`v<run number>`) with a zip of the code and emails the download link (SMTP credentials and the recipient come from repository secrets/variables).

Before changing behaviour, read [`OVERVIEW.md`](OVERVIEW.md) — it lists conventions, thread-safety notes and known issues.

---

## Troubleshooting

**"Python was not found"** — Python isn't installed or "Add python.exe to PATH" wasn't ticked. Reinstall Python and run `START.bat` again.

**The first launch takes long** — normal: dependencies and the scraping browser are downloaded once (5–10 minutes). Press «Детальніше ▾» to see the log.

**Dependencies failed to install** — check the internet connection and run `START.bat` again; if it persists, delete the `.venv` folder and retry.

**http://localhost:8765 doesn't open** — wait 10–15 seconds after the window reports the app is starting, then press «Відкрити у браузері». The PriceScout window must stay open. If the port is busy, set another `PORT` in `.env`.

**Prices are not found at all** — delete `.venv\.setup_done` and run `START.bat`; the components (including the browser) are reinstalled.

**A run seems stuck** — if the log hasn't changed for several minutes, press «◼ Зупинити»; if that doesn't help, close the PriceScout window and start `START.bat` again.
