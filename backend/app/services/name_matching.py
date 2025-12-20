"""
Shared utilities for character/name matching.

We centralize normalization + fuzzy scoring here so CharacterExtractor and
CharacterDatabase stay consistent and we can improve behavior in one place.
"""

from __future__ import annotations

import re
from thefuzz import fuzz


# Minimal, safe abbreviation expansion map (token-level).
_ABBREV_MAP = {
    "dr": "doctor",
    "mr": "mister",
    "mrs": "missus",
    "ms": "miss",
}

_TITLE_TOKENS = {
    "doctor",
    "mister",
    "missus",
    "miss",
}


def normalize_name(name: str) -> str:
    """
    Normalize a name for fuzzy matching.

    - Lowercase
    - Remove punctuation
    - Collapse whitespace
    - Expand common abbreviations (e.g., "dr" -> "doctor")
    """
    if not name:
        return ""

    # Keep letters/numbers/spaces; strip punctuation (e.g. "Dr.", "O'Neil", etc.)
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", str(name).lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""

    tokens = cleaned.split(" ")
    tokens = [_ABBREV_MAP.get(t, t) for t in tokens if t]
    return " ".join(tokens).strip()


def name_similarity_ratio(a: str, b: str) -> float:
    """
    Return similarity ratio in [0.0, 1.0] using TheFuzz.

    We take the best of:
    - token_sort_ratio: handles name order swaps well
    - token_set_ratio: handles subset matches (e.g. "Doctor Strange" vs "Strange")
    - partial_ratio: handles truncations and partial overlaps
    """
    na = normalize_name(a)
    nb = normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    ta = na.split()
    tb = nb.split()
    if not ta or not tb:
        return 0.0

    # Guardrail: don't match title-only to a full name (avoids many false merges).
    if len(ta) == 1 and ta[0] in _TITLE_TOKENS and len(tb) > 1:
        return 0.0
    if len(tb) == 1 and tb[0] in _TITLE_TOKENS and len(ta) > 1:
        return 0.0

    s1 = fuzz.token_sort_ratio(na, nb)
    s2 = fuzz.token_set_ratio(na, nb)
    s3 = fuzz.partial_ratio(na, nb)
    return max(s1, s2, s3) / 100.0


