"""
Парсер кошторису КД_РЛМТ (Excel .xls/.xlsx)
"Відомість матеріальних ресурсів із зазначенням відсоткової частки" —
другий підтримуваний формат кошторису, поруч із kostoris_parser.py (КД_ПВР,
"Підсумкова відомість ресурсів").

Розкладка колонок відрізняється від КД_ПВР (тут є додаткова колонка
"Варіант ціни", через яку назва/од./к-сть/ціна зсунуті на одну позицію, і
ціна — одне число, а не комбінована клітинка "за од./всього"). Головна
структурна відмінність — матеріали розбиті на РІВНО ДВА позначені розділи:

  Розділ 1. Ціноутворюючі матеріали     (найдорожчі,  >= 60% вартості)
  Розділ 2. Неціноутворюючі матеріали   (найдешевші,  <= 40% вартості)

Кожна позиція позначається, з якого розділу вона взята (`section: 1|2`),
щоб проект, зібраний з цього файлу, міг зберегти те саме групування і
порядок при експорті — див. routes/projects.py: export_project().
"""

import re
import pandas as pd
from pathlib import Path
from matching.monitorable import is_monitorable
from parsers.category_codes import derive_category


CODE_RE = re.compile(r'^[&+]?[СCКк\d][\dА-Яа-яA-Za-z]')
SECTION_RE = re.compile(r'^Розділ\s*(\d+)', re.IGNORECASE)

# 0-indexed колонки — відрізняються від розкладки КД_ПВР через додаткову
# колонку "Варіант ціни" на позиції 2.
COL_CODE = 1
COL_NAME = 3
COL_UNIT = 4
COL_QTY = 5
COL_PRICE = 6


def _parse_df(df: pd.DataFrame) -> list[dict]:
    items: list[dict] = []
    by_key: dict[tuple, dict] = {}
    merged_rows = 0
    seq = 0   # ordinal of the matched row within the file (0-based)
    current_section = None
    seen_any_section = False

    for _, row in df.iterrows():
        col0 = str(row[0]) if pd.notna(row[0]) else ''
        m = SECTION_RE.match(col0.strip())
        if m:
            current_section = int(m.group(1))
            seen_any_section = True
            continue   # marker row itself is never a material row

        code_raw  = str(row[COL_CODE])  if pd.notna(row[COL_CODE])  else ''
        name_raw  = str(row[COL_NAME])  if pd.notna(row[COL_NAME])  else ''
        unit_raw  = str(row[COL_UNIT])  if pd.notna(row[COL_UNIT])  else ''
        qty_raw   = str(row[COL_QTY])   if pd.notna(row[COL_QTY])   else ''
        price_raw = str(row[COL_PRICE]) if pd.notna(row[COL_PRICE]) else ''

        code = code_raw.replace('\n', ' ').strip()
        code = re.sub(r'\s*варіант\s*\d+', '', code, flags=re.IGNORECASE).strip()
        name = name_raw.replace('\n', ' ').strip()
        unit = unit_raw.replace('\n', ' ').strip()

        if not CODE_RE.match(code) or not name or name == 'nan':
            # Also skips the "Разом:" subtotal row and the periodic
            # page-header-repeat rows (a bare 1..10 row) — both fail the
            # code-shape check on col 1 the same way КД_ПВР's do.
            continue

        unit_price = None
        raw_price = price_raw.split('\n')[0].replace(',', '.').replace('\xa0', '').replace(' ', '').strip()
        try:
            unit_price = float(raw_price)
        except Exception:
            pass

        qty = None
        try:
            qty = float(qty_raw.replace(',', '.').strip())
        except Exception:
            pass

        # Merge key includes the section: the same material name should
        # never legitimately straddle both a "price-forming >=60%" section
        # and a "non-price-forming <=40%" one in a well-formed file, and
        # merging across sections would corrupt whichever section "wins" —
        # unlike kostoris_parser.py, which merges on name alone.
        key = (name.lower(), current_section)
        existing = by_key.get(key)
        if existing is not None:
            merged_rows += 1
            existing['rows'] += 1
            existing['occurrences'].append(
                {'seq': seq, 'qty': qty, 'unit_price': unit_price, 'section': current_section})
            seq += 1
            if qty is not None and \
               (existing.get('unit') or '').strip().lower() == unit.strip().lower():
                existing['qty'] = round((existing.get('qty') or 0) + qty, 6)
            continue

        category = derive_category(code)
        is_retail = is_monitorable(name)
        item = {
            'code':        code,
            'name':        name,
            'unit':        unit,
            'qty':         qty,
            'unit_price':  unit_price,
            'retail':      is_retail,
            'category':    category,
            'section':     current_section,   # 1 or 2
            'rows':        1,   # how many file rows were merged into this entry
            # every source row of this material: file ordinal + row qty/price/section
            'occurrences': [{'seq': seq, 'qty': qty, 'unit_price': unit_price, 'section': current_section}],
        }
        seq += 1
        items.append(item)
        by_key[key] = item

    if not seen_any_section:
        raise ValueError(
            "Не знайдено розділів 'Розділ 1' / 'Розділ 2' — це схоже на файл "
            "КД_ПВР, а не КД_РЛМТ. Оберіть інший тип файлу при завантаженні."
        )

    # silent in production — summary only to console
    print(f"КД_РЛМТ: {len(items)} унікальних позицій ({merged_rows} рядків-повторів об'єднано)")
    return items


def parse(filepath: str) -> list[dict]:
    """
    Parse a КД_РЛМТ кошторис Excel file ("Відомість матеріальних ресурсів
    із зазначенням відсоткової частки").
    Returns list of unique material items with retail flag + section (1|2).
    """
    path = Path(filepath)

    if path.suffix.lower() == '.xls':
        try:
            import xlrd
            wb = xlrd.open_workbook(str(path))
            ws = wb.sheet_by_index(0)
            data = [[ws.cell_value(r, c) for c in range(ws.ncols)] for r in range(ws.nrows)]
            df = pd.DataFrame(data)
        except Exception as e:
            raise ValueError(f"Не вдалось прочитати .xls файл: {e}. Спробуйте зберегти файл як .xlsx в Excel або АВК-5.")
        # NOTE: _parse_df() is called OUTSIDE the try/except above on purpose —
        # it can raise its own ValueError (e.g. "no sections found" when the
        # wrong doc type was picked) and that message must reach the caller
        # as-is, not get rewrapped into the "couldn't read .xls" message.
        return _parse_df(df)
    else:
        df = pd.read_excel(str(path), sheet_name=0, header=None)
        return _parse_df(df)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python rlmt_parser.py <path/to/rlmt.xlsx>")
        sys.exit(2)
    items = parse(sys.argv[1])
    retail = [i for i in items if i['retail']]
    sec1 = sum(1 for i in items if i['section'] == 1)
    sec2 = sum(1 for i in items if i['section'] == 2)
    print(f'Total: {len(items)}, Retail: {len(retail)}, Розділ 1: {sec1}, Розділ 2: {sec2}')
    for i in retail[:10]:
        print(f"  §{i['section']} {i['name'][:55]:55s} | {i['unit']:6s} | {i['unit_price']}")
