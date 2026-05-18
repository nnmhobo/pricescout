"""
Generate search query variations for Ukrainian building materials.

Given a label like "Фарба грунтувальна", generates multiple alternatives
to maximize chances of finding the product on different sites where it
may be listed under a different name.
"""

import re


# Pure character-level UA → RU letter substitution: "Гіпсокартон" -> "Гипсокартон",
# "Шпаклівка" -> "Шпаклевка-ish form". Useful on OLX / Prom where ~half of
# Ukrainian listings are typed in Russian. We collapse the diacritic-bearing
# Ukrainian letters to their Russian counterparts and the matcher already
# treats them interchangeably afterwards.
_UA_TO_RU_TRANS = str.maketrans({
    "і": "и", "І": "И",
    "ї": "и", "Ї": "И",
    "є": "е", "Є": "Е",
    "ґ": "г", "Ґ": "Г",
    "'": "",  "’": "",  # apostrophes — most Russian texts drop them
})


def _ua_to_ru(text: str) -> str:
    return text.translate(_UA_TO_RU_TRANS)

# Synonym map: word → list of alternatives (first = most common on sites)
SYNONYMS = {
    # Paint/primer
    "фарба": ["краска", "фарба", "емаль"],
    "грунтувальна": ["грунт", "грунтовочна", "ґрунтувальна"],
    "грунтовка": ["ґрунтовка", "грунт", "праймер", "грунт-фарба"],
    "ґрунтовка": ["грунтовка", "грунт", "праймер", "грунт-фарба"],
    "емаль": ["эмаль", "емаль", "фарба"],

    # Plaster/putty
    "штукатурка": ["штукатурка", "декоративна штукатурка"],
    "шпаклівка": ["шпаклевка", "шпаклівка", "шпатлівка"],
    "фінішна": ["финишная", "фінішна", "finish", "фініш"],
    "стартова": ["стартовая", "стартова", "start", "старт"],

    # Adhesives
    "клей": ["клей", "клеюча суміш"],
    "суміш": ["смесь", "суміш"],
    "клеюча": ["клеевая", "клеюча"],

    # Insulation
    "утеплювач": ["утеплитель", "утеплювач", "теплоізоляція"],
    "пінопласт": ["пенопласт", "пінопласт", "EPS"],
    "мінвата": ["минвата", "мінвата", "мінеральна вата", "базальтова вата"],

    # Drywall
    "гіпсокартон": ["гипсокартон", "гіпсокартон", "ГКЛ"],

    # Cement
    "цемент": ["цемент", "портландцемент"],

    # Fasteners
    "саморіз": ["саморез", "саморіз", "шуруп"],
    "дюбель": ["дюбель", "дюбель-шуруп"],

    # General filler words to drop
    "будівельна": ["строительная", "будівельна"],
    "для": [],
    "та": [],
    "або": [],
    "із": [],
    "з": [],
}

# Compound word patterns: "X Y-на/ий/а" → "Y-X" (hyphenated product names)
# e.g., "фарба грунтувальна" → "грунт-фарба"
COMPOUND_ROOTS = {
    "грунтувальна": "грунт",
    "грунтувальний": "грунт",
    "ґрунтувальна": "грунт",
    "штукатурна": "штукатурка",
    "шпаклювальна": "шпаклівка",
    "клеюча": "клей",
    "гідроізоляційна": "гідроізоляція",
    "теплоізоляційна": "теплоізоляція",
    "антикорозійна": "антикор",
}


def generate_variations(label: str, max_variations: int = 6) -> list[str]:
    """
    Generate up to `max_variations` search query alternatives from a label.
    Returns a list of strings to try in order (first = most likely to work).
    """
    if not label or not label.strip():
        return [label or ""]

    original = label.strip()
    variations = []
    seen_lower = set()

    def _add(v: str):
        if len(variations) >= max_variations:
            return
        v = v.strip()
        if v and v.lower() not in seen_lower:
            seen_lower.add(v.lower())
            variations.append(v)

    _add(original)

    # 0a. Ukrainian letter → Russian letter substitution. Many Ukrainian
    # retail listings (especially on OLX / Prom / re-uploaded ProductFeeds)
    # are typed in Russian. Adding the Russian-letter form as an early
    # variant lets the search engine find them without sacrificing a slot
    # for a more specific guess.
    ru_variant = _ua_to_ru(original)
    if ru_variant != original:
        _add(ru_variant)

    # 1. Brand code expansion (highest priority — most specific). Added BEFORE
    # simplification so it is never dropped when max_variations is small.
    code_match = re.search(r'(?:^|\s)([СCс][ТTт])[\-\s]+(\d{1,3})', original, re.IGNORECASE)
    if code_match:
        _add(f"Ceresit CT {code_match.group(2)}")
        _add(f"CT-{code_match.group(2)}")

    # 1b. Hyphen-tokenization: many search engines treat "Грунт-фарба" as
    # a single literal token and miss it when products are listed as
    # "Грунт фарба" (with a space). Add a variant that splits any
    # word-internal hyphen between letters (skips number-hyphen ranges like
    # "12-14" and brand codes like "CT-225"/"ПФ-115" which we handle above).
    if re.search(r"[A-Za-zА-Яа-яІіЇїЄєҐґ\u2010-\u2015]-(?=[A-Za-zА-Яа-яІіЇїЄєҐґ])", original):
        dehyphenated = re.sub(
            r"([A-Za-zА-Яа-яІіЇїЄєҐґ])[\-\u2010-\u2015](?=[A-Za-zА-Яа-яІіЇїЄєҐґ])",
            r"\1 ",
            original,
        )
        _add(dehyphenated)

    # Generic paint/primer brand codes (ГФ-021, ПФ-115, ХС-010, МА-025, …)
    paint_code = re.search(
        r"(?:^|\s)(ГФ|ПФ|ХС|МА|МО|КО|ВД|АК|НЦ)[\-\s]*(\d{1,4})\b",
        original, re.IGNORECASE,
    )
    if paint_code:
        prefix = paint_code.group(1).upper()
        num = paint_code.group(2)
        _add(f"{prefix}-{num}")
        _add(f"{prefix} {num}")

    # 0. Spec-style simplification — turn long, boiler-plate descriptions
    # ("Болти із шестигранною головкою оцинковані, діаметр різьби 12 мм")
    # into shorter, e-commerce-friendly queries ("Болти оцинковані 12",
    # "Болти 12", "Болти"). Inserted near the top of the candidate list
    # so that parsers fall back to them before random word reorders.
    try:
        from scrapers.query_simplifier import simplify_label
        for short in simplify_label(original, max_variants=5):
            _add(short)
            if len(variations) >= max_variations:
                return variations[:max_variations]
    except Exception:
        pass

    words = original.lower().split()
    significant = [w for w in words if len(w) >= 4]

    # 2. Compound hyphenated form: "фарба грунтувальна" → "грунт-фарба"
    for word in significant:
        root = COMPOUND_ROOTS.get(word)
        if root:
            # Find the noun it modifies (usually the other significant word)
            nouns = [w for w in significant if w != word]
            if nouns:
                _add(f"{root}-{nouns[0]}")
                _add(f"{root} {nouns[0]}")  # also without hyphen

    # 3. Word reorder
    if len(significant) >= 2:
        _add(f"{significant[1]} {significant[0]}")

    # 4. Synonym substitution
    for word in significant[:2]:
        alts = SYNONYMS.get(word, [])
        for alt in alts:
            if alt.lower() != word:
                new_q = original.lower().replace(word, alt, 1)
                _add(new_q)
                if len(variations) >= max_variations:
                    return variations[:max_variations]

    # 5. Just the root/stem of the adjective + noun
    for word in significant:
        root = COMPOUND_ROOTS.get(word)
        if root:
            _add(root)

    # 6. Longest significant word alone (last resort)
    if significant:
        longest = max(significant, key=len)
        if len(longest) >= 5:
            _add(longest)

    return variations[:max_variations]
