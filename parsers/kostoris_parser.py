"""
Парсер кошторису АВК-5 (Excel .xls/.xlsx)
Витягує будівельні матеріали що можна моніторити в роздрібних магазинах.
"""

import re
import pandas as pd
from pathlib import Path
from matching.monitorable import is_monitorable


CODE_RE = re.compile(r'^[&+]?[СCКк\d][\dА-Яа-яA-Za-z]')

# NOTE: retail/non-retail classification lives entirely in `monitorable.py`.
# A duplicate keyword list used to sit here but was never read — removed.


def _parse_df(df: pd.DataFrame) -> list[dict]:
    items = []
    seen  = set()
    duplicates = []

    for _, row in df.iterrows():
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

        key = name.lower()
        if key in seen:
            duplicates.append(name)
            continue
        seen.add(key)

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

        # determine category from ДБН code prefix
        code_clean = code.lstrip('&+').strip()
        num_match = re.match(r'^[СCКк]?(\d+)', code_clean)
        num = int(num_match.group(1)) if num_match else 0

        if re.match(r'^[КкKk]', code_clean):
            category = 'Конструкції збірні'

        # ── С-resource catalog codes (verified from DB analysis) ──
        # С111 = загальнобудівельні матеріали (металовироби, кріплення, цемент, фарби...)
        elif num == 111 or (num == 11 and num_match and len(num_match.group(1)) == 2):
            category = 'Підлоги, покрівлі, покриття'
        # С112 = пиломатеріали (дошки, бруски, бруси)
        elif num == 112:
            category = 'Пиломатеріали'
        # С113 = трубопроводи, фітинги, профільний метал
        elif num == 113:
            category = 'Трубопроводи та фітинги'
        # С114 = теплоізоляція (мінвата, пінопластирол)
        elif num == 114:
            category = 'Теплоізоляція'
        # С121 = металоконструкції
        elif num == 121:
            category = 'Металоконструкції'
        # С123 = вікна та двері (металопластикові, алюмінієві)
        elif num == 123:
            category = 'Вікна та двері'
        # С124 = арматура сталева
        elif num == 124:
            category = 'Арматура та металоконструкції'
        # С130 = heating/ventilation mixed zbіrnyk
        # sub-code 62 = ventilation equipment (recuperators, exhaust units)
        elif num == 130:
            sub_match = re.search(r'С130-(\d+)', code_clean)
            sub = int(sub_match.group(1)) if sub_match else 0
            if sub == 62:
                category = 'Вентиляція та кондиціонування'
            else:
                category = 'Теплопостачання та опалення'
        # С142/С147 = спецматеріали (вода, дріт)
        elif num in (142, 147):
            category = 'Спеціальні роботи'
        # С151/С152 = кабелі (силові, сигналізації)
        elif 151 <= num <= 152:
            category = 'Кабельні системи'
        # Other С1xx codes
        elif 101 <= num <= 110:
            category = 'Конструктивні роботи'
        elif 115 <= num <= 120:
            category = 'Захист конструкцій'
        elif 125 <= num <= 129:
            category = 'Мережі (водопостачання, газ)'
        elif 131 <= num <= 149:
            category = 'Спеціальні роботи'

        # ── Equipment montage codes (verified from DB) ────────────
        elif 1100 <= num <= 1119:
            category = 'Теплотехнічне устаткування'
        elif 1300 <= num <= 1399:
            category = 'Вентиляція та кондиціонування'
        elif 1400 <= num <= 1419:
            category = 'Санітарно-технічне устаткування'
        elif 1421 <= num <= 1429:
            category = 'Будівельні матеріали'
        elif 1500 <= num <= 1529:
            category = 'Електрообладнання'
        elif 1530 <= num <= 1560:
            category = 'Кабельні системи'
        elif 1600 <= num <= 1629:
            category = 'Охорона та сигналізація'
        elif 1630 <= num <= 1699:
            category = 'Теплопостачання та опалення'
        elif 1700 <= num <= 1799:
            category = 'Автоматизація (КВП)'
        elif 1800 <= num <= 1899:
            category = 'Вантажопідйомне устаткування'
        elif num == 1999:
            category = 'Енергоносії'
        elif num >= 1000:
            category = 'Інше устаткування'

        # ── С100-xxxx: sub-code determines category ───────────────
        elif num == 100:
            sub_match = re.search(r'\d{3,4}[-\s]*(\d{4,6})', code_clean)
            sub = int(sub_match.group(1)) if sub_match else 0
            if 1500 <= sub <= 1529:
                category = 'Електрообладнання'
            elif 1530 <= sub <= 1560:
                category = 'Кабельні системи'
            elif 1600 <= sub <= 1629:
                category = 'Охорона та сигналізація'
            elif 1630 <= sub <= 1699:
                category = 'Теплопостачання та опалення'
            elif 1700 <= sub <= 1799:
                category = 'Автоматизація (КВП)'
            elif 1900 <= sub <= 1999:
                category = 'Теплотехнічне устаткування'
            else:
                category = 'Електрообладнання'

        else:
            category = 'Матеріали будівельні'

        is_retail = is_monitorable(name, category)
        items.append({
            'code':       code,
            'name':       name,
            'unit':       unit,
            'qty':        qty,
            'unit_price': unit_price,
            'retail':     is_retail,
            'category':   category,
        })

    # silent in production — summary only to console
    print(f"Кошторис: {len(items)} унікальних позицій ({len(duplicates)} дублікатів)")
    if duplicates:
        print(f"\nДублікати ({len(duplicates)}):")
        for d in duplicates:
            print(f"  - {d[:80]}")
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
            return _parse_df(df)
        except Exception as e:
            raise ValueError(f"Не вдалось прочитати .xls файл: {e}. Спробуйте зберегти файл як .xlsx в Excel або АВК-5.")
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