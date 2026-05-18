"""
query_simplifier.py — turn spec-document material strings into short, search-engine-friendly queries.

Real-world input from cost-estimate documents looks like:

  "Болти із шестигранною головкою оцинковані, діаметр різьби 12-[14] мм"
  "Цвяхи будівельні з конічною головкою 4,0х100 мм"
  "Гіпсові в'яжучі Г-3"
  "Дріт сталевий низьковуглецевий різного призначення світлий, діаметр 4,0 мм"
  "Блоки віконні металопластикові, з двокамерним склопакетом"
  "Щиток розподільчий навісний HАGЕR СОSMОS VS112РD"

These do not match e-commerce product titles. ``simplify_label`` returns a
short ranked list of candidate search queries to try, from most specific to
most generic. Designed to be used by parsers as a fallback chain when the
full label returns no results.

Public API:
    simplify_label(label, max_variants=4) -> list[str]
"""

from __future__ import annotations

import re
from typing import Iterable

# ── Vocabulary ────────────────────────────────────────────────

# Connectives and prepositions — always dropped.
_CONNECTIVES = {
    "із", "iз", "з", "зі", "у", "в", "на", "при", "над", "під", "за",
    "та", "і", "або", "й",
    "по", "до", "від", "до",
    "по-",
}

# Generic adjectives that add no information to a search query.
_NOISE_WORDS = {
    "різного", "призначення", "нормальної", "точності",
    "будівельний", "будівельна", "будівельне", "будівельні",
    "технічний", "технічна", "технічне", "технічні",
    "звичайний", "звичайна", "звичайне", "звичайні",
    "загальний", "загальна", "загальне", "загальні",
    "стандартний", "стандартна", "стандартне", "стандартні",
    "марка", "марки", "сорт", "сорту", "тип", "типу",
    "вид", "виду", "клас", "класу", "розмір",
    "наявності", "штук", "штука", "штуки", "комплект", "комплекту",
    "примітки", "примітка",
}

# Boilerplate noun-phrase fillers like "з конічною головкою".
_HEAD_DESCRIPTORS = {
    "з конічною головкою": "",
    "із конічною головкою": "",
    "з плоскою головкою": "",
    "із плоскою головкою": "",
    "з напівкруглою головкою": "",
    "із напівкруглою головкою": "",
    "з шестигранною головкою": "шестигранний",
    "із шестигранною головкою": "шестигранний",
}

# Spec phrases that we want to KEEP as adjectives.
_KEEP_ADJECTIVES = {
    "оцинкований", "оцинкована", "оцинковане", "оцинковані",
    "нержавіючий", "нержавіюча", "нержавіюче", "нержавіючі",
    "чорний", "чорна", "чорне", "чорні",
    "білий", "біла", "біле", "білі",
    "сталевий", "сталева", "сталеве", "сталеві",
    "мідний", "мідна", "мідне", "мідні",
    "алюмінієвий", "алюмінієва", "алюмінієве", "алюмінієві",
    "пластиковий", "пластикова", "пластикове", "пластикові",
    "металопластиковий", "металопластикова", "металопластикове", "металопластикові",
    "армований", "армована", "армоване", "армовані",
    "клиновий", "клинова", "клинове", "клинові",
    "розпірний", "розпірна", "розпірне", "розпірні",
    "шестигранний", "шестигранна", "шестигранне", "шестигранні",
    "довгий", "довга", "довге", "довгі",
    "короткий", "коротка", "коротке", "короткі",
    "фасадний", "фасадна", "фасадне", "фасадні",
    "стіновий", "стінова", "стінове", "стінові",
    "вуличний", "вулична", "вуличне", "вуличні",
    "віконний", "віконна", "віконне", "віконні",
    "дверний", "дверна", "дверне", "дверні",
    "оптичний", "оптична", "оптичне", "оптичні",
    "опалубковий", "опалубкова", "опалубкове", "опалубкові",
    "теплий", "тепла", "тепле", "теплі",
    "холодний", "холодна", "холодне", "холодні",
    "тактильний", "тактильна", "тактильне", "тактильні",
    "розподільчий", "розподільча", "розподільче", "розподільчі",
    "розподільний", "розподільна", "розподільне", "розподільні",
    "навісний", "навісна", "навісне", "навісні",
    "вбудований", "вбудована", "вбудоване", "вбудовані",
    "заглиблений", "заглиблена", "заглиблене", "заглиблені",
    "монтажний", "монтажна", "монтажне", "монтажні",
    "гарячекатаний", "гарячекатана", "гарячекатане", "гарячекатані",
    "холоднокатаний", "холоднокатана", "холоднокатане", "холоднокатані",
    "негашений", "негашена", "негашене", "негашені",
    "хлорний", "хлорна", "хлорне", "хлорні",
    "бітумний", "бітумна", "бітумне", "бітумні",
    "морозостійкий", "морозостійка", "морозостійке", "морозостійкі",
    "індустрійний", "індустрійна", "індустрійне", "індустрійні",
    "канатний", "канатна", "канатне", "канатні",
    "зварювальний", "зварювальна", "зварювальне", "зварювальні",
    "низьковуглецевий", "низьковуглецева", "низьковуглецеве", "низьковуглецеві",
    "сурова", "суровий", "суре", "сурові",  # for fabric ("Бязь сурова")
    "вуглецевий", "вуглецева", "вуглецеве", "вуглецеві",
    "двокамерний", "двокамерна", "двокамерне", "двокамерні",
    "однокамерний", "однокамерна", "однокамерне", "однокамерні",
    "ламінований", "ламінована", "ламіноване", "ламіновані",
    "шумоізоляційний", "шумоізоляційна", "шумоізоляційне", "шумоізоляційні",
    "гідроізоляційний", "гідроізоляційна", "гідроізоляційне", "гідроізоляційні",
    "теплоізоляційний", "теплоізоляційна", "теплоізоляційне", "теплоізоляційні",
    "клеючий", "клеюча", "клеюче", "клеючі",
    "пластинчатий", "пластинчата", "пластинчате", "пластинчаті",
    "розбірний", "розбірна", "розбірне", "розбірні",
}


# ── Regex patterns ────────────────────────────────────────────

# Strip square-bracketed alternatives like "12-[14]"
_BRACKETS = re.compile(r"\[[^]]*\]")

# Parenthetical notes at end of label
_TRAIL_PARENS = re.compile(r"\s*\([^)]*\)\s*$", re.UNICODE)

# Apostrophes / quotes
_APOS = re.compile(r"[\u2019\u02bc\u0027`'']")

# Punctuation that should split the label into clauses
_CLAUSE_SPLIT = re.compile(r"[,;]")

# Whitespace collapse
_WS = re.compile(r"\s+")

# Hyphen / em-dash / minus normalisation
_DASH = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\-]")

# Size pattern: 12x25, 1,6х50, 4,0×100, etc. (cyrillic х / latin x / × all accepted)
_SIZE_PAT = re.compile(
    r"(?:\b|^)(?:[МMmМ]\s*)?(\d{1,4}(?:[,.]\d{1,3})?\s*(?:[xхХ×*]\s*\d{1,4}(?:[,.]\d{1,3})?)+)(?:\s*мм|\s*мм\.?)?",
    re.UNICODE,
)

# Standalone diameter / length specs like "діаметр 4,0 мм", "д=10мм", "L=2 м",
# or "діаметр різьби 12 мм" / "діаметр стрижня 6 мм". Allows up to two short
# qualifier words between the marker and the value (the inner words must not
# themselves contain digits to avoid eating a different spec). Also tolerates
# a dangling range marker like "12- мм" (e.g. after stripping "[14]").
_DIM_LABEL = re.compile(
    r"(?:діаметр|діам\.?|d|д)\s*[=:]?\s*"
    r"(?:[а-яa-zії'']{2,15}\s+){0,2}"   # up to 2 qualifier words (without digits)
    r"(\d+(?:[,.]\d+)?)"
    r"(?:\s*[-‒–—]\s*\d+(?:[,.]\d+)?)?"
    r"\s*[-‒–—]?\s*"                     # optional dangling range marker
    r"(?:мм|см|м)\b",
    re.IGNORECASE | re.UNICODE,
)
_LEN_LABEL = re.compile(
    r"(?:довжина|довж\.?|L)\s*[=:]?\s*(\d+(?:[,.]\d+)?)\s*(?:мм|см|м)\b",
    re.IGNORECASE | re.UNICODE,
)

# Brand / model codes — Latin-Cyrillic mix in ALL-CAPS plus digits/hyphens.
# Examples: VS112РD, БН-70/30, Г-3, ПЦ-500, СОSMОS, HАGЕR, М12х25, И-20А
_BRAND_TOKEN = re.compile(
    r"\b([A-ZА-ЯІЇЄҐ][A-ZА-ЯІЇЄҐ0-9/\-]{1,}(?:[А-ЯІЇЄҐ0-9][A-ZА-ЯІЇЄҐ0-9/\-]*)?)\b",
    re.UNICODE,
)


def _norm_ws(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _looks_like_brand(token: str) -> bool:
    """True if the token looks like a brand/model code (e.g. VS112РD, БН-70/30, Г-3)."""
    if len(token) < 2:
        return False
    if not any(c.isdigit() for c in token) and len(token) < 4:
        # Single Cyrillic letter or 2-letter ones — not informative
        return False
    # Must be predominantly uppercase + digits
    upper = sum(1 for c in token if c.isupper() or c.isdigit())
    return upper / max(1, len(token)) >= 0.6


def _extract_sizes(text: str) -> list[str]:
    """Pull out 'compact' size signatures like '12х25', '4,0х100'."""
    sizes: list[str] = []
    for m in _SIZE_PAT.finditer(text):
        s = m.group(1)
        s = _WS.sub("", s).replace(",", ".").replace("Х", "х").replace("X", "х").replace("x", "х").replace("×", "х")
        if s and s not in sizes:
            sizes.append(s)
    return sizes


def _extract_labeled_dimensions(text: str) -> list[str]:
    """Pull '4 мм' from 'діаметр 4,0 мм', '50 мм' from 'довжина 50 мм'."""
    out: list[str] = []
    for m in _DIM_LABEL.finditer(text):
        v = m.group(1).replace(",", ".")
        if v.endswith(".0"):
            v = v[:-2]
        out.append(f"{v} мм")
    for m in _LEN_LABEL.finditer(text):
        v = m.group(1).replace(",", ".")
        if v.endswith(".0"):
            v = v[:-2]
        out.append(f"{v} мм")
    return out


def _extract_brand_codes(text: str) -> list[str]:
    """Identify brand / model codes in the label."""
    seen: list[str] = []
    for m in _BRAND_TOKEN.finditer(text):
        tok = m.group(1)
        if not _looks_like_brand(tok):
            continue
        if tok in seen:
            continue
        seen.append(tok)
    return seen


def _strip_noise(text: str) -> str:
    """Lower-case and drop connective / boilerplate words."""
    out: list[str] = []
    for w in text.split():
        wl = w.lower().strip(".,;:")
        if not wl:
            continue
        if wl in _CONNECTIVES or wl in _NOISE_WORDS:
            continue
        out.append(w)
    return " ".join(out)


def _replace_head_descriptors(text: str) -> str:
    """Replace 'з шестигранною головкою' with 'шестигранний', drop other 'з ... головкою'.

    Tries the longer 'iз'-prefixed variants first so they win over their
    'з'-prefixed siblings (which would otherwise match inside 'із').
    """
    # Process longest patterns first to avoid 'iз'/'з' overlap bugs.
    for pattern in sorted(_HEAD_DESCRIPTORS, key=len, reverse=True):
        replacement = _HEAD_DESCRIPTORS[pattern]
        # Anchor on word boundaries (and a leading whitespace/word edge) so
        # that 'з шестигранною головкою' does NOT match the trailing
        # 'з' inside 'із'.
        regex = r"(?<![\wіїєґ])" + re.escape(pattern) + r"(?!\w)"
        text = re.sub(regex, replacement, text, flags=re.IGNORECASE)
    return _norm_ws(text)


def _first_noun_phrase(text: str) -> str:
    """Take the first comma-delimited clause — usually 'head noun + 1-2 adjectives'."""
    parts = _CLAUSE_SPLIT.split(text, maxsplit=1)
    return parts[0].strip()


def _keep_adjectives(words: Iterable[str], max_adj: int = 2) -> list[str]:
    out: list[str] = []
    for w in words:
        if w.lower() in _KEEP_ADJECTIVES and w not in out:
            out.append(w)
        if len(out) >= max_adj:
            break
    return out


def _content_words(text: str, max_words: int = 4) -> list[str]:
    """Split into significant content words — no connectives, no boilerplate."""
    cleaned = _strip_noise(text)
    words = cleaned.split()
    return words[:max_words]


def simplify_label(label: str, max_variants: int = 4) -> list[str]:
    """
    Reduce a spec-style material description to a ranked list of short
    search queries. Returns at most ``max_variants`` queries, most specific
    first.

    The original ``label`` is always returned as the first variant — callers
    typically try it first, then fall back through the remaining queries.

    Examples
    --------
    >>> simplify_label("Болти із шестигранною головкою оцинковані, діаметр різьби 12-[14] мм")
    ['Болти із шестигранною головкою оцинковані, діаметр різьби 12-[14] мм',
     'болти шестигранний оцинковані 12 мм',
     'болти оцинковані 12 мм',
     'болти']
    """
    if not label or not label.strip():
        return [label or ""]

    original = _norm_ws(str(label))
    variants: list[str] = [original]
    seen_lower = {original.lower()}

    def add(v: str) -> None:
        v = _norm_ws(v)
        if not v:
            return
        if v.lower() in seen_lower:
            return
        seen_lower.add(v.lower())
        variants.append(v)

    # Pre-clean: drop trailing parens, square brackets, apostrophes.
    # Square brackets are removed but their *contents* are kept (e.g.
    # "12-[14] мм" → "12-14 мм") so labelled dimensions inside aren't lost.
    work = _TRAIL_PARENS.sub("", original)
    work = _BRACKETS.sub(lambda m: m.group(0)[1:-1], work)
    work = _APOS.sub("", work)

    sizes = _extract_sizes(work)
    dims = _extract_labeled_dimensions(work)
    brands = _extract_brand_codes(work)

    head_clause = _first_noun_phrase(work)
    head_clause = _replace_head_descriptors(head_clause)
    head_words = _content_words(head_clause)

    if not head_words:
        # Fall back to the global first content word
        full_clean = _strip_noise(_replace_head_descriptors(work))
        head_words = full_clean.split()[:1]

    head_noun = head_words[0] if head_words else ""
    kept_adj = _keep_adjectives(head_words[1:])

    # Tail dimension to attach — prefer compact size, then labelled dim.
    tail = ""
    if sizes:
        tail = sizes[0]
    elif dims:
        tail = dims[0]

    # ── Build candidate queries ─────────────────────────────────
    # Variant 1: head + adjectives + size/brand
    parts1 = [head_noun] + kept_adj
    if brands:
        parts1.append(brands[0])
    if tail and tail not in " ".join(parts1):
        parts1.append(tail)
    if parts1:
        add(" ".join(parts1))

    # Variant 2: head + first kept adjective + size
    if kept_adj:
        parts2 = [head_noun, kept_adj[0]]
        if tail and tail not in " ".join(parts2):
            parts2.append(tail)
        add(" ".join(parts2))

    # Variant 3: head + size only
    if tail:
        add(f"{head_noun} {tail}")

    # Variant 4: head + brand only (helpful for branded items like HAGER)
    if brands:
        add(f"{head_noun} {brands[0]}")

    # Variant 5: head noun alone (last resort)
    if head_noun:
        add(head_noun)

    return variants[: max(1, max_variants)]


__all__ = ["simplify_label"]


# ── Smoke test ────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover — manual quick-check
    samples = [
        "Болти із шестигранною головкою оцинковані, діаметр різьби 12-[14] мм",
        "Цвяхи будівельні з конічною головкою 4,0х100 мм",
        "Цвяхи будівельні з плоскою головкою 1,6х50 мм",
        "Гіпсові в'яжучі Г-3",
        "Дріт сталевий низьковуглецевий різного призначення світлий, діаметр 4,0 мм",
        "Дріт оцинкований, для блискозахисту діаметр 8 мм",
        "Анкер шпилька клиновий розпірний М12х25",
        "Дюбель-шуруп 100х10мм",
        "Анкер 150мм",
        "Блоки віконні металопластикові, з двокамерним склопакетом",
        "Щиток розподільчий навісний HАGЕR СОSMОS VS112РD",
        "Блок РЕ/N-клем для 2-рядних боксів \"Hаgеr\" VZ463",
        "Утеплювач мінвата т=50 мм НГ",
        "Бітуми нафтові будівельні, марка БН-70/30",
        "Бязь сурова",
        "Розетка заглиблена для прихованої проводки",
    ]
    for s in samples:
        print(f"\n{s!r}")
        for v in simplify_label(s):
            print(f"  → {v}")
