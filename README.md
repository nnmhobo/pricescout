# PriceScout — Price Monitoring for Construction Materials

PriceScout searches 13 Ukrainian building-supply websites at once and shows you a side-by-side price comparison for any construction material. Import your estimate (кошторис) from АВК-5, click **Start**, and get a spreadsheet with the best prices in minutes.

---

## Requirements

- **Windows 10 or 11**
- **Python 3.10 or newer** — download free from [python.org/downloads](https://www.python.org/downloads/)
  - During installation, tick **"Add python.exe to PATH"** on the first screen
- Internet connection (for scraping supplier websites)

---

## Installation & First Launch

1. Put the `PriceScout` folder anywhere on your computer.
2. Double-click **`START.bat`**.
3. The first launch takes **5–10 minutes** — it installs all components automatically. A black console window will show progress. Do not close it.
4. When ready, your browser opens at **http://localhost:5000** automatically.
5. Every launch after the first takes just a few seconds.

> **To stop the app:** simply close the black console window.

---

## The Interface at a Glance

The navigation bar across the top has six panels:

| Panel | Ukrainian label | What it does |
|---|---|---|
| Import | Імпорт кошторису | Load an АВК-5 estimate file to populate your materials list |
| Materials | База матеріалів | Browse, search, and manage all saved materials |
| Monitoring | Моніторинг | Run price searches — single item or full batch |
| Results | Результати | View prices found in the last run |
| Availability | Наявність | Matrix showing which suppliers carry which materials |
| Projects | Проєкти | Group materials by project, compare totals to estimate prices |
| Exports | Експорти | Download previously saved Excel files |

---

## Step-by-Step: From Estimate to Prices

### Step 1 — Import your estimate

1. Click **Імпорт кошторису** in the top navigation.
2. Click **Обрати файл** and select your АВК-5 file (`.xls` or `.xlsx`).
3. Click **Завантажити та розпізнати**.
4. PriceScout extracts all construction materials, skipping labour costs, services, and items not sold in retail stores (fuel, sensors, industrial chemicals, etc.).
5. Review the list. The counts at the top show how many materials were found and how many are selected for import.
6. Untick anything you don't want, then click **Імпортувати вибране**.

All imported materials are saved in the **База матеріалів** (Materials database) and persist between sessions.

---

### Step 2 — Select materials for monitoring

1. Click **Моніторинг** in the navigation.
2. The **Черга** (Queue) tab shows your saved materials. Tick the ones you want to price-check.
3. Use the search box to find a specific material quickly.
4. Use **Обрати всі** / **Зняти всі** to select or clear the whole list in one click.

**Choosing how many to run at once:**

- **К-сть товарів** — run all selected materials, or just the first 5 / 10 / 20 / 50 (useful for a quick test).
- **Паралельно** — how many materials are searched at the same time. Higher numbers are faster but use more bandwidth. Default is 5.

---

### Step 3 — Choose suppliers

In the **Черга** tab, a supplier list appears below the materials. All 13 suppliers are ticked by default. Untick any you want to skip.

**The 13 suppliers:**
Епіцентр К, АРС, Будівельний Двір, КУБ, Вен Буд, Будпостач, М2, Віста, Мегатрейд СМ, Будія, ТеплоДiм, Prom.ua, OLX.

> Prom.ua and OLX are marketplaces with broad coverage but lower data quality — useful for hard-to-find items, but results may need review.

---

### Step 4 — Run the search

Click **▶ Запустити** (Run). The progress bar and live log appear immediately. Each material is checked against all selected suppliers in parallel.

**During the run:**
- The log stream shows each step in real time.
- The **X / N матеріалів** counter at the top tracks how many are done.
- If you reload the page, the run continues in the background and the UI reconnects automatically.

**To stop early:** click **◼ Зупинити**. In-flight requests to suppliers finish naturally before the run ends — no data is lost. The button shows a spinner while draining.

---

### Step 5 — Review results

When the run finishes, PriceScout switches automatically to the **Результати** tab.

The results table shows:
- Material name
- Supplier name with a link to the product page
- Price found
- Total price (price × quantity from your estimate)

Results from the last run are saved to disk (`data/last_run.json`) and reload on the next app start.

**Editing a result:** click the price cell to type a corrected price or add a comment. Your edit is saved and persists across runs.

**Sorting and filtering:** click any column header to sort. Use the filter boxes at the top to narrow by material or supplier.

---

### Step 6 — Export to Excel

Click **📥 Завантажити Excel** in the Results tab.

The Excel file includes:
- One row per supplier result, grouped by material
- 🥇🥈🥉 medal icons on the top-3 cheapest prices per material
- Estimate price and quantity columns (if imported from АВК-5)
- Manual price corrections and comments
- A footer with the run date and total count

All exported files are listed in the **Експорти** panel for re-download.

---

## Running a Single-Item Search

For a quick one-off search without going through the batch queue:

1. Go to **Моніторинг → Один матеріал**.
2. Type the material name in the search field (e.g. `Цегла М100`).
3. Choose suppliers and click **▶ Шукати**.
4. Results appear in the log below and are added to the Results tab when done.

---

## Availability Matrix

The **Наявність** panel shows which supplier carries which material, based on all past runs. Useful for deciding which suppliers to bother including when you know certain items are rare.

Click **Запустити Discovery** to run a full scan — this checks every supplier for every item regardless of cache, rebuilding the availability matrix from scratch. Run it once after your first import; normal runs then skip suppliers known not to carry a given item.

---

## Projects

The **Проєкти** panel lets you group materials into named projects (matching your АВК-5 estimates) and see a summary comparing scraped prices against estimate prices.

1. Click **+ Новий проєкт** and give it a name.
2. Click the project to open it, then add materials from your list.
3. The summary tab shows total scraped cost vs. total estimate cost.
4. Export the comparison as Excel with **📥 Експорт**.

---

## Troubleshooting

**"Python not found"**
Python is not installed or the "Add python.exe to PATH" box was not ticked. Reinstall Python from [python.org](https://www.python.org/downloads/), tick the box, and run START.bat again.

**First launch is taking very long**
Normal — downloading components and a browser engine takes 5–10 minutes depending on your connection. Just wait; don't close the window.

**"Could not install dependencies"**
Check your internet connection and run START.bat again. If the problem persists, delete the `.venv` folder and try again.

**http://localhost:5000 doesn't open**
Wait 10–15 seconds after the console says "Starting PriceScout…" then open the address manually in your browser. Make sure the console window is still open.

**Prices not found / search not working**
Delete `.venv\.setup_done` inside the PriceScout folder and run START.bat — this forces a clean reinstall of all scraping components.

**The run looks stuck**
The log stream continues as long as requests are in flight. If nothing changes for 5+ minutes, close the console window, restart START.bat, and the UI will reconnect to confirm the run has ended.

---

## Environment Variables (Advanced)

Create a `.env` file in the PriceScout folder to override defaults:

```
PORT=5000                  # Web server port
MAX_PARALLEL_ITEMS=10      # Max concurrent items in a batch
MAX_INNER_WORKERS=8        # Parallel supplier fetches per item
MAX_INNER_WORKERS_DISCOVERY=10
SKIP_STALE_DAYS=30         # Days before "not found" results expire
```

These only take effect after restarting START.bat.
