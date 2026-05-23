"""
База даних матеріалів — SQLite backend.
Замінює items.json. Свіжий старт — items.json більше не потрібен.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path("pricescout.db")


# WAL mode is persistent at the SQLite file level — once enabled it stays
# enabled across reconnects. Track whether we've already set it so we
# avoid the round-trip PRAGMA on every connection after the first.
_wal_enabled: bool = False


@contextmanager
def get_conn():
    global _wal_enabled
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if not _wal_enabled:
        conn.execute("PRAGMA journal_mode=WAL")
        _wal_enabled = True
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn):
    """Add new columns if they don't exist (safe migration).

    The full monitorability recompute (an UPDATE per row) only runs when
    the `monitorable` column is freshly added — otherwise opening the app
    against an existing DB would pointlessly rewrite every row on every
    startup.
    """
    from matching.monitorable import is_monitorable
    cols = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    monitorable_freshly_added = "monitorable" not in cols
    if monitorable_freshly_added:
        conn.execute("ALTER TABLE items ADD COLUMN monitorable INTEGER NOT NULL DEFAULT 1")
    if "manual_price" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN manual_price REAL")
    if "qty" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN qty REAL")
    if "unit" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN unit TEXT")
    if "estimate_unit_price" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN estimate_unit_price REAL")
    if "search_label" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN search_label TEXT")
    if "project_id" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN project_id TEXT")

    # Per-result manual overrides: lets the user correct a misread price
    # straight from the Results tab and leave a free-form comment that
    # rides along into the Excel export. Stored on supplier_entries so it
    # survives app restarts; cleared automatically when the row is dropped.
    se_cols = {r[1] for r in conn.execute("PRAGMA table_info(supplier_entries)").fetchall()}
    if "manual_price" not in se_cols:
        conn.execute("ALTER TABLE supplier_entries ADD COLUMN manual_price REAL")
    if "comment" not in se_cols:
        conn.execute("ALTER TABLE supplier_entries ADD COLUMN comment TEXT")

    # Projects table
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            created     TEXT NOT NULL,
            description TEXT,
            avk_file    TEXT
        );
        CREATE TABLE IF NOT EXISTS project_items (
            project_id  TEXT NOT NULL,
            item_id     TEXT NOT NULL,
            added       TEXT NOT NULL,
            PRIMARY KEY (project_id, item_id)
        );
    """)
    # One-time migration: move legacy project_id column values into junction table
    pi_rows = conn.execute("SELECT COUNT(*) FROM project_items").fetchone()[0]
    if pi_rows == 0:
        conn.execute("""
            INSERT OR IGNORE INTO project_items (project_id, item_id, added)
            SELECT project_id, id, created FROM items
            WHERE project_id IS NOT NULL
        """)

    # Price history table
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id     TEXT NOT NULL,
            supplier_id TEXT NOT NULL,
            price       REAL NOT NULL,
            checked_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ph_item ON price_history(item_id, supplier_id);
        CREATE INDEX IF NOT EXISTS idx_ph_date ON price_history(checked_at);
    """)

    if monitorable_freshly_added:
        rows = conn.execute("SELECT id, label FROM items").fetchall()
        updates = [
            (1 if is_monitorable(label or "") else 0, item_id)
            for item_id, label in rows
        ]
        if updates:
            conn.executemany("UPDATE items SET monitorable=? WHERE id=?", updates)


_FLOAT_FIELDS = {"manual_price", "qty", "estimate_unit_price"}
_INT_FIELDS = {"monitorable"}
_TEXT_FIELDS = {"unit", "project_id"}


def _coerce(key: str, val):
    if val is None or val == "":
        return None
    if key in _INT_FIELDS:
        return int(val)
    if key in _FLOAT_FIELDS:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    if key in _TEXT_FIELDS:
        return str(val).strip() or None
    return val


def update_item(item_id: str, data: dict):
    """Update flags / numeric fields on an existing item."""
    allowed = _INT_FIELDS | _FLOAT_FIELDS | _TEXT_FIELDS
    sets, vals = [], []
    for key in allowed:
        if key in data:
            sets.append(f"{key}=?")
            vals.append(_coerce(key, data[key]))
    if not sets:
        return
    vals.append(item_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id=?", vals)


def init_db():
    """Create tables on first run."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id                   TEXT PRIMARY KEY,
                label                TEXT NOT NULL UNIQUE,
                created              TEXT NOT NULL,
                source               TEXT NOT NULL DEFAULT 'manual',
                avk_code             TEXT,
                category             TEXT,
                qty                  REAL,
                unit                 TEXT,
                estimate_unit_price  REAL
            );
            CREATE TABLE IF NOT EXISTS supplier_entries (
                item_id      TEXT NOT NULL,
                supplier_id  TEXT NOT NULL,
                url          TEXT,
                found        INTEGER NOT NULL DEFAULT 0,
                last_checked TEXT,
                last_price   REAL,
                PRIMARY KEY (item_id, supplier_id),
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_items_label    ON items(label);
            CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
            CREATE INDEX IF NOT EXISTS idx_items_source   ON items(source);
            CREATE INDEX IF NOT EXISTS idx_items_avk_code ON items(avk_code);
        """)
        _migrate(conn)


def _load_suppliers(conn, item_id: str) -> dict:
    rows = conn.execute(
        "SELECT * FROM supplier_entries WHERE item_id=?", (item_id,)
    ).fetchall()
    return {
        r["supplier_id"]: {
            "url":          r["url"],
            "found":        bool(r["found"]),
            "last_checked": r["last_checked"],
            "last_price":   r["last_price"],
            "manual_price": r["manual_price"],
            "comment":      r["comment"],
        }
        for r in rows
    }


def _build_sup_map(sup_rows) -> dict:
    """Group a flat list of supplier_entry rows into {item_id: {sup_id: {...}}}.

    Used by batch loaders (load_items, get_availability_matrix, etc.) to
    avoid N+1 queries: callers fetch all relevant rows in one query and
    pass them here instead of calling _load_suppliers() per item.
    """
    result: dict[str, dict] = {}
    for r in sup_rows:
        result.setdefault(r["item_id"], {})[r["supplier_id"]] = {
            "url":          r["url"],
            "found":        bool(r["found"]),
            "last_checked": r["last_checked"],
            "last_price":   r["last_price"],
            "manual_price": r["manual_price"],
            "comment":      r["comment"],
        }
    return result


def _row_to_dict(row, suppliers: dict) -> dict:
    # All columns are guaranteed present after _migrate() runs at startup.
    return {
        "id":                  row["id"],
        "label":               row["label"],
        "created":             row["created"],
        "source":              row["source"],
        "avk_code":            row["avk_code"],
        "category":            row["category"],
        "monitorable":         bool(row["monitorable"]) if row["monitorable"] is not None else True,
        "manual_price":        row["manual_price"],
        "qty":                 row["qty"],
        "unit":                row["unit"],
        "estimate_unit_price": row["estimate_unit_price"],
        "search_label":        row["search_label"],
        "project_id":          row["project_id"],
        "suppliers":           suppliers,
    }


def load_items() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM items ORDER BY label").fetchall()
        if not rows:
            return []
        sup_rows = conn.execute("SELECT * FROM supplier_entries").fetchall()
        sup_map = _build_sup_map(sup_rows)
        return [_row_to_dict(r, sup_map.get(r["id"], {})) for r in rows]


def get_item(item_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        return _row_to_dict(row, _load_suppliers(conn, row["id"]))


def get_item_by_code(avk_code: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM items WHERE avk_code=?", (avk_code.strip(),)
        ).fetchone()
        if not row:
            return None
        return _row_to_dict(row, _load_suppliers(conn, row["id"]))


def add_item(label: str, source: str = "manual",
             avk_code: str | None = None, category: str | None = None,
             qty: float | None = None, unit: str | None = None,
             estimate_unit_price: float | None = None,
             project_id: str | None = None) -> dict:
    from matching.monitorable import is_monitorable
    if avk_code:
        existing = get_item_by_code(avk_code)
        if existing:
            raise ValueError(f"Вже існує з кодом {avk_code}: {existing['label']}")
    item_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    mon = 1 if is_monitorable(label.strip(), category or "") else 0
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO items
                   (id, label, created, source, avk_code, category,
                    qty, unit, estimate_unit_price, monitorable, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_id, label.strip(), datetime.now().strftime("%d.%m.%Y"),
                 source, avk_code.strip() if avk_code else None, category or None,
                 _coerce("qty", qty),
                 _coerce("unit", unit),
                 _coerce("estimate_unit_price", estimate_unit_price),
                 mon, project_id or None),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Такий матеріал вже збережено")
    # Construct the dict directly — new items have no supplier entries yet,
    # so a full get_item() round-trip (which JOINs supplier_entries) is wasteful.
    return {
        "id":                  item_id,
        "label":               label.strip(),
        "created":             datetime.now().strftime("%d.%m.%Y"),
        "source":              source,
        "avk_code":            avk_code.strip() if avk_code else None,
        "category":            category or None,
        "monitorable":         bool(mon),
        "manual_price":        None,
        "qty":                 _coerce("qty", qty),
        "unit":                _coerce("unit", unit),
        "estimate_unit_price": _coerce("estimate_unit_price", estimate_unit_price),
        "search_label":        None,
        "project_id":          project_id or None,
        "suppliers":           {},
    }


def batch_add_items(entries: list, project_id: str | None = None) -> tuple[int, int]:
    """
    Bulk insert items from кошторис. Much faster than calling add_item() in a loop.
    entries: list of dicts with optional fields:
      {label, source, avk_code, category, qty, unit, estimate_unit_price}
    Returns (added, skipped) counts.
    """
    from matching.monitorable import is_monitorable
    added = skipped = 0
    now = datetime.now().strftime("%d.%m.%Y")

    with get_conn() as conn:
        existing_labels = {r[0] for r in conn.execute("SELECT label FROM items").fetchall()}

        rows = []
        base_id = datetime.now().strftime("%Y%m%d%H%M%S")
        for idx, e in enumerate(entries):
            label    = (e.get("label") or "").strip()
            avk_code = (e.get("avk_code") or "").strip() or None
            category = e.get("category") or None
            source   = e.get("source", "kostoris")
            qty      = _coerce("qty", e.get("qty"))
            unit     = _coerce("unit", e.get("unit"))
            est_up   = _coerce("estimate_unit_price", e.get("estimate_unit_price"))

            if not label:
                skipped += 1
                continue
            if label in existing_labels:
                skipped += 1
                continue

            item_id = f"{base_id}{idx:06d}"
            mon = 1 if is_monitorable(label, category or "") else 0
            rows.append((item_id, label, now, source, avk_code, category,
                         qty, unit, est_up, mon, project_id or None))
            existing_labels.add(label)
            added += 1

        if rows:
            conn.executemany(
                """INSERT OR IGNORE INTO items
                   (id, label, created, source, avk_code, category,
                    qty, unit, estimate_unit_price, monitorable, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            if project_id:
                now_iso = datetime.now().isoformat()
                conn.executemany(
                    "INSERT OR IGNORE INTO project_items (project_id, item_id, added) VALUES (?, ?, ?)",
                    [(project_id, r[0], now_iso) for r in rows],
                )

    return added, skipped


def delete_item(item_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))


def update_supplier_entry(item_id: str, supplier_id: str,
                          url: str | None, found: bool, price: float | None):
    """Persist a fresh scrape result. Preserves any existing manual_price
    / comment override so the user's hand edits aren't wiped on the next run.
    """
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT manual_price, comment FROM supplier_entries WHERE item_id=? AND supplier_id=?",
            (item_id, supplier_id),
        ).fetchone()
        manual_price = existing["manual_price"] if existing else None
        comment = existing["comment"] if existing else None
        conn.execute("""
            INSERT OR REPLACE INTO supplier_entries
                (item_id, supplier_id, url, found, last_checked, last_price, manual_price, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (item_id, supplier_id, url, int(found), now, price, manual_price, comment))
        if found and price:
            conn.execute(
                "INSERT INTO price_history (item_id, supplier_id, price, checked_at) VALUES (?, ?, ?, ?)",
                (item_id, supplier_id, price, now)
            )


def set_result_override(item_id: str, supplier_id: str, *,
                        manual_price: float | None = ..., comment: str | None = ...):
    """Set per-result hand-corrections that ride along with the scrape.

    ``manual_price=None`` clears the manual price; ``comment=None`` clears
    the comment. Passing the sentinel default (``...``) leaves that field
    alone — so callers can update one without touching the other.

    Creates a `supplier_entries` row if none exists yet (e.g. user adds a
    comment before the scrape has run).
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM supplier_entries WHERE item_id=? AND supplier_id=?",
            (item_id, supplier_id),
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO supplier_entries
                       (item_id, supplier_id, found, manual_price, comment)
                   VALUES (?, ?, 0, ?, ?)""",
                (item_id, supplier_id,
                 None if manual_price is ... else manual_price,
                 None if comment is ... else comment),
            )
            return
        sets, vals = [], []
        if manual_price is not ...:
            sets.append("manual_price=?")
            vals.append(manual_price)
        if comment is not ...:
            sets.append("comment=?")
            vals.append(comment)
        if not sets:
            return
        vals.extend([item_id, supplier_id])
        conn.execute(
            f"UPDATE supplier_entries SET {', '.join(sets)} WHERE item_id=? AND supplier_id=?",
            vals,
        )


def get_result_overrides(item_ids: list[str]) -> dict[tuple[str, str], dict]:
    """Return {(item_id, supplier_id): {manual_price, comment}} for the
    given item IDs. Used by the runner to splice overrides into a fresh
    batch's `state["results"]`."""
    if not item_ids:
        return {}
    placeholders = ",".join("?" * len(item_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT item_id, supplier_id, manual_price, comment
                FROM supplier_entries
                WHERE item_id IN ({placeholders})
                  AND (manual_price IS NOT NULL OR (comment IS NOT NULL AND comment != ''))""",
            item_ids,
        ).fetchall()
    return {
        (r["item_id"], r["supplier_id"]): {
            "manual_price": r["manual_price"],
            "comment": r["comment"],
        }
        for r in rows
    }


# ── Availability / coverage queries ───────────────────────────

def get_supplier_coverage() -> dict:
    """Per-supplier stats: how many items checked, how many found."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT supplier_id,
                   COUNT(*) AS checked,
                   SUM(found) AS found
            FROM supplier_entries
            GROUP BY supplier_id
        """).fetchall()
        return {
            r["supplier_id"]: {
                "checked": r["checked"],
                "found":   r["found"],
            }
            for r in rows
        }


def get_availability_matrix() -> list[dict]:
    """Return items with their per-supplier availability status.

    Each dict: {id, label, category, monitorable, suppliers: {sid: {found, last_price, last_checked}}}
    Only includes items that have at least one supplier_entry.
    """
    with get_conn() as conn:
        items = conn.execute("""
            SELECT DISTINCT i.id, i.label, i.category, i.monitorable
            FROM items i
            JOIN supplier_entries se ON se.item_id = i.id
            ORDER BY i.label
        """).fetchall()
        if not items:
            return []
        item_ids = [r["id"] for r in items]
        ph = ",".join("?" * len(item_ids))
        sup_rows = conn.execute(
            f"SELECT * FROM supplier_entries WHERE item_id IN ({ph})", item_ids
        ).fetchall()
        sup_map = _build_sup_map(sup_rows)
        return [
            {
                "id":          row["id"],
                "label":       row["label"],
                "category":    row["category"],
                "monitorable": bool(row["monitorable"]) if row["monitorable"] is not None else True,
                "suppliers":   sup_map.get(row["id"], {}),
            }
            for row in items
        ]


def get_items_for_supplier(supplier_id: str) -> list[str]:
    """Return item IDs that were found on a specific supplier."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT item_id FROM supplier_entries WHERE supplier_id=? AND found=1",
            (supplier_id,)
        ).fetchall()
        return [r["item_id"] for r in rows]


# ── Projects ───────────────────────────────────────────────────

def create_project(name: str, description: str | None = None,
                   avk_file: str | None = None) -> dict:
    project_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, created, description, avk_file) VALUES (?, ?, ?, ?, ?)",
            (project_id, name.strip(), datetime.now().strftime("%d.%m.%Y"),
             description or None, avk_file or None)
        )
    return get_project(project_id)


def get_projects() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created DESC").fetchall()
        if not rows:
            return []
        project_ids = [r["id"] for r in rows]
        ph = ",".join("?" * len(project_ids))

        # Batch-fetch item counts per project (2 queries instead of 2N)
        counts = {
            r["project_id"]: r["cnt"]
            for r in conn.execute(
                f"SELECT project_id, COUNT(*) AS cnt FROM project_items "
                f"WHERE project_id IN ({ph}) GROUP BY project_id",
                project_ids,
            ).fetchall()
        }
        prices = {
            r["project_id"]: r["cnt"]
            for r in conn.execute(
                f"""SELECT pi.project_id, COUNT(DISTINCT se.item_id) AS cnt
                    FROM supplier_entries se
                    JOIN project_items pi ON pi.item_id = se.item_id
                    WHERE pi.project_id IN ({ph})
                      AND se.found=1 AND se.last_price IS NOT NULL
                    GROUP BY pi.project_id""",
                project_ids,
            ).fetchall()
        }

        result = []
        for r in rows:
            p = dict(r)
            p["item_count"]      = counts.get(r["id"], 0)
            p["items_with_price"] = prices.get(r["id"], 0)
            result.append(p)
        return result


def get_project(project_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if not row:
            return None
        p = dict(row)
        p["item_count"] = conn.execute(
            "SELECT COUNT(*) FROM project_items WHERE project_id=?", (project_id,)
        ).fetchone()[0]
        return p


def update_project(project_id: str, data: dict):
    sets, vals = [], []
    for key in ("name", "description", "avk_file"):
        if key in data:
            sets.append(f"{key}=?")
            vals.append(data[key] or None)
    if not sets:
        return
    vals.append(project_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", vals)


def delete_project(project_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM project_items WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


def get_project_items(project_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT i.* FROM items i
               JOIN project_items pi ON pi.