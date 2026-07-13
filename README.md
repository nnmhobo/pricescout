# PriceScout — Construction Materials Price Monitor

PriceScout automatically searches 13 Ukrainian building-supply websites simultaneously and brings all prices into one comparison table. Import your АВК-5 estimate, run the search — and get an Excel file with price comparisons in minutes.

---

## What It Does

- Imports material line items from АВК-5 estimates (`.xls`, `.xlsx`) in one click
- Searches each material across 13 suppliers in parallel
- Shows a comparison table with prices and direct links to products
- Highlights 🥇🥈🥉 the cheapest offers per material
- Uses quantities and units from the estimate to calculate total costs
- Exports results to Excel
- Lets you manually correct prices and add comments
- Maintains an availability matrix showing which suppliers carry which materials
- Groups materials by project and compares against estimate prices

**13 suppliers:** Епіцентр К, АРС, Будівельний Двір, КУБ, Вен Буд, Будпостач, М2, Віста, Мегатрейд СМ, Будія, ТеплоДiм, Prom.ua, OLX.

---

## Requirements

- Windows 10 or 11
- Python 3.10 or newer — free from [python.org/downloads](https://www.python.org/downloads/)
- Internet connection

---

## Installation & First Launch

**Step 1.** Install Python (if not already installed).

1. Go to [python.org/downloads](https://www.python.org/downloads/) and download the latest version.
2. Run the installer.
3. **Important:** tick **"Add python.exe to PATH"** on the first screen before clicking Install.

**Step 2.** Launch the app.

1. Open the PriceScout folder.
2. Double-click **`START.bat`**.
3. An installation window will open. The first launch takes **5–10 minutes** — the app downloads all required components automatically and shows the progress. Do not close the window.
4. When ready, your browser opens automatically at **http://localhost:8765**.

> **To stop the app:** press "Зупинити" in the PriceScout window, or simply close it.

Every launch after the first takes just a few seconds.

---

## Interface Overview

The navigation bar across the top has seven sections:

| Section | What it does |
|---|---|
| **Імпорт кошторису** (Import) | Load an АВК-5 estimate file to populate your materials list |
| **База матеріалів** (Materials) | Browse, search, and manage saved materials |
| **Моніторинг** (Monitoring) | Run price searches — single item or full batch |
| **Результати** (Results) | Prices found in the last search |
| **Наявність** (Availability) | Matrix showing which suppliers carry which materials |
| **Проєкти** (Projects) | Group materials by project, compare against estimate |
| **Експорти** (Exports) | Previously saved Excel files |

---

## Step-by-Step: From Estimate to Prices

### Step 1 — Import your estimate

1. Click **Імпорт кошторису** in the navigation bar.
2. Click **Обрати файл** and select your АВК-5 file (`.xls` or `.xlsx`).
3. Click **Завантажити та розпізнати** (Load and parse).
4. PriceScout extracts all construction materials automatically, filtering out labour costs, services, and items not sold in retail stores (fuel, sensors, industrial chemicals, etc.).
5. Review the list. The counters at the top show how many materials were found and how many are selected.
6. Untick anything you don't need, then click **Імпортувати вибране** (Import selected).

All imported materials are saved to the Materials database and persist between sessions.

---

### Step 2 — Select materials to search

1. Click **Моніторинг** in the navigation.
2. The **Черга** (Queue) tab shows your saved materials. Tick the ones you want to price-check.
3. Use the search box to quickly find a specific material.
4. **Обрати всі** / **Зняти всі** — select or deselect everything at once.

**Run size settings:**

- **К-сть товарів** — search all selected materials or just the first 5 / 10 / 20 / 50 (useful for a quick test).
- **Паралельно** — how many materials to search simultaneously. Higher = faster, but uses more bandwidth. Default is 5.

---

### Step 3 — Choose suppliers

The supplier list appears below the materials list on the **Черга** tab. All 13 suppliers are enabled by default. Untick any you want to skip.

> Prom.ua and OLX are marketplace aggregators with broad coverage but lower data quality — useful for hard-to-find items, but results may need manual review.

---

### Step 4 — Run the search

Click **▶ Запустити** (Run). A progress bar and live log appear immediately. Each material is checked across all selected suppliers in parallel.

**While the search is running:**
- The log stream shows each step in real time.
- The **X / N матеріалів** counter tracks overall progress.
- Reloading the page is safe — the search keeps running in the background and the UI reconnects automatically.

**To stop early:** click **◼ Зупинити** (Stop). In-flight supplier requests complete naturally — no data is lost. The button shows a loading indicator while draining.

---

### Step 5 — Review results

When the search finishes, PriceScout switches automatically to the **Результати** (Results) tab.

The results table shows:
- Material name
- Supplier name with a link to the product page
- Found price
- Total price (price × quantity from your estimate)

Results from the last run are saved to disk and reload after restarting the app.

**Editing a result:** click any price cell to enter a corrected price or add a comment. Edits are saved and carried into Excel exports.

**Sorting and filtering:** click any column header to sort. The filter fields at the top of the table narrow results by material or supplier.

---

### Step 6 — Export to Excel

Click **📥 Завантажити Excel** in the Results tab.

The Excel file includes:
- One row per supplier result, grouped by material
- 🥇🥈🥉 medals on the top-3 cheapest prices per material
- Estimate price and quantity columns (from the АВК-5 import)
- Manually corrected prices and comments
- Run date and total result count

All saved files appear in the **Експорти** section for re-download at any time.

---

## Single-Item Search

For a quick one-off search without going through the batch queue:

1. Go to **Моніторинг → Один матеріал** (Single item).
2. Type a material name (e.g. `Цегла М100`).
3. Select suppliers and click **▶ Шукати** (Search).
4. Results appear in the log below and are added to the Results tab when done.

---

## Availability Matrix

The **Наявність** (Availability) panel shows which supplier carries which material, built up from all past searches. Useful for deciding which suppliers to include when you know certain items are rare.

**Запустити Discovery** runs a full scan — checks every supplier for every item regardless of cache, rebuilding the availability matrix from scratch. Run it once after your first import; subsequent searches will automatically skip suppliers known not to carry a given item.

---

## Projects

The **Проєкти** (Projects) panel lets you group materials into named projects and compare found prices against estimate prices.

1. Click **+ Новий проєкт** and give it a name.
2. Open the project and add materials to it.
3. The summary view shows total cost at market prices vs. total estimate cost.
4. Export the comparison to Excel with **📥 Експорт**.

---

## Troubleshooting

**"Python not found"**
Python is not installed or the "Add python.exe to PATH" box was not ticked. Reinstall Python per Step 1 and run START.bat again.

**First launch takes a very long time**
Normal — downloading components and a browser engine takes 5–10 minutes depending on your internet speed. Wait it out; don't close the window.

**"Could not install dependencies"**
Check your internet connection and run START.bat again. If the problem persists, delete the `.venv` folder inside the PriceScout folder and try again.

**http://localhost:8765 doesn't open**
Wait 10–15 seconds after the window says the app is starting, then press "Відкрити у браузері" (or open the address manually). Make sure the PriceScout window is still open.

**Prices not found / search not working**
Delete the file `.venv\.setup_done` inside the PriceScout folder and run START.bat — this forces all scraping components to reinstall cleanly.

**The search appears stuck**
If the log stops updating for more than 5 minutes, close the PriceScout window, restart START.bat, and the UI will reconnect and confirm the run has ended.

---

## Advanced Settings

Create a `.env` file in the PriceScout folder to override defaults:

```
PORT=8765                    # Web server port
MAX_PARALLEL_ITEMS=10        # Maximum items searched concurrently
MAX_INNER_WORKERS=8          # Parallel supplier requests per item
MAX_INNER_WORKERS_DISCOVERY=10
SKIP_STALE_DAYS=30           # Days before "not found" results are re-checked
```

Changes take effect after restarting START.bat.
