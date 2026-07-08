"""
monitorable.py — Item-level monitorability detection for PriceScout.

Logic: permissive by default — everything is monitorable unless its label
matches a SKIP keyword.

SKIP_KW covers only items that genuinely do not exist on Ukrainian retail
building-material sites:
  - Energy/utility carriers (electricity, gasoline, fuel, water, gases)
  - Industrial rags / textile waste
  - Welding gases and industrial solvents
  - Sensors, automation instruments, fire/security alarm electronics
  - UPS, industrial batteries
  - Cranes / hoisting equipment
  - A handful of very specific non-retail misc items

Everything else — bolts, cables, steel profiles, valves, door hardware,
HVAC panels, insulation, paints, fasteners, etc. — should be tried on
suppliers. Worst case: the scraper returns "not found", which is fine.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ── TEMPORARY override (customer request, 2026-07): monitor EVERYTHING ──
# When MONITOR_ALL_ITEMS=1 (set in .env), is_monitorable() always returns
# True, so imports mark every item monitorable and the runner skips nothing.
# Existing DB rows are synced once at startup — see the 'monitor_all_mode'
# block in core/item_db._migrate().
# To restore the SKIP_KW blocklist: remove the line from .env (or set it
# to 0) and restart — the next startup recomputes monitorable from labels.
MONITOR_ALL: bool = os.getenv("MONITOR_ALL_ITEMS", "0") == "1"

# Items that are NOT findable on retail building suppliers.
# Keep this list SHORT — only things no retail construction site stocks.
SKIP_KW: list[str] = [
    # Energy / utility carriers
    "електроенергия",   # Russian form
    "електроенергія",   # Ukrainian form
    "бензин",
    "мастильні матеріали",
    "гідравлічна рідина",
    "стиснене повітря",
    "дрова",
    "пропан-бутан",
    "ацетилен",
    "кисень технічний",
    "гас для технічних",

    # Water
    "вода дистильована",
    "вода технічна",
    "^вода",

    # Industrial rags / textile waste
    "дрантя",
    "бязь сурова",
    "рядно",
    "клоччя",
    "очіс льняний",
    "нитки швейні",
    "серветки бавовняні",

    # Industrial solvents (items that appear as standalone chemicals, not in retail)
    "ацетон технічний",
    "уайт-спірит",
    "розчинник марки р-4",
    "ксилол нафтовий",
    "масло індустрійне",
    "оліфа натуральна",
    "дисперсія полівінілацетатна",
    "каніфоль",
    "вазелін технічний",
    "моногідрат літію",
    "тальк мелений",
    "графіт подрібнений",

    # Instruments / automation / sensors
    "датчик зовнішньої",
    "датчик температури",
    "датчик тиску",
    "реле перепаду",
    "реле тиску",
    "електронний регулятор",
    "теплообчислювач",
    "регулятор перепаду тиску",
    "електропривід",

    # Fire & security alarm electronics
    "сповіщувач пожежний",
    "приймально-контрольний прилад",
    "оповіщувач",
    "блок технологічного обліку",
    "модуль цифрового",
    "акустична система",
    "блок релейних",
    "пристрій комутаційний",

    # UPS / industrial batteries
    "джерело безперебійного",
    "підсилювач-мікшер",

    # Cranes & hoisting
    "штабелер",

    # Misc non-retail
    "бирка маркувальна",
    "рамка для написів",
    "кнопка к",
    "патрони д або",
    "патрони до пістолета",
    "тактильна стрічка",
    "тактильна табличка",
    "тактильні попереджувальні",
    "наліпка",
    "плитки тактильні",
    "грязезахисні грати",
    "пароніт",
    "папір шліфувальний",
    "просічно-витяжний лист",
]


def is_monitorable(label: str) -> bool:
    """Return True if *label* is likely findable on Ukrainian retail
    building-material sites.  Returns True by default (permissive);
    returns False only when the label clearly matches a SKIP keyword.

    TEMPORARY: when MONITOR_ALL_ITEMS=1 the blocklist is bypassed entirely
    and everything is monitorable (see module header)."""
    if MONITOR_ALL:
        return True
    if not label:
        return True
    lower = label.lower().strip()
    for kw in SKIP_KW:
        if kw.startswith("^"):
            # Anchored match: must start with the keyword (minus the ^)
            if lower.startswith(kw[1:].lower()):
                return False
        else:
            if kw.lower() in lower:
                return False
    return True
