"""Item database routes: /api/items (CRUD), /api/availability,
/api/availability/coverage, /api/items/<item_id>/price-history"""

from flask import Blueprint, jsonify, request
from core.core import normalize_label
from core.item_db import (
    load_items, add_item, delete_item, get_item, update_item,
    get_supplier_coverage, get_availability_matrix, get_price_history,
)

bp = Blueprint("items", __name__)


@bp.route("/api/items", methods=["GET"])
def get_items():
    return jsonify(load_items())


@bp.route("/api/items", methods=["POST"])
def create_item():
    label = normalize_label(request.json.get("label", "").strip())
    if not label:
        return jsonify({"error": "Назва не може бути порожньою"}), 400
    try:
        return jsonify(add_item(label))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/api/items/<item_id>", methods=["GET"])
def get_single_item(item_id):
    item = get_item(item_id)
    if not item:
        return jsonify({"error": "Не знайдено"}), 404
    return jsonify(item)


@bp.route("/api/items/<item_id>", methods=["PATCH"])
def patch_item(item_id):
    data = request.json or {}
    update_item(item_id, data)
    return jsonify(get_item(item_id))


@bp.route("/api/items/<item_id>", methods=["DELETE"])
def remove_item(item_id):
    delete_item(item_id)
    return jsonify({"status": "deleted"})


@bp.route("/api/availability")
def availability():
    """Coverage matrix: which items are found on which suppliers."""
    return jsonify({
        "coverage":    get_supplier_coverage(),
        "items":       get_availability_matrix(),
    })


@bp.route("/api/availability/coverage")
def coverage():
    """Per-supplier coverage stats only (lightweight)."""
    return jsonify(get_supplier_coverage())


@bp.route("/api/items/<item_id>/price-history")
def price_history(item_id):
    """Return price history for one item, grouped by supplier."""
    supplier_id = request.args.get("supplier_id")
    rows = get_price_history(item_id, supplier_id or None)
    # Group by supplier for easier charting
    grouped: dict = {}
    for r in rows:
        grouped.setdefault(r["supplier_id"], []).append({
            "price": r["price"],
            "date":  r["checked_at"],
        })
    return jsonify(grouped)