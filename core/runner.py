"""
PriceScout — scrape runner on Scrapling.

Replaces the old Playwright + Claude pipeline with synchronous per-site
scrapers that run on Scrapling. Items are fanned out through a
ThreadPoolExecutor so the Flask UI keeps responding while a batch runs.

Public entrypoints (called from routes/scrape.py):
  - start_scrape(item_id, active_supplier_ids)
  - start_batch(item_ids, active_supplier_ids, parallel_items=None, limit=None)

start_batch accepts two optional knobs exposed to the UI:
  - parallel_items: how many items to scrape concurrently (1..MAX_PARALLEL_ITEMS).
    Defaults to MAX_PARALLEL_ITEMS. Lets the user pick a sequential (1) or a
    light async mode (2-3) without having to restart the app.
  - limit: cap on how many items are pulled from the head of the queue.
    Defaults to no limit (all items). Used by the UI to scrape the first N
    items instead of the whole queue.

State contracts preserved:
  - core.state keys: running, stop_requested, log, results, last_run,
    error, label, parallel_items, limit, total_items
  - item_states[item_id]: {log, results, done, error}
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from core.core import state, log, save_last_run
from core.suppliers import SUPPLIERS as SUPPLIERS_CONFIG
from core.item_db import get_item, update_supplier_entry, get_result_overrides
from matching.category_routing import get_suppliers_for_item

# How many days before a "not found" result is re-checked.
# Suppliers that returned not-found recently are skipped to save time.
# 30 days: after a full discovery run results stay valid for a month.
SKIP_STALE_DAYS = int(os.getenv("SKIP_STALE_DAYS", "30"))

# Outer fan-out (how many items are scraped in parallel).
# The old default of 5 was tuned for a Playwright-heavy pipeline where every
# request meant a browser warm-up. After switching most suppliers to the fast
# HTTP fetcher the bottleneck moved to remote latency, so a bigger pool helps.
MAX_PARALLEL_ITEMS = int(os.getenv("MAX_PARALLEL_ITEMS", "10"))
# Default fan-out when the UI doesn't pass an explicit value.
DEFAULT_PARALLEL_ITEMS = min(MAX_PARALLEL_ITEMS, 5)

# Inner fan-out: parallel supplier fetches per item. With 13 suppliers per
# item and fast-mode dominating the mix, 8 lets one item drain through its
# routed list in roughly one network RTT instead of two.
# Discovery mode runs items sequentially so it can spend the budget on inner
# workers instead.
MAX_INNER_WORKERS = int(os.getenv("MAX_INNER_WORKERS", "8"))
MAX_INNER_WORKERS_DISCOVERY = int(os.getenv("MAX_INNER_WORKERS_DISCOVERY", "10"))


def clamp_parallel(value, fallback: int = DEFAULT_PARALLEL_ITEMS) -> int:
    """Clamp a user-supplied parallelism setting into [1, MAX_PARALLEL_ITEMS].

    Invalid / missing values fall back to ``fallback``.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return max(1, min(MAX_PARALLEL_ITEMS, fallback))
    if n <= 0:
        return max(1, min(MAX_PARALLEL_ITEMS, fallback))
    return min(MAX_PARALLEL_ITEMS, n)


# Ukrainian-friendly sort key: lowercase, fold ґ→г, і→и, ї→и, є→е so the
# alphabetic order matches what a human reader expects ("Анкер" < "Бетон"
# < "Грунт", with ґ tied with г instead of landing in the codepoint hole
# between Я and а). Used to group the run's results by material.
_UA_SORT_FOLD = str.maketrans({
    "ґ": "г", "Ґ": "г", "і": "и", "І": "и",
    "ї": "и", "Ї": "и", "є": "е", "Є": "е",
})


def _ua_sort_key(text) -> str:
    if not text:
        return ""
    return str(text).lower().translate(_UA_SORT_FOLD)


def apply_overrides(results: list[dict]) -> list[dict]:
    """Splice manual_price / comment from supplier_entries into a fresh
    result list. Each row gets:

      - `comment`       — the free-form note the user attached.
      - `manual_price`  — the corrected price (kept separately for the UI
                          so it can flag "manually adjusted").
      - `price`         — replaced with manual_price when one exists,
                          original kept in `original_price` for reference.
      - `total_price`   — recomputed against the effective price × qty.
    """
    if not results:
        return results
    item_ids = list({r.get("item_id") for r in results if r.get("item_id")})
    overrides = get_result_overrides(item_ids) if item_ids else {}
    if not overrides and not any(r.get("comment") or r.get("manual_price") for r in results):
        return results
    for r in results:
        key = (r.get("item_id"), r.get("supplier_id"))
        ov = overrides.get(key)
        if not ov:
            continue
        if ov.get("comment") is not None:
            r["comment"] = ov["comment"]
        mp = ov.get("manual_price")
        if mp is not None:
            r["original_price"] = r.get("price")
            r["manual_price"] = mp
            r["price"] = mp
            qty = r.get("qty")
            try:
                if qty is not None:
                    r["total_price"] = round(float(qty) * float(mp), 2)
            except (TypeError, ValueError):
                pass
    return results


def sort_results(results: list[dict]) -> list[dict]:
    """Order a flat result list as `item1: [all suppliers], item2: [all], …`.

    Primary key — `item_label` (the material name from the кошторис) so the
    Results tab and Excel exports show each material with its suppliers
    grouped together. Secondary key — `supplier` so the rows under a given
    material are stable across runs (matters when the user compares two
    Excels side-by-side).
    """
    return sorted(
        results,
        key=lambda r: (_ua_sort_key(r.get("item_label")), _ua_sort_key(r.get("supplier"))),
    )


def apply_limit(item_ids: list[str], limit) -> list[str]:
    """Return the first ``limit`` ids, or the full list when limit is
    falsy / out of range."""
    if not item_ids:
        return []
    try:
        n = int(limit) if limit is not None else 0
    except (TypeError, ValueError):
        n = 0
    if n <= 0 or n >= len(item_ids):
        return list(item_ids)
    return list(item_ids[:n])


# Per-item state for parallel tracking (same shape as before)
item_states: dict[str, dict] = {}

# Session-level scrape cache: (item_id, frozenset(supplier_ids)) -> list of result dicts.
# Prevents re-scraping the same item within a single app run.
# Key includes the supplier set so that changing the active suppliers between
# batches doesn't return stale results from a previous, different fan-out.
_session_cache: dict[tuple[str, frozenset], list[dict]] = {}


def _scrape_one_supplier(supplier, label, item, ilog):
    """Call a single supplier's scraper synchronously. Returns
    (supplier, result, found_url, saved_entry, saved_url)."""
    sup_id = supplier["id"]
    saved_entry = item.get("suppliers", {}).get(sup_id, {})
    saved_url = saved_entry.get("url") if saved_entry.get("found") else None

    ilog(f"── {supplier['name']} {'(збережене)' if saved_url else '(пошук)'}")

    try:
        result, found_url = supplier["scrape"](
            supplier, label, ilog, saved_url=saved_url,
        )
    except Exception as exc:
        ilog(f"  → ПОМИЛКА ({supplier['name']}): {exc}")
        return supplier, None, None, saved_entry, saved_url

    return supplier, result, found_url, saved_entry, saved_url


def _missing_stub(item_id: str, display_label: str, item: dict) -> dict:
    """Placeholder row for the 'ціна 0, якщо не знайдено' option
    (fill_missing): keeps EVERY кошторис position present in Results/Excel
    with price 0 and an empty URL, so the customer can align exported
    columns with the original file row-by-row."""
    return {
        "name":          "не знайдено",
        "price":         0,
        "currency":      "UAH",
        "unit":          None,
        "brand":         None,
        "sku":           None,
        "specs":         None,
        "supplier":      "—",
        "url":           "",
        "date_scraped":  datetime.now().strftime("%Y-%m-%d"),
        "item_id":       item_id,
        "supplier_id":   None,
        "item_label":    display_label,
        "qty":           item.get("qty"),
        "unit_estimate": item.get("unit"),
        "total_price":   0,
    }


def _run_single_item(item_id: str, active_suppliers: list, discovery_mode: bool = False,
                     qty_override: float | None = None,
                     single_price: bool = False, best_price: bool = False,
                     supplier_order: list | None = None,
                     fill_missing: bool = False) -> None:
    """Scrape one item across its routed suppliers. Results land in
    item_states[item_id] and in core.state.

    discovery_mode=True: skip cache and smart-skip, force all suppliers.
    qty_override: per-project quantity (project runs) — replaces the shared
    item qty so totals match the project's кошторис.

    Search-mode options (from the batch toolbar checkboxes):
      single_price + supplier_order  — probe suppliers SEQUENTIALLY in the
        user's priority order and stop at the first found price.
      single_price + best_price     — query all routed suppliers as usual,
        then keep only the cheapest hit in the results (the DB still records
        every supplier's price for availability/history).
      fill_missing                  — items that end with no results get a
        stub row (price 0, empty URL) so Excel has a row per position.
    """
    # Cooperative stop: once the user hits stop, every item still queued
    # in the pool must become an instant no-op. Without this the batch
    # keeps churning through the whole queue — a full scrape pass per
    # item — in the background long after "stop" was pressed.
    if state.get("stop_requested"):
        return

    item = get_item(item_id)
    if not item:
        return
    if qty_override is not None:
        item["qty"] = qty_override

    # `search_label` is the query we feed to suppliers (a shortened version
    # of the кошторис row, e.g. "Ceresit CT 225"). `display_label` is what
    # the user typed in the кошторис and what they expect to see in the
    # Results tab / Excel exports — keep them distinct.
    display_label = item["label"]
    label = item.get("search_label") or display_label
    istate = item_states[item_id]
    cache_key = (item_id, frozenset(s["id"] for s in active_suppliers))

    def ilog(msg: str) -> None:
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        istate["log"].append(entry)
        state["log"].append(entry)

    # ── Session cache: skip re-scraping if already done this session ──
    # Disabled in discovery mode so all suppliers are always checked.
    # Cache key includes the supplier set: if the user changes which suppliers
    # are active, we must NOT return results scraped under a different set.
    if not discovery_mode and cache_key in _session_cache:
        cached = _session_cache[cache_key]
        ilog(f"Матеріал: {label} (кеш сесії, {len(cached)} результатів)")
        istate["results"] = list(cached)
        istate["done"] = True
        log(f"⚡ {label} — з кешу ({len(cached)} рез.)")
        return

    ilog(f"Матеріал: {label}" + (" [discovery]" if discovery_mode else ""))

    active_ids = [s["id"] for s in active_suppliers]
    routed_ids = get_suppliers_for_item(item, active_ids)
    routed_suppliers = [s for s in active_suppliers if s["id"] in routed_ids]

    # Smart skip: if a supplier returned not-found recently, skip it
    # to save time. Suppliers that previously found the item are always
    # re-checked (price may have changed).
    # Disabled in discovery mode — we want a full fresh picture.
    if not discovery_mode:
        sups_data = item.get("suppliers", {})
        skipped = []
        checked = []
        for s in routed_suppliers:
            entry = sups_data.get(s["id"])
            if entry and not entry.get("found") and entry.get("last_checked"):
                try:
                    last = datetime.strptime(entry["last_checked"], "%Y-%m-%d %H:%M")
                    age = (datetime.now() - last).days
                    if age < SKIP_STALE_DAYS:
                        skipped.append(s)
                        continue
                except (ValueError, TypeError):
                    pass
            checked.append(s)
        if skipped:
            ilog(f"  → Пропущено {len(skipped)} постачальників (не знайдено <{SKIP_STALE_DAYS}д тому): "
                 + ", ".join(s["name"] for s in skipped))
        routed_suppliers = checked

    if not item.get("monitorable", True):
        ilog(f"  → Пропущено (не моніториться): {label[:60]}")
        if fill_missing:
            istate["results"].append(_missing_stub(item_id, display_label, item))
        if not discovery_mode:
            _session_cache[cache_key] = list(istate["results"])
        istate["done"] = True
        return

    if not routed_suppliers:
        ilog(f"  → Пропущено (категорія не підтримується постачальниками): {item.get('category', '—')}")
        if fill_missing:
            istate["results"].append(_missing_stub(item_id, display_label, item))
        if not discovery_mode:
            _session_cache[cache_key] = list(istate["results"])
        istate["done"] = True
        return

    ilog(f"Запускаємо {len(routed_suppliers)} постачальників… (з {len(active_suppliers)} активних)")

    # In discovery mode use more inner workers since items run sequentially,
    # keeping total concurrent browser count manageable.
    max_workers_cap = MAX_INNER_WORKERS_DISCOVERY if discovery_mode else MAX_INNER_WORKERS
    inner_workers = min(len(routed_suppliers), max_workers_cap)
    found_count = 0

    # Re-check stop before launching browser fetches: an item picked up
    # just as stop was pressed shouldn't kick off a fresh scrape wave.
    if state.get("stop_requested"):
        ilog("  → зупинено")
        istate["done"] = True
        return

    def _record(supplier: dict, result: dict, found_url) -> None:
        """Enrich a scraper hit and persist it (shared by both modes)."""
        nonlocal found_count
        found_count += 1
        result["item_id"] = item_id
        result["supplier_id"] = supplier["id"]
        # Display the original кошторис label, not the shortened
        # `search_label` we sent to the supplier — the user wrote
        # the long name and expects to see it in the results.
        result["item_label"] = display_label
        qty = item.get("qty")
        unit_est = item.get("unit")
        price = result.get("price")
        total = None
        try:
            if qty is not None and price is not None:
                total = round(float(qty) * float(price), 2)
        except (TypeError, ValueError):
            total = None
        result["qty"] = qty
        result["unit_estimate"] = unit_est
        result["total_price"] = total

        istate["results"].append(result)
        update_supplier_entry(
            item_id, supplier["id"], found_url, True, result.get("price"),
        )
        if total is not None:
            ilog(
                f"  ✓ {supplier['name']}: {result['name'][:50]} — "
                f"{price} ₴/{unit_est or 'од'} × {qty} = {total} ₴"
            )
        else:
            ilog(f"  ✓ {supplier['name']}: {result['name'][:50]} — {price} ₴")

    if single_price and not best_price:
        # ── One price, user-defined priority: probe SEQUENTIALLY and stop
        # at the first supplier that returns a price.
        if supplier_order:
            order_index = {sid: n for n, sid in enumerate(supplier_order)}
            routed_suppliers = sorted(
                routed_suppliers,
                key=lambda s: order_index.get(s["id"], len(order_index)),
            )
        ilog("  Режим: одна ціна | порядок: " + " → ".join(s["name"] for s in routed_suppliers))
        for supplier in routed_suppliers:
            if state.get("stop_requested"):
                ilog("  → зупинено")
                break
            _sup, result, found_url, saved_entry, _saved = _scrape_one_supplier(
                supplier, label, item, ilog,
            )
            if result:
                _record(supplier, result, found_url)
                break
            update_supplier_entry(
                item_id, supplier["id"], saved_entry.get("url"), False, None,
            )
            ilog(f"  ✗ {supplier['name']}: не знайдено")
    else:
        with ThreadPoolExecutor(max_workers=inner_workers) as pool:
            futures = [
                pool.submit(_scrape_one_supplier, supplier, label, item, ilog)
                for supplier in routed_suppliers
            ]
            for fut in as_completed(futures):
                if state.get("stop_requested"):
                    # Cooperative stop — attempt to cancel pending futures and
                    # let any in-flight ones drain on their own.
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    break
                try:
                    supplier, result, found_url, saved_entry, saved_url = fut.result()
                except Exception as exc:
                    ilog(f"  → внутрішня помилка: {exc}")
                    continue

                if result:
                    _record(supplier, result, found_url)
                else:
                    update_supplier_entry(
                        item_id, supplier["id"], saved_entry.get("url"), False, None,
                    )
                    ilog(f"  ✗ {supplier['name']}: не знайдено")

        # ── One price, cheapest wins: all suppliers were queried (and the
        # DB keeps every price), but the Results/Excel row set is trimmed
        # to the single cheapest hit.
        if single_price and best_price and len(istate["results"]) > 1:
            best = min(
                istate["results"],
                key=lambda r: (r.get("price") is None, r.get("price") or 0),
            )
            ilog(
                f"  → найменша ціна: {best.get('price')} ₴ ({best.get('supplier')}), "
                f"інші {len(istate['results']) - 1} відкинуто"
            )
            istate["results"] = [best]
            found_count = 1

    # Stub row for "ціна 0, якщо не знайдено" — only when the item actually
    # finished all its attempts (not when the run was stopped mid-way).
    if fill_missing and not istate["results"] and not state.get("stop_requested"):
        istate["results"].append(_missing_stub(item_id, display_label, item))
        ilog("  → ціну не знайдено, додано рядок з ціною 0")

    ilog(f"Готово. {found_count}/{len(routed_suppliers)} постачальників.")
    # Don't populate the cache in discovery mode: subsequent normal runs
    # must hit the DB-backed smart-skip path, not a session snapshot.
    if not discovery_mode:
        _session_cache[cache_key] = list(istate["results"])
    istate["done"] = True
    log(f"✓ {label} — {found_count}/{len(routed_suppliers)}")


def _run_batch(
    item_ids: list[str],
    active_supplier_ids: list[str],
    parallel_items: int | None = None,
    limit: int | None = None,
    discovery_mode: bool = False,
    project_id: str | None = None,
    run_label: str | None = None,
    single_price: bool = False,
    best_price: bool = False,
    supplier_order: list | None = None,
    fill_missing: bool = False,
) -> None:
    """Main batch orchestrator. Runs in a background thread.

    ``parallel_items`` and ``limit`` come from the UI and are validated by
    :func:`clamp_parallel` / :func:`apply_limit` before use.

    ``discovery_mode=True`` forces all suppliers to be checked for every item,
    ignoring SKIP_STALE_DAYS and the session cache. Use once to build the
    full availability matrix; subsequent normal runs then skip known-absent
    suppliers automatically.
    """
    # Clear session cache at the start of every batch so a new run always
    # reflects the current state of the DB rather than stale in-memory results.
    _session_cache.clear()

    total_requested = len(item_ids)
    item_ids = apply_limit(item_ids, limit)
    # Discovery mode runs items sequentially to keep concurrent browser count low.
    if discovery_mode and parallel_items is None:
        workers = 1
    else:
        workers = clamp_parallel(parallel_items)
    state["running"] = True
    state["stop_requested"] = False
    state["log"] = []
    state["error"] = None
    state["batch_started_at"] = datetime.now().isoformat()
    state["parallel_items"] = workers
    state["limit"] = len(item_ids)
    state["total_items"] = total_requested
    state["project_id"] = project_id
    # Expose the run's options so a page reload can restore + lock the
    # toolbar checkboxes while the run is still active.
    state["run_options"] = {
        "single_price":   single_price,
        "best_price":     best_price,
        "fill_missing":   fill_missing,
        "supplier_order": supplier_order or [],
    }
    base_label = run_label or ("Discovery" if discovery_mode else "Черга")
    if total_requested and len(item_ids) < total_requested:
        state["label"] = f"{base_label} ({len(item_ids)} з {total_requested} матеріалів)"
    else:
        state["label"] = f"{base_label} ({len(item_ids)} матеріалів)"

    # Project runs: per-project quantities (from project_items links) replace
    # the shared item qty so totals match THIS project's кошторис.
    qty_overrides: dict[str, float] = {}
    if project_id:
        try:
            from core.item_db import get_project_items
            for pi in get_project_items(project_id):
                if pi.get("qty") is not None:
                    qty_overrides[pi["id"]] = pi["qty"]
        except Exception as exc:
            log(f"Не вдалося завантажити кількості проекту: {exc}")

    item_states.clear()
    item_states.update({
        iid: {"log": [], "results": [], "done": False, "error": None}
        for iid in item_ids
    })

    active_suppliers = [
        s for s in SUPPLIERS_CONFIG
        if s["id"] in active_supplier_ids and s.get("enabled", True)
    ]

    log(
        f"{'[DISCOVERY] ' if discovery_mode else ''}Черга: {len(item_ids)} матеріалів"
        + (f" (з {total_requested})" if total_requested != len(item_ids) else "")
        + f" | {len(active_suppliers)} постачальників | паралельно: {workers}"
        + (f" | SKIP_STALE відключено" if discovery_mode else f" | SKIP_STALE: {SKIP_STALE_DAYS}д")
        + (" | режим: одна ціна (найменша)" if single_price and best_price else "")
        + (" | режим: одна ціна (за порядком)" if single_price and not best_price else "")
        + (" | ціна 0 для не знайдених" if fill_missing else "")
    )

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for iid in item_ids:
                if state.get("stop_requested"):
                    break
                futures.append(pool.submit(
                    _run_single_item, iid, active_suppliers, discovery_mode,
                    qty_overrides.get(iid),
                    single_price, best_price, supplier_order, fill_missing,
                ))
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as exc:
                    log(f"Помилка обробки матеріалу: {exc}")

        # The Results tab and Excel export reflect THIS run — the last
        # monitoring run — not a lifetime accumulation. Per-item history
        # still lives in the DB (supplier_entries / price_history).
        # Results are collected after the pool has drained, so a manual
        # stop still captures whatever was found before the queue was
        # cut short.
        #
        # Order: group by item (alphabetic by label, UA letters folded onto
        # their Russian equivalents so "Анкер" sorts before "Бетон" without
        # surprises from ґ/і/є codepoint positions), and inside each group
        # by supplier name. Without this, futures completion order would
        # interleave items unpredictably in the Results tab and Excel.
        run_results: list = []
        for iid in item_ids:
            run_results.extend(item_states.get(iid, {}).get("results", []))

        if project_id:
            # Project runs keep the imported file's order: item_ids already
            # follow project positions, so sort by that sequence (suppliers
            # alphabetical inside each item). Results tab + Excel then match
            # the кошторис row order.
            order = {iid: n for n, iid in enumerate(item_ids)}
            run_results = apply_overrides(run_results)
            run_results.sort(key=lambda r: (
                order.get(r.get("item_id"), len(order)),
                _ua_sort_key(r.get("supplier")),
            ))
            state["results"] = run_results
        else:
            state["results"] = sort_results(apply_overrides(run_results))
        state["last_run"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        stopped_note = " (зупинено)" if state.get("stop_requested") else ""
        log(f"Все готово{stopped_note}. {len(run_results)} цін по {len(item_ids)} матеріалах.")
        save_last_run(state["results"], state["label"], state["last_run"])
    except Exception as exc:
        state["error"] = str(exc)
        log(f"Критична помилка: {exc}")
    finally:
        state["running"] = False


# ── Public API (unchanged signatures) ─────────────────────────

def start_scrape(item_id: str, active_supplier_ids: list[str]) -> None:
    threading.Thread(
        target=_run_batch,
        args=([item_id], active_supplier_ids),
        kwargs={"parallel_items": 1},
        daemon=True,
    ).start()


def start_batch(
    item_ids: list[str],
    active_supplier_ids: list[str],
    parallel_items: int | None = None,
    limit: int | None = None,
    discovery_mode: bool = False,
    project_id: str | None = None,
    run_label: str | None = None,
    single_price: bool = False,
    best_price: bool = False,
    supplier_order: list | None = None,
    fill_missing: bool = False,
) -> None:
    threading.Thread(
        target=_run_batch,
        args=(item_ids, active_supplier_ids),
        kwargs={
            "parallel_items": parallel_items,
            "limit": limit,
            "discovery_mode": discovery_mode,
            "project_id": project_id,
            "run_label": run_label,
            "single_price": single_price,
            "best_price": best_price,
            "supplier_order": supplier_order,
            "fill_missing": fill_missing,
        },
        daemon=True,
    ).start()
