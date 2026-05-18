"""Export routes: /api/export/excel, /api/export/price-matrix, /api/exports"""

import io
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from flask import Blueprint, jsonify, request, send_file

from core import state, EXPORTS_DIR, ensure_exports_dir

bp = Blueprint("exports", __name__)

COLUMN_ORDER = ["item_label",
                "name", "price", "currency", "unit",
                "qty", "unit_estimate", "total_price",
                "brand", "sku",
                "specs", "supplier", "url", "date_scraped"]

COLUMN_NAMES = {
    "item_label":    "Матеріал кошторису",
    "name":          "Назва товару",
    "price":         "Ціна за од.",
    "currency":      "Валюта",
    "unit":          "Од.",
    "qty":           "К-сть (кошторис)",
    "unit_estimate": "Од. (кошторис)",
    "total_price":   "Загальна ціна",
    "brand":         "Бренд",
    "sku":           "Артикул",
    "specs":         "Характеристики",
    "supplier":      "Постачальник",
    "url":           "Посилання",
    "date_scraped":  "Дата",
}


def _build_excel(results: list, label: str) -> tuple[bytes, str]:
    df = pd.DataFrame(results)
    if "specs" in df.columns:
        df["specs"] = df["specs"].apply(
            lambda x: ", ".join(f"{k}: {v}" for k, v in x.items())
            if isinstance(x, dict) else ""
        )
    df = df[[c for c in COLUMN_ORDER if c in df.columns]]
    df.rename(columns=COLUMN_NAMES, inplace=True)

    safe_lbl = re.sub(r'[^\w\-]', '_', label)[:40]
    filename  = f"{safe_lbl}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Ціни")
        ws = writer.sheets["Ціни"]
        for col in ws.columns:
            w = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(w + 4, 60)
        from openpyxl.styles import Font, PatternFill, Alignment
        fill = PatternFill("solid", fgColor="141820")
        font = Font(bold=True, color="FFFFFF", size=11)
        for cell in ws[1]:
            cell.fill      = fill
            cell.font      = font
            cell.alignment = Alignment(horizontal="center")
    return output.getvalue(), filename


@bp.route("/api/export/excel")
def export_excel():
    if not state["results"]:
        return jsonify({"error": "Немає даних для експорту"}), 400
    excel_bytes, filename = _build_excel(state["results"], state.get("label", "prices"))
    ensure_exports_dir()
    (EXPORTS_DIR / filename).write_bytes(excel_bytes)
    return send_file(
        io.BytesIO(excel_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@bp.route("/api/exports")
def list_exports():
    ensure_exports_dir()
    files = sorted(EXPORTS_DIR.glob("*.xlsx"), reverse=True)
    return jsonify([{
        "filename": f.name,
        "size_kb":  round(f.stat().st_size / 1024, 1),
        "created":  datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
    } for f in files])


def _safe_export_path(filename: str):
    """Resolve a user-supplied filename inside EXPORTS_DIR. Returns None
    if the result would escape the directory (e.g. via '..')."""
    safe = re.sub(r'[^\w\-\.]', '', filename)
    if not safe or safe in (".", ".."):
        return None
    ensure_exports_dir()
    base = EXPORTS_DIR.resolve()
    candidate = (base / safe).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


@bp.route("/api/exports/<filename>")
def download_export(filename):
    path = _safe_export_path(filename)
    if path is None or not path.exists():
        return jsonify({"error": "Файл не знайдено"}), 404
    return send_file(path, as_attachment=True, download_name=path.name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/api/exports/<filename>", methods=["DELETE"])
def delete_export(filename):
    path = _safe_export_path(filename)
    if path is not None and path.exists():
        path.unlink()
    return jsonify({"status": "deleted"})


@bp.route("/api/export/price-matrix")
def export_price_matrix():
    """Export all monitored items × all suppliers as a price matrix Excel."""
    from item_db import get_availability_matrix
    from suppliers import SUPPLIERS
    from openpyxl.styles import Font, PatternFill, Alignment

    sup_ids   = [s["id"]   for s in SUPPLIERS if s.get("enabled", True)]
    sup_names = {s["id"]: s["name"] for s in SUPPLIERS}

    items = get_availability_matrix()
    if not items:
        return jsonify({"error": "Немає даних — спочатку запустіть discovery"}), 400

    rows = []
    for item in items:
        sups = item.get("suppliers", {})
        prices_found = []
        row = {
            "Матеріал":  item["label"],
            "Категорія": item.get("category") or "",
        }
        for sid in sup_ids:
            entry = sups.get(sid)
            price = None
            if entry and entry.get("found") and entry.get("last_price"):
                price = entry["last_price"]
                prices_found.append(price)
            row[sup_names.get(sid, sid)] = price

        row["Мін. ціна ₴"]  = min(prices_found) if prices_found else None
        row["Макс. ціна ₴"] = max(prices_found) if prices_found else None
        row["Знайдено (сайтів)"] = len(prices_found)
        if len(prices_found) >= 2:
            mn, mx = min(prices_found), max(prices_found)
            row["Розкид %"] = round((mx - mn) / mn * 100, 1) if mn > 0 else None
        else:
            row["Розкид %"] = None
        rows.append(row)

    df = pd.DataFrame(rows)
    # Sort by category then name
    df = df.sort_values(["Категорія", "Матеріал"])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Прайс-матриця")
        ws = writer.sheets["Прайс-матриця"]

        header_fill = PatternFill("solid", fgColor="141820")
        header_font = Font(bold=True, color="FFFFFF", size=10)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        # Auto column widths
        for col_cells in ws.columns:
            width = max(len(str(c.value or "")) for c in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = min(width + 3, 40)

        # Highlight min price cells (green) in supplier columns
        sup_col_indices = {}
        for cell in ws[1]:
            if cell.value in sup_names.values():
                sup_col_indices[cell.column] = True

        for row_num in range(2, ws.max_row + 1):
            # Find min value in supplier columns for this row
            sup_vals = []
            for col_idx in sup_col_indices:
                v = ws.cell(row=row_num, column=col_idx).value
                if isinstance(v, (int, float)):
                    sup_vals.append((v, col_idx))
            if sup_vals:
                min_val = min(v for v, _ in sup_vals)
                for v, col_idx in sup_vals:
                    cell = ws.cell(row=row_num, column=col_idx)
                    if v == min_val:
                        cell.font = Font(color="1a6b5a", bold=True)
                        cell.fill = PatternFill("solid", fgColor="e6f4f1")

    output.seek(0)
    ensure_exports_dir()
    filename = f"price_matrix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    (EXPORTS_DIR / filename).write_bytes(output.getvalue())
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )