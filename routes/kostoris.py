"""Кошторис import routes: /api/kostoris/parse, /api/kostoris/import"""

import json
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request
from core.item_db import add_item, batch_add_items
from parsers.kostoris_parser import parse as parse_kostoris

bp = Blueprint("kostoris", __name__)

LAST_IMPORT_FILE = Path("data/last_import.json")


def save_last_import(data: dict):
    try:
        LAST_IMPORT_FILE.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass


def load_last_import() -> dict | None:
    if LAST_IMPORT_FILE.exists():
        try:
            return json.loads(LAST_IMPORT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


@bp.route("/api/kostoris/last")
def kostoris_last():
    data = load_last_import()
    if data:
        return jsonify(data)
    return jsonify(None)


@bp.route("/api/kostoris/parse", methods=["POST"])
def kostoris_parse():
    if "file" not in request.files:
        return jsonify({"error": "Файл не завантажено"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Порожній файл"}), 400

    suffix = Path(f.filename).suffix.lower()
    if suffix not in (".xls", ".xlsx"):
        return jsonify({"error": f"Непідтримуваний формат '{suffix}'. Потрібен .xls або .xlsx з АВК-5."}), 400

    f.seek(0, 2); size = f.tell(); f.seek(0)
    if size < 1000:
        return jsonify({"error": "Файл занадто малий. Перевірте, чи це кошторис АВК-5."}), 400
    if size > 20 * 1024 * 1024:
        return jsonify({"error": "Файл занадто великий (>20MB)."}), 400

    tmp      = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(tmp.name)
    tmp.close()
    f.save(tmp_path)

    try:
        items = parse_kostoris(str(tmp_path))
        if not items:
            return jsonify({"error": "Позиції не знайдено. Перевірте, що це Підсумкова відомість ресурсів АВК-5."}), 400
        result = {
            "total":    len(items),
            "retail":   sum(1 for i in items if i["retail"]),
            "items":    items,
            "filename": f.filename,
        }
        save_last_import(result)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Помилка читання файлу: {e}. Спробуйте зберегти як .xlsx в Excel."}), 500
    finally:
        tmp_path.unlink(missing_ok=True)


@bp.route("/api/kostoris/import", methods=["POST"])
def kostoris_import():
    payload    = request.json
    project_id = (payload.get("project_id") or "").strip() or None
    raw        = payload.get("items") or [{"name": n} for n in payload.get("names", [])]
    if not raw:
        return jsonify({"error": "Немає вибраних позицій"}), 400

    entries = [
        {
            "label":               (e.get("name") or "").strip(),
            "avk_code":            (e.get("code") or "").strip() or None,
            "category":            (e.get("category") or "").strip() or None,
            "source":              "kostoris",
            "qty":                 e.get("qty"),
            "unit":                e.get("unit"),
            "estimate_unit_price": e.get("unit_price"),
        }
        for e in raw if (e.get("name") or "").strip()
    ]

    added, skipped = batch_add_items(entries, project_id=project_id)
    return jsonify({"added": added, "skipped": skipped, "project_id": project_id})