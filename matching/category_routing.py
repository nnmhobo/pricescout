"""
Category-to-supplier routing for PriceScout.

Maps кошторис categories (derived from resource codes, see
parsers/category_codes.py) to the supplier IDs that realistically carry those
items, so a run doesn't waste requests and time sending cable queries to
general builders or boiler queries to a dry-mix shop.

Routing logic (see get_suppliers_for_item):
- Label contains a RETAIL_OVERRIDE_KW keyword → GENERAL_SUPPLIERS
- Otherwise CATEGORY_ROUTING[category] (unknown category → DEFAULT_SUPPLIERS):
  general materials → retail chains; plumbing / electrical / insulation /
  windows-doors → the subset with that section; heating & ventilation →
  ТеплоДiм (HVAC_SUPPLIERS); automation, energy, cranes … → [] (skipped,
  unless MONITOR_ALL_ITEMS=1 → DEFAULT_SUPPLIERS)
- Marketplaces (prom, olx) are appended after the specialists when enabled
- Always intersected with the suppliers enabled in the UI

NOTE: 'budpostach' appears only in HARDWARE_SUPPLIERS, which no rule uses,
so Будпостач is currently never routed (OVERVIEW.md, Known issue #15).
"""

from matching.monitorable import MONITOR_ALL

# Suppliers that carry GENERAL building materials (dry mixes, insulation, paint, fasteners)
GENERAL_SUPPLIERS = [
    "epicentr", "ars", "buddvir", "kub", "venbud", "m2", "vista", "megatrade", "budia"
]

# Marketplace aggregators — broad coverage, lower data quality. Listed after
# the specialist retailers in every routing rule so cards from real stores
# rank first when the user enables them.
MARKETPLACE_SUPPLIERS = [
    "prom", "olx",
]

# Specialised HVAC / heating supplier (added 2026-05-16) — fills the empty
# 'Теплопостачання', 'Вентиляція', 'Теплотехнічне устаткування' categories.
HVAC_SUPPLIERS = [
    "teplodim",
]

# Suppliers with electrical/cable sections
ELECTRICAL_SUPPLIERS = [
    "epicentr", "kub", "m2"
]

# Suppliers with plumbing sections
PLUMBING_SUPPLIERS = [
    "epicentr", "kub", "venbud", "m2", "vista", "buddvir"
]

# Suppliers with insulation / thermal materials
INSULATION_SUPPLIERS = [
    "epicentr", "ars", "buddvir", "kub", "venbud", "m2", "vista", "budia"
]

# Suppliers with fasteners/hardware (Будпостач is good here)
HARDWARE_SUPPLIERS = [
    "epicentr", "kub", "buddvir", "budpostach", "m2", "vista"
]

# Category routing map: category name → list of supplier IDs to try
CATEGORY_ROUTING = {
    # ── General building materials — try all retail suppliers ─────
    "Будівельні матеріали":         GENERAL_SUPPLIERS,
    "Підлоги, покрівлі, покриття":  GENERAL_SUPPLIERS,
    "Пиломатеріали":                GENERAL_SUPPLIERS,
    "Теплоізоляція":                INSULATION_SUPPLIERS,
    "Арматура та металоконструкції": ["epicentr", "ars", "kub", "m2", "vista"],
    "Металоконструкції":            ["epicentr", "ars", "kub", "m2"],
    "Вікна та двері":               ["epicentr", "kub", "m2", "vista"],
    "Захист конструкцій":           GENERAL_SUPPLIERS,
    "Конструктивні роботи":         GENERAL_SUPPLIERS,
    "Конструкції збірні":           ["epicentr", "kub"],

    # ── Plumbing / pipes ─────────────────────────────────────────
    "Трубопроводи та фітинги":      PLUMBING_SUPPLIERS,
    "Мережі (водопостачання, газ)": PLUMBING_SUPPLIERS,
    "Санітарно-технічне устаткування": ["epicentr", "kub", "m2"],

    # ── Electrical — limited suppliers ───────────────────────────
    "Електрообладнання":            ELECTRICAL_SUPPLIERS,
    "Кабельні системи":             ELECTRICAL_SUPPLIERS,
    "Охорона та сигналізація":      ELECTRICAL_SUPPLIERS,

    # ── HVAC / heating / automation — specialised supplier ──────
    # ТеплоДiм (HVAC_SUPPLIERS) covers boilers, radiators, convectors, pumps
    # since 2026-05-16. General builders still skipped (no stock there).
    "Теплопостачання та опалення":  HVAC_SUPPLIERS,
    "Вентиляція та кондиціонування": HVAC_SUPPLIERS,
    "Теплотехнічне устаткування":   HVAC_SUPPLIERS,
    "Автоматизація (КВП)":          [],   # instrumentation — skip
    "Енергоносії":                  [],   # fuel/energy — skip
    "Спеціальні роботи":            [],   # skip
    "Вантажопідйомне устаткування": [],   # cranes/hoists — skip
    "Інше устаткування":            [],   # skip
}

# Fallback for unknown categories
DEFAULT_SUPPLIERS = GENERAL_SUPPLIERS

# Labels that clearly indicate a retail building material regardless of the
# category field (which may be wrong or generic). Defined at module level so
# the list is built once, not on every routing call.
RETAIL_OVERRIDE_KW = [
    "шпаклівка", "шпакл", "штукатурка", "грунтовка", "ґрунтовка",
    "грунт-фарба", "фарба", "клей для плитки", "клей для піноп",
    "клеюча суміш", "суміш клеюча", "суміш для штукатурки",
    "суміш для приклеювання", "стяжка", "наливна підлога",
    "самовирівн", "затирка", "гідроізоляція", "утеплювач",
    "пінопласт", "мінвата", "базальтова вата", "гіпсокартон",
    "профіль cd", "профіль ud", "саморіз", "дюбель",
    "монтажна піна", "герметик", "цемент", "пісок",
    "ceresit", "knauf", "baumit", "polimin", "siltek",
]


def get_suppliers_for_item(item: dict, all_supplier_ids: list) -> list:
    """
    Given an item dict (with 'category' field) and the list of currently
    enabled supplier IDs, return the filtered list of supplier IDs to use.

    Always intersects with active_ids so disabled suppliers are never used.

    Marketplace aggregators (prom, olx) — if enabled by the user — are
    appended to whatever specialist list applies, including the explicit-
    skip categories: an OLX listing for industrial cable is still a
    plausible quote even when no general builder stocks it. The marketplace
    suffix runs after the specialists so real retailer cards win ties.
    """
    category = (item.get("category") or "").strip()
    label = (item.get("label") or "").lower()
    enabled_set = set(all_supplier_ids)
    marketplace_tail = [sid for sid in MARKETPLACE_SUPPLIERS if sid in enabled_set]

    # Override: if the item label clearly indicates a retail building material,
    # send it to all general suppliers regardless of the (possibly wrong) category.
    for kw in RETAIL_OVERRIDE_KW:
        if kw in label:
            specialists = [sid for sid in GENERAL_SUPPLIERS if sid in enabled_set]
            return specialists + marketplace_tail

    routed = CATEGORY_ROUTING.get(category, DEFAULT_SUPPLIERS)

    if not routed:
        # Category was explicitly mapped to empty (industrial/specialised
        # supplies no retailer carries). Marketplaces are the only realistic
        # source for these — try them if enabled, otherwise skip.
        # TEMPORARY (MONITOR_ALL_ITEMS, customer request 2026-07): the
        # customer wants EVERY item searched, so fall back to the general
        # retailers instead of skipping. Worst case is a clean "not found"
        # per supplier, and SKIP_STALE_DAYS suppresses repeats for a month.
        if not MONITOR_ALL:
            return marketplace_tail
        routed = DEFAULT_SUPPLIERS

    # Intersect with what's currently enabled, preserving routing order,
    # then append marketplaces so they probe AFTER specialists.
    specialists = [sid for sid in routed if sid in enabled_set]
    return specialists + marketplace_tail