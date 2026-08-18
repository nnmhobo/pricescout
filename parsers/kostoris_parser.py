"""
Парсер кошторису АВК-5 (Excel .xls/.xlsx)
Витягує будівельні матеріали що можна моніторити в роздрібних магазинах.

Це формат КД_ПВР ("Підсумкова відомість ресурсів") — другий підтримуваний
формат, КД_РЛМТ, живе у parsers/rlmt_parser.py.
"""

import re
import pandas as pd
from pathlib import Path
from matching.monitorable import is_monitorable
from parsers.category_codes import derive_category


CODE_RE = re.compile(r'^[&+]?[СCКк\d][\dА-Яа-яA-Za-z]')
_SECTION_RE = re.compile(r'^Розділ\s*\d', re.IGNORECASE)

# NOTE: retail/non-retail classification lives entirely in `monitorable.py`.
# A duplicate keyword list used to sit here but was never read — removed.


def _parse_df(df: pd.DataFrame) -> list[dict]:
    items: list[dict] = []
    by_key: dict[str, dict] = {}
    merged_rows = 0
    seq = 0   # ordinal of the matched row within the file (0-based)

    for _, row in df.iterrows():
        col0 = str(row[0]) if pd.notna(row[0]) else ''
        if _SECTION_RE.match(col0.strip()):
            raise ValueError(
                "Файл містить розділи 'Розділ 1' / 'Розділ 2' — це схоже на "
                "файл КД_РЛМТ, а не КД_ПВР. Оберіть інший тип файлу при "
                "завантаженні."
            )

        code_raw  = str(row[1]) if pd.notna(row[1]) else ''
        name_raw  = str(row[2]) if pd.notna(row[2]) else ''
        unit_raw  = str(row[3]) if pd.notna(row[3]) else ''
        qty_raw   = str(row[4]) if pd.notna(row[4]) else ''
        price_raw = str(row[6]) if pd.notna(row[6]) else ''

        code = code_raw.replace('\n', ' ').strip()
        code = re.sub(r'\s*варіант\s*\d+', '', code, flags=re.IGNORECASE).strip()
        name = name_raw.replace('\n', ' ').strip()
        unit = unit_raw.replace('\n', ' ').strip()

        if not CODE_RE.match(code) or not name or name == 'nan':
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

        key = name.lower()
        existing = by_key.get(key)
        if existing is not None:
            # Same material on another row of the file — typical АВК-5
            # output: the resource is listed under EVERY work section it is
            # used in, each with its own quantity. Merge into one entry and
            # SUM the quantities (when units match), so project totals are
            # correct. `rows` counts the merged source rows for the UI;
            # `occurrences` keeps every source row (ordinal + its own qty /
            # price) so keep-order project imports can restore the file 1:1.
            merged_rows += 1
            existing['rows'] += 1
            existing['occurrences'].append(
                {'seq': seq, 'qty': qty, 'unit_price': unit_price})
            seq += 1
            if qty is not None and \
               (existing.get('unit') or '').strip().lower() == unit.strip().lower():
                existing['qty'] = round((existing.get('qty') or 0) + qty, 6)
            continue

        category = derive_category(code)
        is_retail = is_monitorable(name)
        item = {
            'code':       code,
            'name':       name,
            'unit':       unit,
            'qty':        qty,
            'unit_price': unit_price,
            'retail':     is_retail,
            'category':   category,
            'rows':       1,   # how many file rows were merged into this entry
            # every source row of this material: file ordinal + row qty/price
            'occurrences': [{'seq': seq, 'qty': qty, 'unit_price': unit_price}],
        }
        seq += 1
        items.append(item)
        by_key[key] = item

    # silent in production — summary only to console
    print(f"Кошторис: {len(items)} унікальних позицій ({merged_rows} рядків-повторів об'єднано)")
    return items


def parse(filepath: str) -> list[dict]:
    """
    Parse an АВК-5 кошторис Excel file.
    Returns list of unique material items with retail flag.
    """
    path = Path(filepath)

    # Convert .xls to xlsx if needed
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
        # it can raise its own ValueError (e.g. wrong-doc-type mismatch) and
        # that message must reach the caller as-is, not get rewrapped into
        # the "couldn't read .xls" message meant for genuine read failures.
        return _parse_df(df)
    else:
        df = pd.read_excel(str(path), sheet_name=0, header=None)
        return _parse_df(df)

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python kostoris_parser.py <path/to/kostoris.xlsx>")
        sys.exit(2)
    items = parse(sys.argv[1])
    retail = [i for i in items if i['retail']]
    print(f'Total: {len(items)}, Retail: {len(retail)}')
    for i in retail[:10]:
        print(f"  {i['name'][:60]:60s} | {i['unit']:6s} | {i['unit_price']}")