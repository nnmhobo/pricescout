"""Кошторис import routes: /api/kostoris/parse, /api/kostoris/import

Supports two file layouts, chosen by the caller via `doc_type`:
  'pvr'  — КД_ПВР  ("Підсумкова відомість ресурсів", АВК-5) — parsers/kostoris_parser.py
  'rlmt' — КД_РЛМТ ("Відомість матеріальних ресурсів...")   — parsers/rlmt_parser.py
Item-level import into the shared `items` table is identical either way;
`doc_type` only ends up mattering for a linked project's `project_type`
(see core/item_db.create_project) and, for 'rlmt', each row's `section`.
"""

import json
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request
from core.item_db import add_item, batch_add_items, create_project, get_project
from parsers.kostoris_parser import parse as parse_kostoris
from parsers.rlmt_parser import parse as parse_rlmt

bp = Blueprint("kostoris", __name__)

LAST_IMPORT_FILE = Path("data/last_import.json")

DOC_TYPES = {"pvr", "rlmt"}
DOC_TYPE_LABELS = {"pvr": "КД_ПВР", "rlmt": "КД_РЛМТ"}


def _doc_type_from(source, default="pvr") -> str:
    """Normalize/validate a doc_type value from a form or JSON payload."""
    raw = (source.get("doc_type") or default) if source else default
    dt = str(raw).strip().lower()
    return dt if dt in DOC_TYPES else default


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

    doc_type = _doc_type_from(request.form)

    f.seek(0, 2); size = f.tell(); f.seek(0)
    if size < 1000:
        return jsonify({"error": "Файл занадто малий. Перевірте, чи це кошторис АВК-5."}), 400
    if size > 20 * 1024 * 1024:
        return jsonify({"error": "Файл занадто великий (>20MB)."}), 400

    tmp      = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(tmp.name)
    tmp.close()
    f.save(tmp_path)

    parse_fn = parse_rlmt if doc_type == "rlmt" else parse_kostoris

    try:
        items = parse_fn(str(tmp_path))
        if not items:
            expected = "Відомість матеріальних ресурсів КД_РЛМТ" if doc_type == "rlmt" else "Підсумкова відомість ресурсів АВК-5"
            return jsonify({"error": f"Позиції не знайдено. Перевірте, що це {expected}."}), 400
        rows_total = sum(i.get("rows", 1) for i in items)
        result = {
            "total":      len(items),                 # unique materials
            "rows_total": rows_total,                 # matched file rows (incl. repeats)
            "merged":     rows_total - len(items),    # repeat rows merged (qty summed)
            "retail":     sum(1 for i in items if i["retail"]),
            "items":      items,
            "filename":   f.filename,
            "doc_type":   doc_type,
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
    """Save selected parse rows into the DB, preserving file order.

    Body:
      items:            ordered rows from /api/kostoris/parse
      doc_type:         'pvr' (default) | 'rlmt' — which layout `items` came
                        from. Sets a NEW project's `project_type`; must MATCH
                        an EXISTING project's type or the request is rejected.
      project_id:       link the selection to an existing project, OR
      new_project_name: create a project first and link to it
      filename:         stored as the project's avk_file (with new_project_name)
      keep_order:       true → the project stores EVERY source row in file
                        order (duplicates included, expanded from each item's
                        `occurrences`) — 1:1 URL mapping against the file.
                        false/absent → one row per material (qty summed).
    """
    payload    = request.json
    doc_type   = _doc_type_from(payload)
    project_id = (payload.get("project_id") or "").strip() or None
    new_name   = (payload.get("new_project_name") or "").strip()
    keep_order = bool(payload.get("keep_order"))
    raw        = payload.get("items") or [{"name": n} for n in payload.get("names", [])]
    if not raw:
        return jsonify({"error": "Немає вибраних позицій"}), 400

    project = None
    if new_name:
        project = create_project(new_name, avk_file=(payload.get("filename") or None),
                                  project_type=doc_type)
        project_id = project["id"]
    elif project_id:
        # A project mirrors ONE file — reject linking a differently-typed
        # file into it rather than silently mixing КД_ПВР/КД_РЛМТ rows (the
        # section-preserving export only makes sense if every synced row
        # came from the same layout).
        existing = get_project(project_id)
        if not existing:
            return jsonify({"error": "Проект не знайдено"}), 404
        existing_type = existing.get("project_type") or "pvr"
        if existing_type != doc_type:
            return jsonify({"error": (
                f"Проект «{existing['name']}» має тип {DOC_TYPE_LABELS.get(existing_type, existing_type)}, "
                f"а обраний файл — {DOC_TYPE_LABELS.get(doc_type, doc_type)}. "
                "Оберіть інший проект або створіть новий."
            )}), 400

    entries = [
        {
            "label":               (e.get("name") or "").strip(),
            "avk_code":            (e.get("code") or "").strip() or None,
            "category":            (e.get("category") or "").strip() or None,
            "source":              "kostoris",
            "qty":                 e.get("qty"),
            "unit":                e.get("unit"),
            "estimate_unit_price": e.get("unit_price"),
            "section":             e.get("section"),
            "occurrences":         e.get("occurrences"),
        }
        for e in raw if (e.get("name") or "").strip()
    ]

    added, linked, skipped = batch_add_items(
        entries, project_id=project_id, keep_duplicates=keep_order,
    )
    return jsonify({
        "added":        added,
        "linked":       linked,
        "skipped":      skipped,
        "keep_order":   keep_order,
        "doc_type":     doc_type,
        "project_id":   project_id,
        "project_name": project["name"] if project else None,
    })