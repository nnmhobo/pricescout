"""
search_label_converter.py — Converts кошторис item labels into
search-friendly queries for Ukrainian building material retailers.

Rules:
  1. Recognize Ceresit codes: СТ-NNN, CT-NNN → "Ceresit CT NNN"
  2. Recognize other brand codes: ГФ-021, ПФ-0142, ХС-010, МА-025, МО-1
  3. Strip verbose technical specs (steel grades, DIN refs, etc.)
  4. Keep: product type + brand + key dimensions (mm, kg, l)
  5. Normalize Ukrainian Ґ→Г for search compatibility
  6. Cap at ~60 chars for cleaner search queries
"""

import re


# ── Brand code patterns ───────────────────────────────────────

_CERESIT_RE = re.compile(
    r'(?:^|\s|[(\-])([СCс][ТTт])[\-\s]+(\d{1,3})\b', re.IGNORECASE
)

_BRAND_CODES = {
    # paint/primer codes → keep as-is with type
    "ГФ": "Грунтовка ГФ",
    "ПФ": "Грунтовка ПФ",
    "ХС": "Грунтовка ХС",
    "МА": "Фарба МА",
    "МО": "Фарба МО",
    "КО": "Фарба КО",
    "ВД": "Фарба ВД",
    "АК": "Фарба АК",
    "НЦ": "Емаль НЦ",
}

_BRAND_CODE_RE = re.compile(
    r'(?:^|\s)(' + '|'.join(_BRAND_CODES.keys()) + r')[\-\s]*(\d{1,4})',
    re.IGNORECASE
)

# ── Noise patterns to strip ───────────────────────────────────

_NOISE_PATTERNS = [
    # Steel grades
    r'із сталі [А-Яа-яA-Za-z0-9\s,]+',
    r'марка [МM]\d+',
    r'марки? [А-Яа-яA-Za-z\-]+',
    # DIN/GOST references
    r'ГОСТ\s*[\d\.\-]+',
    r'ДБН\s*[\d\.\-]+',
    r'ТУ\s*[\d\.\-]+',
    # Pressure/force specs
    r'тиск\s*[\d,\.]+\s*МПа\s*\[[^\]]*\]',
    # Verbose material descriptions
    r'з гарячекатаного прокату',
    r'із вуглецевої звичайної якості',
    r'звичайної якості',
    r'для будівельних робіт',
    r'для внутрішніх робіт',
    r'для зовнішніх робіт',
    r'для технічних цілей',
    # Redundant prefixes
    r'^Труби сталеві зварні водогазопровідні з різьбою,?\s*',
]

_NOISE_COMPILED = [re.compile(p, re.IGNORECASE) for p in _NOISE_PATTERNS]

# ── Dimension extraction ──────────────────────────────────────

_SIZE_RE = re.compile(
    r'(\d+)\s*[хxX×]\s*(\d+)(?:\s*[хxX×]\s*(\d+))?\s*(мм|см|м)?',
    re.IGNORECASE
)

_DIAM_RE = re.compile(
    r'(?:діам(?:етр)?|Ø|d|д)[.\s]*(\d+(?:[.,]\d+)?)\s*(мм)?',
    re.IGNORECASE
)


def convert_label(label: str) -> str:
    """
    Convert a кошторис label into a search-friendly query.
    Returns a shorter, more specific string suitable for site search boxes.
    """
    if not label or not label.strip():
        return label or ""

    original = label.strip()
    result = original

    # 1. Check for Ceresit codes first (most common in Ukrainian construction)
    ceresit_match = _CERESIT_RE.search(result)
    if ceresit_match:
        code_num = ceresit_match.group(2)
        # Extract the product type word before the code
        type_word = _extract_type_word(result)
        result = f"Ceresit CT {code_num}"
        if type_word:
            result = f"{type_word} {result}"
        # Add weight/size if present
        dims = _extract_key_dimension(original)
        if dims:
            result = f"{result} {dims}"
        return _finalize(result)

    # 2. Check for other brand codes (ГФ-021, ПФ-115, etc.)
    brand_match = _BRAND_CODE_RE.search(result)
    if brand_match:
        prefix = brand_match.group(1).upper()
        num = brand_match.group(2)
        brand_name = _BRAND_CODES.get(prefix, prefix)
        result = f"{brand_name}-{num}"
        dims = _extract_key_dimension(original)
        if dims:
            result = f"{result} {dims}"
        return _finalize(result)

    # 3. Strip noise patterns
    for pattern in _NOISE_COMPILED:
        result = pattern.sub("", result)

    # 4. Collapse whitespace and commas
    result = re.sub(r'\s*,\s*', " ", result)
    result = re.sub(r'\s+', " ", result).strip()

    # 5. If still too long (>60 chars), try to shorten
    if len(result) > 60:
        # Keep first meaningful phrase + dimensions
        parts = result.split(",")
        result = parts[0].strip()
        dims = _extract_key_dimension(original)
        if dims and dims not in result:
            result = f"{result} {dims}"

    # 6. Normalize Ґ→Г for search
    return _finalize(result)


def _extract_type_word(text: str) -> str:
    """Extract the product type word (шпаклівка, штукатурка, грунтовка, etc.)"""
    type_words = [
        "шпаклівка", "штукатурка", "грунтовка", "ґрунтовка",
        "фарба", "емаль", "клей", "суміш", "стяжка",
        "гідроізоляція", "затирка",
    ]
    lower = text.lower()
    for tw in type_words:
        if tw in lower:
            return tw.capitalize()
    return ""


def _extract_key_dimension(text: str) -> str:
    """Extract the most important dimension (weight in kg, or size in mm)."""
    # Prefer kg (weight of a bag)
    kg_match = re.search(r'(\d+(?:[.,]\d+)?)\s*кг', text, re.IGNORECASE)
    if kg_match:
        return f"{kg_match.group(1)} кг"

    # Then liters
    l_match = re.search(r'(\d+(?:[.,]\d+)?)\s*л\b', text, re.IGNORECASE)
    if l_match:
        return f"{l_match.group(1)} л"

    # Then mm dimensions
    diam_match = _DIAM_RE.search(text)
    if diam_match:
        return f"{diam_match.group(1)} мм"

    size_match = _SIZE_RE.search(text)
    if size_match:
        parts = [size_match.group(1), size_match.group(2)]
        if size_match.group(3):
            parts.append(size_match.group(3))
        unit = size_match.group(4) or "мм"
        return "x".join(parts) + f" {unit}"

    return ""


def _finalize(text: str) -> str:
    """Final cleanup: normalize chars, cap length."""
    # Ґ → Г for search compatibility (sites use both)
    text = text.replace("Ґ", "Г").replace("ґ", "г")
    # Collapse whitespace
    text = re.sub(r'\s+', " ", text).strip()
    # Cap at 60 chars at a word boundary. Do NOT append "..." — search
    # engines treat it literally and never match.
    if len(text) > 60:
        text = text[:60].rsplit(" ", 1)[0]
    return text


def convert_all_items():
    """Update search_label for all items in the database."""
    import sqlite3
    from pathlib import Path

    db = Path("pricescout.db")
    if not db.exists():
        print("DB not found")
        return

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    # Ensure column exists
    cols = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    if "search_label" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN search_label TEXT")
        conn.commit()

    rows = conn.execute("SELECT id, label FROM items").fetchall()
    updated = 0
    for row in rows:
        sl = convert_label(row["label"])
        if sl and sl != row["label"]:
            conn.execute("UPDATE items SET search_label=? WHERE id=?", (sl, row["id"]))
            updated += 1

    conn.commit()
    conn.close()
    print(f"Updated {updated}/{len(rows)} items with search_label")


if __name__ == "__main__":
    convert_all_items()

    # Show results
    import sqlite3
    conn = sqlite3.connect("pricescout.db")
    rows = conn.execute(
        "SELECT label, search_label FROM items WHERE search_label IS NOT NULL ORDER BY label"
    ).fetchall()
    print(f"\nExamples ({len(rows)} total):")
    for r in rows[:30]:
        print(f"  {r[0][:50]:50s} → {r[1]}")
    conn.close()
