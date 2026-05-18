"""Scrape routes: /api/scrape, /api/scrape/batch, /api/stop, /api/status, /api/results"""

from flask import Blueprint, jsonify, request
from core import state, normalize_label
from runner import (
    start_scrape,
    start_batch,
    MAX_PARALLEL_ITEMS,
    DEFAULT_PARALLEL_ITEMS,
    SKIP_STALE_DAYS,
    _clamp_parallel,
    _apply_limit,
)
from item_db import load_items, add_item, set_result_override
from runner import _apply_overrides, _sort_results
from suppliers import SUPPLIERS as SUPPLIERS_CONFIG

bp = Blueprint("scrape", __name__)


@bp.route("/api/scrape", methods=["POST"])
def scrape():
    if state["running"]:
        return jsonify({"error": "Вже виконується"}), 400
    data    = request.json
    item_id = data.get("item_id", "").strip()
    label   = normalize_label(data.get("label", "").strip())
    if not item_id and label:
        existing = next((i for i in load_items() if i["label"] == label), None)
        item_id  = existing["id"] if existing else add_item(label)["id"]
    if not item_id:
        return jsonify({"error": "Вкажіть матеріал"}), 400
    active_ids = [s["id"] for s in data.get("suppliers", []) if s.get("enabled")]
    if not active_ids:
        return jsonify({"error": "Жоден постачальник не обраний"}), 400
    start_scrape(item_id, active_ids)
    return jsonify({"status": "started", "item_id": item_id})


@bp.route("/api/scrape/batch", methods=["POST"])
def scrape_batch():
    if state["running"]:
        return jsonify({"error": "Вже виконується"}), 400
    data       = request.json
    item_ids   = data.get("item_ids", [])
    active_ids = [s["id"] for s in data.get("suppliers", []) if s.get("enabled")]
    if not item_ids:
        return jsonify({"error": "Черга порожня"}), 400
    if not active_ids:
        return jsonify({"error": "Жоден постачальник не обраний"}), 400

    # Optional knobs: number of items to scrape (всі / N) and how many
    # to fetch concurrently (1..MAX_PARALLEL_ITEMS).
    parallel_items = _clamp_parallel(data.get("parallel_items"))
    effective_ids  = _apply_limit(item_ids, data.get("limit"))

    start_batch(item_ids, active_ids, parallel_items=parallel_items, limit=data.get("limit"))
    return jsonify({
        "status":          "started",
        "item_count":      len(effective_ids),
        "requested_count": len(item_ids),
        "supplier_count":  len(active_ids),
        "parallel_items":  parallel_items,
        "max_parallel":    MAX_PARALLEL_ITEMS,
    })


@bp.route("/api/stop", methods=["POST"])
def stop():
    if state["running"]:
        state["stop_requested"] = True
    return jsonify({"status": "stopping"})


@bp.route("/api/status")
def status():
    full_log = state["log"]
    # Incremental log fetch: callers tracking their own position pass
    # ?log_offset=N and get every line from index N onward. Without the
    # param we keep the legacy behaviour (last 100 lines) for the
    # single-run poller, which re-renders the whole window each tick.
    try:
        log_offset = int(request.args.get("log_offset", -1))
    except (TypeError, ValueError):
        log_offset = -1
    log_slice = full_log[log_offset:] if log_offset >= 0 else full_log[-100:]
    return jsonify({
        "running":        state["running"],
        "log":            log_slice,
        "log_total":      len(full_log),
        "count":          len(state["results"]),
        "last_run":       state["last_run"],
        "error":          state["error"],
        "label":          state["label"],
        "parallel_items": state.get("parallel_items"),
        "limit":          state.get("limit"),
        "total_items":    state.get("total_items"),
    })


@bp.route("/api/discover", methods=["POST"])
def discover():
    """Full discovery run: checks ALL suppliers for ALL items, ignoring
    SKIP_STALE_DAYS and session cache. Run once to build the availability
    matrix; subsequent normal scrapes then skip absent suppliers automatically."""
    if state["running"]:
        return jsonify({"error": "Вже виконується"}), 400
    data       = request.json
    item_ids   = data.get("item_ids", [])
    active_ids = [s["id"] for s in data.get("suppliers", []) if s.get("enabled")]
    if not item_ids:
        return jsonify({"error": "Черга порожня"}), 400
    if not active_ids:
        return jsonify({"error": "Жоден постачальник не обраний"}), 400

    start_batch(item_ids, active_ids, parallel_items=1, discovery_mode=True)
    return jsonify({
        "status":         "started",
        "mode":           "discovery",
        "item_count":     len(item_ids),
        "supplier_count": len(active_ids),
        "note":           "Запущено повний discovery: всі постачальники будуть перевірені для кожного товару",
    })


@bp.route("/api/config")
def config():
    """Expose static parallelism limits so the UI can build its controls."""
    return jsonify({
        "max_parallel_items":     MAX_PARALLEL_ITEMS,
        "default_parallel_items": DEFAULT_PARALLEL_ITEMS,
        "skip_stale_days":        SKIP_STALE_DAYS,
    })


@bp.route("/api/results")
def results():
    return jsonify(state["results"])


@bp.route("/api/results/<item_id>/<supplier_id>", methods=["PATCH"])
def patch_result(item_id, supplier_id):
    """Persist a hand-edit to a scraped result.

    Body (all keys optional):
      - manual_price: number → override the parsed price.
                      Send null to clear.
      - comment:      string → free-form note carried into Excel.
                      Send "" / null to clear.

    After persisting we re-apply overrides over the current run's results
    so the Results tab updates without a re-scrape.
    """
    data = request.json or {}
    kwargs = {}
    if "manual_price" in data:
        raw = data["manual_price"]
        if raw in (None, "", "null"):
            kwargs["manual_price"] = None
        else:
            try:
                kwargs["manual_price"] = float(str(raw).replace(",", "."))
            except (TypeError, ValueError):
                return jsonify({"error": "Невалідна ціна"}), 400
    if "comment" in data:
        c = data["comment"]
        kwargs["comment"] = None if c in (None, "") else str(c).strip()

    if not kwargs:
        return jsonify({"error": "Нічого оновлювати"}), 400

    set_result_override(item_id, supplier_id, **kwargs)

    # Re-splice overrides into the in-memory run so the UI sees the change
    # without a full re-scrape. Strip our own splice fields first so we
    # don't double-stack `original_price` on repeat edits.
    refreshed = []
    for r in state["results"]:
        clean = {k: v for k, v in r.items()
                 if k not in ("manual_price", "comment", "original_price")}
        # Restore original price before re-applying overrides.
        if r.get("original_price") is not None:
            clean["price"] = r["original_price"]
        refreshed.append(clean)
    state["results"] = _sort_results(_apply_overrides(refreshed))

    updated = next(
        (r for r in state["results"]
         if r.get("item_id") == item_id and r.get("supplier_id") == supplier_id),
        None,
    )
    return jsonify({"status": "ok", "result": updated})
