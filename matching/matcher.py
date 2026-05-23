"""
PriceScout — Smart fuzzy matcher for product names.

Provides robust product name matching that handles:
- Different languages (Ukrainian, Russian, Latin transliterations)
- Partial matches, prefixes, stems
- Special characters, hyphens, case differences
- SEO-enriched product titles with extra words
- Combined scoring via rapidfuzz (partial_ratio, token_sort_ratio, token_set_ratio)
- Key-token verification to reject irrelevant matches
- Debug logging with top-N candidates

Public API:
  - normalize_text(text)           -> str
  - calculate_match_score(query, candidate) -> float  (0..100)
  - find_best_match(query, candidates, ...) -> MatchResult | None
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Sequence

from rapidfuzz import fuzz

logger = logging.getLogger("matcher")


# ── Transliteration tables ────────────────────────────────────

# Ukrainian/Russian Cyrillic -> Latin (ISO 9 inspired, practical)
_CYR_TO_LAT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g",
    "д": "d", "е": "e", "є": "ye", "ж": "zh", "з": "z",
    "и": "y", "і": "i", "ї": "yi", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ь": "", "ъ": "", "ю": "yu", "я": "ya",
    "ы": "y", "э": "e", "ё": "yo",
}

# Latin -> Cyrillic (reverse, simplified for matching)
_LAT_TO_CYR: dict[str, str] = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д",
    "e": "е", "z": "з", "i": "и", "y": "и", "k": "к",
    "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
    "r": "р", "s": "с", "t": "т", "u": "у", "f": "ф",
    "c": "к", "h": "х", "w": "в", "x": "кс", "j": "й",
    "q": "к",
}

# Multi-char Latin -> Cyrillic
_LAT_DIGRAPHS_TO_CYR: list[tuple[str, str]] = [
    ("shch", "щ"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"),
    ("ts", "ц"), ("kh", "х"), ("yu", "ю"), ("ya", "я"),
    ("ye", "є"), ("yi", "ї"), ("yo", "ё"),
]


def transliterate_to_latin(text: str) -> str:
    """Convert Cyrillic text to Latin transliteration."""
    result = []
    for ch in text:
        low = ch.lower()
        if low in _CYR_TO_LAT:
            mapped = _CYR_TO_LAT[low]
            result.append(mapped)
        else:
            result.append(low)
    return "".join(result)


def transliterate_to_cyrillic(text: str) -> str:
    """Convert Latin text to Cyrillic (best-effort)."""
    text = text.lower()
    # Apply digraphs first (longest match)
    for lat, cyr in _LAT_DIGRAPHS_TO_CYR:
        text = text.replace(lat, cyr)
    result = []
    for ch in text:
        if ch in _LAT_TO_CYR:
            result.append(_LAT_TO_CYR[ch])
        else:
            result.append(ch)
    return "".join(result)


# ── Normalization ─────────────────────────────────────────────

# Characters to normalize for fuzzy matching only.
# Collapses Ukrainian / Russian letter variants that humans treat as
# interchangeable in retail product names (e.g. "і" vs "и", "ё" vs "е")
# so that "Утеплювач" matches "Утеплитель" and "мінвата" matches
# "минвата" without paying a similarity penalty.
_NORM_MAP = str.maketrans({
    "ё": "е",
    "ґ": "г",
    "ї": "и",
    "і": "и",
    "є": "е",
    "ы": "и",
    "э": "е",
    "ъ": "",
    "ь": "",
    "'": "",
    "\u2019": "",   # right single quotation mark
    "\u02bc": "",   # modifier letter apostrophe
    "\u0027": "",   # apostrophe
})

_SPECIAL_CHARS = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_SPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """
    Normalize text for fuzzy comparison:
    - lowercase
    - replace ё→е, ґ→г, remove apostrophes
    - strip special characters (hyphens, dots, commas, etc.)
    - collapse multiple spaces
    - strip leading/trailing whitespace
    """
    if not text:
        return ""
    result = text.lower()
    result = result.translate(_NORM_MAP)
    result = _SPECIAL_CHARS.sub(" ", result)
    result = _MULTI_SPACE.sub(" ", result)
    return result.strip()


def _tokenize(text: str) -> list[str]:
    """Split normalized text into tokens (words), drop very short ones."""
    if not text:
        return []
    normalized = normalize_text(text)
    return [w for w in normalized.split() if len(w) >= 2]


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[а-яА-ЯіІїЇєЄґҐёЁ]", text))


def _has_latin(text: str) -> bool:
    return bool(re.search(r"[a-zA-Z]", text))


# ── Scoring ───────────────────────────────────────────────────

# Weights for combining rapidfuzz scores
_W_PARTIAL     = 0.35
_W_TOKEN_SORT  = 0.30
_W_TOKEN_SET   = 0.35

# Bonus for exact key-token containment
_EXACT_TOKEN_BONUS = 15.0

# Minimum score threshold (0-100)
DEFAULT_THRESHOLD = 50

# Synonyms for retail-construction terms — symmetric. If any synonym of a
# query token appears in the candidate (or vice versa), the tokens are
# considered to match. Tokens are stored after `normalize_text` (so they
# all use "и" instead of "і"/"ї", "е" instead of "є"/"ё", etc.).
_SYNONYM_GROUPS: list[set[str]] = [
    # Insulation
    {"утеплювач", "утеплитель", "теплоизоляция", "теплоизоляция",
     "минвата", "минеральная", "минеральна", "вата",
     "базальтовая", "базальтова", "стекловата", "скловата"},
    {"пинопласт", "пенопласт", "пенополистирол", "пинополистирол", "eps"},
    # Drywall
    {"гипсокартон", "гипсокартонная", "гкл", "гипсокартонн", "knauf"},
    # Primer
    {"грунтовка", "грунт", "праймер", "грунтуюча", "грунтувальна",
     "грунтовочная", "грунт-фарба", "грунт-краска"},
    # Paint
    {"фарба", "краска", "эмаль", "емаль"},
    # Putty
    {"шпаклевка", "шпаклювання", "шпатлевка", "шпаклевочная",
     "шпаклювальна", "шпатлювальна", "шпаклевочной", "шпаклевочную",
     "шпаклевочная", "шпаклювальна", "шпакливка", "шпакл"},
    # Adhesive
    {"клей", "клеящая", "клеюча", "клеящий", "клеевая", "adhesive"},
    # Mixture
    {"смесь", "сумиш", "строительная", "будивельна"},
    # Fasteners
    {"саморез", "самориз", "шуруп", "screw"},
    {"дюбель", "дюбель-шуруп", "анкер"},
    # Tiles
    {"плитка", "кафель", "керамогранит", "плити"},
    # Cement
    {"цемент", "портландцемент"},
    # Polyurethane foam
    {"пина", "пена", "foam"},
    {"монтажная", "монтажна"},
    # Profiles & drywall accessories
    {"профиль", "профиль"},
    # Plaster
    {"штукатурка", "штукатурки", "plaster"},
    # Sealant
    {"герметик", "sealant"},
    # Self-leveling
    {"стяжка", "наливна", "наливной", "самовиривн", "самовыравн"},
]

_SYNONYM_MAP: dict[str, set[str]] = {}
for _group in _SYNONYM_GROUPS:
    for _w in _group:
        _SYNONYM_MAP.setdefault(_w, set()).update(_group)


def _expand_synonyms(tokens: list[str]) -> set[str]:
    """Return the union of all synonyms of every input token (including
    the tokens themselves). Tokens must already be normalized."""
    out: set[str] = set()
    for t in tokens:
        out.add(t)
        for syn in _SYNONYM_MAP.get(t, ()):
            out.add(syn)
    return out


def calculate_match_score(query: str, candidate: str) -> float:
    """
    Calculate a combined fuzzy match score (0-100) between a search
    query and a candidate product title.

    Uses:
    - rapidfuzz.fuzz.partial_ratio  (good for substring matches)
    - rapidfuzz.fuzz.token_sort_ratio (order-independent)
    - rapidfuzz.fuzz.token_set_ratio  (handles extra/missing words)
    - Exact key-token bonus
    - Cross-language transliteration matching

    Returns a float 0..100+  (can exceed 100 due to bonuses).
    """
    if not query or not candidate:
        return 0.0

    norm_q = normalize_text(query)
    norm_c = normalize_text(candidate)

    if not norm_q or not norm_c:
        return 0.0

    # --- Direct comparison ---
    score_direct = _combined_fuzz(norm_q, norm_c)

    # --- Transliteration comparison ---
    # If query is Cyrillic but candidate has Latin parts (or vice versa),
    # compare in both alphabets and take the best.
    score_translit = 0.0

    q_has_cyr = _has_cyrillic(query)
    q_has_lat = _has_latin(query)
    c_has_cyr = _has_cyrillic(candidate)
    c_has_lat = _has_latin(candidate)

    if q_has_cyr and c_has_lat:
        # Compare query-as-latin vs candidate
        q_lat = normalize_text(transliterate_to_latin(query))
        c_lat = normalize_text(candidate)
        score_translit = max(score_translit, _combined_fuzz(q_lat, c_lat))

    if q_has_lat and c_has_cyr:
        # Compare query-as-cyrillic vs candidate
        q_cyr = normalize_text(transliterate_to_cyrillic(query))
        c_cyr = normalize_text(candidate)
        score_translit = max(score_translit, _combined_fuzz(q_cyr, c_cyr))

    if q_has_cyr and c_has_cyr:
        # Both Cyrillic — also try Latin-Latin comparison for brand codes
        q_lat = normalize_text(transliterate_to_latin(query))
        c_lat = normalize_text(transliterate_to_latin(candidate))
        score_translit = max(score_translit, _combined_fuzz(q_lat, c_lat))

    if q_has_lat and c_has_lat:
        # Both Latin — also try Cyrillic-Cyrillic comparison
        q_cyr = normalize_text(transliterate_to_cyrillic(query))
        c_cyr = normalize_text(transliterate_to_cyrillic(candidate))
        score_translit = max(score_translit, _combined_fuzz(q_cyr, c_cyr))

    base_score = max(score_direct, score_translit)

    # --- Exact key-token bonus ---
    # If the query (after normalization) appears as a substring in the
    # candidate, give a significant bonus. This rewards
    # "Антигрибок" found in "Грунтовка Rolax Антигрибок 10 л".
    bonus = 0.0
    query_tokens = _tokenize(query)

    if norm_q in norm_c:
        bonus += _EXACT_TOKEN_BONUS

    # Also check transliterated containment
    if q_has_cyr and c_has_lat:
        q_lat = normalize_text(transliterate_to_latin(query))
        c_lat_norm = normalize_text(candidate)
        if q_lat and q_lat in c_lat_norm:
            bonus += _EXACT_TOKEN_BONUS
    if q_has_lat and c_has_cyr:
        q_cyr = normalize_text(transliterate_to_cyrillic(query))
        c_cyr_norm = normalize_text(candidate)
        if q_cyr and q_cyr in c_cyr_norm:
            bonus += _EXACT_TOKEN_BONUS

    # Per-token containment: reward if significant query tokens are
    # found as substrings in the candidate (handles prefix/stem matches).
    cand_tokens = _tokenize(candidate)
    cand_expanded = _expand_synonyms(cand_tokens) if cand_tokens else set()
    if query_tokens and cand_tokens:
        matched_tokens = 0
        for qt in query_tokens:
            if len(qt) < 3:
                continue
            matched = False
            for ct in cand_tokens:
                # exact match
                if qt == ct:
                    matched_tokens += 1
                    matched = True
                    break
                # prefix/stem match (min 4 chars)
                if len(qt) >= 4 and len(ct) >= 4:
                    if ct.startswith(qt[:4]) or qt.startswith(ct[:4]):
                        matched_tokens += 0.7
                        matched = True
                        break
            if not matched:
                # Synonym fallback — if a synonym of the query token
                # appears (directly or via its synonyms) in the candidate.
                qt_syns = _SYNONYM_MAP.get(qt)
                if qt_syns and (qt_syns & cand_expanded):
                    matched_tokens += 0.7
        if query_tokens:
            token_ratio = matched_tokens / len(query_tokens)
            bonus += token_ratio * 10.0  # up to +10 for full token coverage

    return min(base_score + bonus, 120.0)


def _combined_fuzz(s1: str, s2: str) -> float:
    """Weighted combination of rapidfuzz scores."""
    pr = fuzz.partial_ratio(s1, s2)
    tsr = fuzz.token_sort_ratio(s1, s2)
    tsetr = fuzz.token_set_ratio(s1, s2)
    return pr * _W_PARTIAL + tsr * _W_TOKEN_SORT + tsetr * _W_TOKEN_SET


# ── Key-token verification ────────────────────────────────────

_SIG_NUM_RE = re.compile(r"\d{2,}", re.UNICODE)


def _verify_key_tokens(query: str, candidate: str, min_key_overlap: float = 0.4) -> bool:
    """
    Verify that at least `min_key_overlap` fraction of the query's
    significant tokens are present (or prefix-present) in the candidate.

    Also checks that important numbers from the query (product codes like
    17, 85, 500, 137) are present in the candidate to avoid matching
    CT-85 when searching for CT-17.

    This prevents accepting completely unrelated products that happen
    to score high on generic words.

    For single-token queries, requires the token to be found as a
    substring or a close prefix match in the candidate.
    """
    q_tokens = _tokenize(query)
    c_tokens = _tokenize(candidate)

    if not q_tokens:
        return True  # nothing to verify

    # Filter to significant tokens (4+ chars)
    sig_tokens = [t for t in q_tokens if len(t) >= 4]
    if not sig_tokens:
        sig_tokens = q_tokens  # fallback to all tokens

    norm_c = normalize_text(candidate)

    # Also prepare transliterated versions
    c_lat = normalize_text(transliterate_to_latin(candidate)) if _has_cyrillic(candidate) else ""
    c_cyr = normalize_text(transliterate_to_cyrillic(candidate)) if _has_latin(candidate) else ""

    # Expand candidate tokens with synonyms once — used for symmetric
    # synonym matching (e.g. query "утеплювач" ↔ candidate "минеральна").
    c_tokens_expanded = _expand_synonyms(c_tokens)

    matched = 0
    for qt in sig_tokens:
        found = False

        # Direct substring check
        if qt in norm_c:
            found = True
        # Transliterated substring check
        elif c_lat:
            qt_lat = normalize_text(transliterate_to_latin(qt)) if _has_cyrillic(qt) else qt
            if qt_lat and qt_lat in c_lat:
                found = True
        elif c_cyr:
            qt_cyr = normalize_text(transliterate_to_cyrillic(qt)) if _has_latin(qt) else qt
            if qt_cyr and qt_cyr in c_cyr:
                found = True

        if not found:
            # Prefix match against candidate tokens
            for ct in c_tokens:
                if len(qt) >= 4 and len(ct) >= 4:
                    if ct.startswith(qt[:4]) or qt.startswith(ct[:4]):
                        found = True
                        break
                    # Also check transliterated prefix
                    qt_lat = transliterate_to_latin(qt) if _has_cyrillic(qt) else qt
                    ct_lat = transliterate_to_latin(ct) if _has_cyrillic(ct) else ct
                    if len(qt_lat) >= 4 and len(ct_lat) >= 4:
                        if ct_lat.startswith(qt_lat[:4]) or qt_lat.startswith(ct_lat[:4]):
                            found = True
                            break

        if not found:
            # Synonym match — if any synonym of the query token is
            # in the candidate tokens (or any candidate token's synonyms
            # contain the query token).
            qt_syns = _SYNONYM_MAP.get(qt)
            if qt_syns and (qt_syns & c_tokens_expanded):
                found = True

        if found:
            matched += 1

    overlap = matched / len(sig_tokens)
    if overlap < min_key_overlap:
        return False

    # Numeric code verification: if the query contains significant numbers
    # (product codes like 17, 137, 500), the candidate must also contain them.
    # This prevents matching CT-85 when searching for CT-17.
    query_nums = set(_SIG_NUM_RE.findall(query))
    if query_nums:
        candidate_nums = set(_SIG_NUM_RE.findall(candidate))
        # At least one query number must be present in the candidate
        if not query_nums & candidate_nums:
            return False

    return True


# ── Main API ──────────────────────────────────────────────────

@dataclass
class MatchResult:
    """Result of find_best_match()."""
    name: str              # Original (unnormalized) candidate name
    score: float           # Combined match score (0-100+)
    index: int             # Index in the original candidates list
    all_scores: list[tuple[float, str]]  # Top candidates: [(score, name), ...]


def find_top_matches(
    query: str,
    candidates: Sequence[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    top_n: int = 5,
    log_fn=None,
) -> list[MatchResult]:
    """
    Return up to ``top_n`` candidates ordered by score (best first) that
    both clear ``threshold`` AND pass key-token verification.

    Callers that want a *single* result can use :func:`find_best_match`;
    callers that need to fall through to the next-best match when the
    current one has no usable price/URL should iterate this list instead.
    """
    if not query or not candidates:
        return []

    scored: list[tuple[float, int, str]] = []
    for i, candidate in enumerate(candidates):
        if not candidate or not candidate.strip():
            continue
        sc = calculate_match_score(query, candidate)
        scored.append((sc, i, candidate))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    _log_candidates(query, scored[:top_n], log_fn)

    accepted: list[MatchResult] = []
    all_scores = [(s, n) for s, _, n in scored[:top_n]]
    for sc, idx, name in scored:
        if sc < threshold:
            break
        if not _verify_key_tokens(query, name):
            if log_fn:
                log_fn(f"  [Matcher] Rejected (key tokens): {name[:60]} (score={sc:.0f})")
            continue
        accepted.append(MatchResult(name=name, score=sc, index=idx, all_scores=all_scores))
        if len(accepted) >= top_n:
            break

    if not accepted and log_fn:
        log_fn(f"  [Matcher] No match above threshold ({threshold})")
    return accepted


def find_best_match(
    query: str,
    candidates: Sequence[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    top_n: int = 3,
    log_fn=None,
) -> Optional[MatchResult]:
    """
    Find the best matching candidate for a query.

    Args:
        query:      The search query (product name being searched for).
        candidates: List of candidate product names to match against.
        threshold:  Minimum score to accept a match (0-100).
        top_n:      Number of top candidates to include in debug output.
        log_fn:     Optional logging function log_fn(msg: str).

    Returns:
        MatchResult with the best match, or None if no match passes
        the threshold + key-token verification.
    """
    if not query or not candidates:
        return None

    scored: list[tuple[float, int, str]] = []  # (score, index, name)

    for i, candidate in enumerate(candidates):
        if not candidate or not candidate.strip():
            continue
        sc = calculate_match_score(query, candidate)
        scored.append((sc, i, candidate))

    if not scored:
        return None

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Debug logging
    top = scored[:top_n]
    _log_candidates(query, top, log_fn)

    # Try each candidate from best to worst
    for sc, idx, name in scored:
        if sc < threshold:
            break  # All remaining are worse

        # Verify key tokens to reject garbage matches
        if not _verify_key_tokens(query, name):
            if log_fn:
                log_fn(f"  [Matcher] Rejected (key tokens): {name[:60]} (score={sc:.0f})")
            continue

        # Accept this match
        all_scores = [(s, n) for s, _, n in top]
        if log_fn:
            log_fn(f"  [Matcher] Selected: {name[:60]} (score={sc:.0f})")
        return MatchResult(name=name, score=sc, index=idx, all_scores=all_scores)

    if log_fn:
        log_fn(f"  [Matcher] No match above threshold ({threshold})")
    return None


def _log_candidates(query: str, top: list[tuple[float, int, str]], log_fn):
    """Log the top candidate matches for debugging."""
    if not log_fn:
        return

    log_fn(f"  [Matcher] Query: {query}")
    if not top:
        log_fn("  [Matcher] No candidates")
        return

    log_fn("  [Matcher] Candidates:")
    for sc, _, name in top:
        log_fn(f"    {sc:5.0f} -> {name[:70]}")
