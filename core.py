"""Deterministic cheese-order -> SAP parsing core.

This module contains ALL business logic and deliberately has no Streamlit /
network dependency so it can be unit tested (see tests/).

The rules implemented here follow MASTER_TRAINING_CHEESE_ORDER_STOCK_SAP_V2.txt:

* never combine two different customers;
* never invent an FG code - anything unclear goes to REVIEW;
* W.Poly (WP) codes are used only when WP is written explicitly;
* Top Cow shred == Top Cow dice (same SKU), Nivora shred != Nivora dice;
* CTN is converted with the item packing, PKT/PCS is never multiplied;
* a quantity without a unit is flagged instead of guessed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from item_master import (  # noqa: F401  (PRODUCTS re-exported on purpose)
    PRODUCTS,
    REGULAR_OF_WP,
    WP_ONLY,
    WP_VARIANTS,
    is_wp_code,
)

# ============================================================================
# 1. TEXT NORMALISATION
# ============================================================================

_PHRASE_FIXES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\btop\s*[-_]?\s*cow\b"), "top cow"),
    (re.compile(r"\bpizza\s*[-_]?\s*topping\b"), "pizza topping"),
    (re.compile(r"\bdesi\s*ghee\b"), "desi ghee"),
    (re.compile(r"\bun\s+salted\b"), "unsalted"),
]

# W.Poly / WP written in any of the accepted spellings.
_WP_RE = re.compile(
    r"(?<![a-z0-9])(?:w\s*[./\-]?\s*poly|w\s*\.\s*p\.?|w\s*/\s*p|wp)(?![a-z0-9])",
    re.I,
)

_WORD_FIXES = {
    # brand / typo normalisation
    "accha": "achha", "acha": "achha", "achaa": "achha", "achh": "achha",
    "acchha": "achha", "ahcha": "achha", "aacha": "achha", "ach": "achha",
    "chadder": "cheddar", "chaddar": "cheddar", "chedar": "cheddar",
    "cheder": "cheddar", "cheedar": "cheddar", "cheeder": "cheddar",
    "chedder": "cheddar", "chadar": "cheddar", "chddr": "cheddar",
    "chesse": "cheese", "chese": "cheese", "chz": "cheese",
    "mozz": "mozzarella", "moz": "mozzarella", "mozza": "mozzarella",
    "mozzarela": "mozzarella", "mozzrela": "mozzarella", "mozralla": "mozzarella",
    "mozerella": "mozzarella", "mozzerella": "mozzarella", "mozarella": "mozzarella",
    "mozzrella": "mozzarella", "mozzarrella": "mozzarella", "mozzz": "mozzarella",
    # product form
    "shredd": "shred", "shredded": "shred", "shreded": "shred", "shrded": "shred",
    "shreadded": "shred", "shared": "shred", "sherd": "shred", "shrad": "shred",
    "shrd": "shred", "shreds": "shred", "shredds": "shred", "shredding": "shred",
    "diced": "dice", "dices": "dice", "dise": "dice",
    "blk": "block", "blck": "block", "blocks": "block", "bloc": "block",
    "slices": "slice", "slic": "slice", "slise": "slice", "sliced": "slice",
    # origin
    "locl": "local", "lockl": "local", "loacl": "local", "lcl": "local",
    "imp": "imported", "import": "imported", "imprted": "imported",
    "imported": "imported", "uk": "uk",
    # units
    "ctns": "ctn", "carton": "ctn", "cartons": "ctn", "cartoon": "ctn",
    "coton": "ctn", "cotton": "ctn", "crtn": "ctn", "ctnn": "ctn",
    "box": "ctn", "boxes": "ctn", "bx": "ctn", "case": "ctn", "cases": "ctn",
    "pkts": "pkt", "packet": "pkt", "packets": "pkt", "pack": "pkt",
    "packs": "pkt", "pac": "pkt", "pcs": "pkt", "pc": "pkt", "pices": "pkt",
    "piece": "pkt", "pieces": "pkt", "nos": "pkt", "peice": "pkt",
    "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "gms": "gm", "gram": "gm", "grams": "gm", "grm": "gm",
    # colours / misc
    "yello": "yellow", "yelow": "yellow", "ylw": "yellow",
    "whte": "white", "wht": "white", "whit": "white",
    "jalapino": "jalapeno", "jalepeno": "jalapeno", "jalapeeno": "jalapeno",
    "jal": "jalapeno", "jalepino": "jalapeno",
    "danis": "danish", "dansih": "danish",
    "silvr": "silver", "siver": "silver",
    "verona": "verona", "verrona": "verona",
    "latina": "latina", "latinaa": "latina",
    "nivora": "nivora", "nivoraa": "nivora",
    "allana": "allana", "alana": "allana", "allanaa": "allana",
}
_WORD_FIX_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _WORD_FIXES), key=len, reverse=True)) + r")\b")

_KNOWN_RATIOS = {("70", "30"), ("30", "70"), ("50", "50"), ("60", "40"), ("40", "60"), ("80", "20"), ("20", "80")}
_RATIO_SEP_RE = re.compile(r"\b(\d{2})\s*[./:\-\\]\s*(\d{2})\b")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•·>]+|\(?\d{1,2}[).])\s+")


def _ratio_fix(match: re.Match) -> str:
    a, b = match.group(1), match.group(2)
    return f"{a}/{b}" if (a, b) in _KNOWN_RATIOS else match.group(0)


def normalize(text: Any) -> str:
    """Lowercase + typo/unit/ratio normalisation used by every matcher."""
    s = str(text or "").lower()
    s = s.replace("\u00a0", " ").replace("’", "'").replace("–", "-").replace("—", "-")
    s = re.sub(r"[*_•·|]+", " ", s)
    s = _LIST_MARKER_RE.sub("", s)
    for pattern, repl in _PHRASE_FIXES:
        s = pattern.sub(repl, s)
    s = _RATIO_SEP_RE.sub(_ratio_fix, s)          # 70.30 / 70-30 -> 70/30
    s = _WP_RE.sub(" wp ", s)                      # every W.Poly spelling -> "wp"
    s = re.sub(r"(\d)\s*(kg|gm|ctn|pkt)\b", r"\1 \2", s)   # 2kg -> 2 kg
    s = re.sub(r"[,;]+", " ", s)
    s = _WORD_FIX_RE.sub(lambda m: _WORD_FIXES[m.group(1)], s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def has_wp(text: str) -> bool:
    """True only when WP / W.P / W.Poly / W-Poly / W/P is explicitly written."""
    return bool(re.search(r"\bwp\b", normalize(text)))


# ============================================================================
# 2. PERSISTENT RULES (aliases taught by the user)
# ============================================================================

RULES_FILE = Path(__file__).with_name("rules.json")
_DEFAULT_RULES: Dict[str, List[dict]] = {
    "product_aliases": [],
    "quantity_rules": [],
    "customer_rules": [],
    "general_rules": [],
}


def load_rules(path: Optional[Path] = None) -> Dict[str, List[dict]]:
    target = Path(path) if path else RULES_FILE
    rules = {key: list(value) for key, value in _DEFAULT_RULES.items()}
    try:
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8"))
            for key in rules:
                if isinstance(data.get(key), list):
                    rules[key] = data[key]
    except Exception:
        pass
    return rules


def save_rules(rules: Dict[str, List[dict]], path: Optional[Path] = None) -> bool:
    target = Path(path) if path else RULES_FILE
    target.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _alias_candidates(rules: Dict[str, List[dict]], user_only: bool) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for entry in rules.get("product_aliases", []) or []:
        alias = normalize(entry.get("alias", ""))
        code = str(entry.get("code", "")).upper()
        if not alias or code not in PRODUCTS:
            continue
        is_user = str(entry.get("source", "")).lower() == "user" or bool(entry.get("note"))
        if is_user == user_only:
            out.append((alias, code))
    # longest alias first: "top cow white dice" must beat "top cow"
    return sorted(out, key=lambda item: len(item[0]), reverse=True)


def match_alias(normalized_text: str, rules: Dict[str, List[dict]], user_only: bool, wp: bool) -> Optional[str]:
    """Longest matching alias whose WP-ness agrees with the order text."""
    for alias, code in _alias_candidates(rules, user_only):
        if alias not in normalized_text:
            continue
        alias_is_wp = "wp" in alias.split() or is_wp_code(code)
        if alias_is_wp != wp and not (wp and code in WP_VARIANTS):
            # a regular alias must not answer a WP request unless it can be upgraded
            if alias_is_wp != wp:
                continue
        return code
    return None


# ============================================================================
# 3. PRODUCT RESOLUTION
# ============================================================================


@dataclass
class ProductMatch:
    code: Optional[str] = None
    name: str = ""
    reason: str = ""
    review: str = ""
    suggestion: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.code) and not self.review


def _base(code: Optional[str] = None, reason: str = "", review: str = "", suggestion: Optional[str] = None) -> ProductMatch:
    return ProductMatch(code=code, reason=reason, review=review, suggestion=suggestion)


NIVORA_FAMILIES = ("mf", "pro", "max", "vf", "pt")
NIVORA_TABLE = {
    ("mf", "white", "dice"): "FG-02-0102", ("mf", "white", "shred"): "FG-02-0101",
    ("mf", "yellow", "dice"): "FG-02-0104", ("mf", "yellow", "shred"): "FG-02-0103",
    ("pro", "white", "dice"): "FG-02-0106", ("pro", "white", "shred"): "FG-02-0105",
    ("pro", "yellow", "dice"): "FG-02-0108", ("pro", "yellow", "shred"): "FG-02-0107",
    ("max", "white", "dice"): "FG-02-0110", ("max", "white", "shred"): "FG-02-0109",
    ("max", "yellow", "dice"): "FG-02-0112", ("max", "yellow", "shred"): "FG-02-0111",
    ("pt", "white", "dice"): "FG-02-0118", ("pt", "white", "shred"): "FG-02-0117",
    ("pt", "yellow", "dice"): "FG-02-0120", ("pt", "yellow", "shred"): "FG-02-0119",
    ("vf", "white", "dice"): "FG-02-0114", ("vf", "white", "shred"): "FG-02-0113",
    ("vf", "yellow", "dice"): "FG-02-0116", ("vf", "yellow", "shred"): "FG-02-0115",
}


# "800" / "500" / "16" only describe the pack size when a unit does not follow them
# ("white slice 800" is 800gm, but "desi ghee 16 ctn" is 16 cartons).
_SIZE_800 = r"\b800\s*gm\b|\b0?\.8\s*kg\b|\b800\b(?!\s*(?:ctn|pkt|kg))"
_SIZE_500 = r"\b500\s*gm\b|\b0?\.5\s*kg\b|\b500\b(?!\s*(?:ctn|pkt|kg))"
_SIZE_16KG = r"\b16\s*kg\b|\b16\b(?!\s*(?:ctn|pkt|kg))"


def _word(text: str, w: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text) is not None


def _resolve_base(t: str, default_form: Optional[str] = None) -> ProductMatch:  # noqa: C901 - a deliberate, readable rule cascade
    """Map normalised order text to the REGULAR SAP item (WP is applied later)."""
    has = lambda *words: all(w in t for w in words)          # noqa: E731
    any_ = lambda *words: any(w in t for w in words)         # noqa: E731

    block = _word(t, "block")
    shred = _word(t, "shred")
    dice = _word(t, "dice")
    slice_ = _word(t, "slice")
    white = _word(t, "white")
    yellow = any_("yellow", "orange") or _word(t, "burger")
    gm800 = bool(re.search(_SIZE_800, t))

    # ---------- DESI GHEE ----------
    if _word(t, "ghee"):
        if re.search(_SIZE_16KG, t):
            return _base("FG-05-0005", "desi ghee 16kg")
        if re.search(_SIZE_500, t):
            return _base("FG-05-0002", "desi ghee 500gm")
        return _base("FG-05-0011", "desi ghee 1kg")

    # ---------- BUTTER (salted = yellow, unsalted = white) ----------
    if _word(t, "butter"):
        salted = _word(t, "salted") and not _word(t, "unsalted")
        unsalted = _word(t, "unsalted")
        if salted and white and not yellow:
            return _base(review="Salted butter written together with White - salted means Yellow. Please confirm.")
        if unsalted and yellow and not white:
            return _base(review="Unsalted butter written together with Yellow - unsalted means White. Please confirm.")
        is_yellow = salted or yellow
        is_white = unsalted or white
        fat87 = bool(re.search(r"\b87\b", t))
        gm500 = bool(re.search(_SIZE_500, t))
        if is_yellow and not is_white:
            if fat87:
                return _base("FG-06-0018", "butter yellow 87 fat")
            if gm500:
                return _base("FG-06-0010", "butter yellow 500gm")
            return _base("FG-06-0011", "butter yellow 82 fat 1kg")
        if is_white and not is_yellow:
            if fat87:
                return _base("FG-06-0017", "butter white 87 fat")
            if gm500:
                return _base("FG-06-0003", "butter white 500gm")
            return _base("FG-06-0004", "butter white 82 fat 1kg")
        return _base(review="Butter without Salted/Unsalted or White/Yellow - cannot pick a SAP code safely.")

    # ---------- LOCKED SPECIAL MAPPINGS ----------
    if _word(t, "red") and "mozzarella" in t and block:
        return _base("FG-01-0006", "red mozz block = Achha Mozzarella Block")
    if _word(t, "blue") and shred:
        return _base("FG-01-0042", "blue shredd = Achha Mozzarella Shredded")

    # ---------- ALLANA ----------
    if _word(t, "allana"):
        gold = _word(t, "gold")
        r7030 = "70/30" in t
        r5050 = "50/50" in t
        if "pizza topping" in t or (_word(t, "topping") and block):
            return _base("FG-02-0171" if gold else "FG-02-0172", "allana pizza topping block (W.Poly only)")
        if slice_:
            if yellow:
                return _base("FG-02-0215", "allana cheddar slice yellow 800gm (W.Poly only)")
            if white:
                return _base("FG-02-0214", "allana cheddar slice white 800gm (W.Poly only)")
            return _base(review="Allana slice needs White or Yellow.")
        if "cheddar" in t and block:
            return _base("FG-02-0159" if gold else "FG-02-0094", "allana cheddar block")
        if r7030:
            if gold:
                if dice:
                    return _base("FG-02-0179" if yellow else "FG-02-0177", "allana gold pizza 70/30 dice (W.Poly only)")
                return _base("FG-02-0175" if yellow else "FG-02-0173", "allana gold pizza 70/30 shredded (W.Poly only)")
            if dice:
                return _base("FG-02-0180" if yellow else "FG-02-0178", "allana pizza 70/30 dice (W.Poly only)")
            if yellow:
                return _base(review="Allana Pizza 70/30 Shredded Yellow is not in the item master.")
            return _base("FG-02-0100", "allana pizza 70/30 shredded white")
        if r5050:
            if gold:
                return _base("FG-02-0183" if yellow else "FG-02-0181", "allana gold pizza 50/50 (W.Poly only)")
            return _base("FG-02-0184" if yellow else "FG-02-0182", "allana pizza 50/50 (W.Poly only)")
        if "mozzarella" in t or block or dice or shred:
            if block:
                return _base("FG-02-0161" if gold else "FG-02-0096", "allana mozzarella block")
            if dice:
                if gold:
                    return _base("FG-02-0169" if yellow else "FG-02-0167", "allana gold mozzarella dice (W.Poly only)")
                return _base("FG-02-0170" if yellow else "FG-02-0168", "allana mozzarella dice (W.Poly only)")
            if shred:
                if gold:
                    return _base("FG-02-0165" if yellow else "FG-02-0163", "allana gold mozzarella shredded (W.Poly only)")
                return _base("FG-02-0166" if yellow else "FG-02-0097", "allana mozzarella shredded")
        return _base(review="Allana item needs block/shred/dice/slice and colour to be mapped.")

    # ---------- NIVORA (shred and dice are DIFFERENT SKUs) ----------
    family = next((f for f in NIVORA_FAMILIES if _word(t, f)), None)
    if family == "pt" and "pizza topping" in t and not (white or yellow):
        family = None  # plain "Pizza Topping Block/Shred" is the 2kg item, not Nivora PT
    if family is None and "pizza topping" in t and (white or yellow):
        family = "pt"
    if family:
        colour = "yellow" if yellow or _word(t, "y") else "white" if white or _word(t, "w") else None
        form = "dice" if dice else "shred" if shred else (default_form or None)
        if colour is None:
            return _base(review=f"Nivora {family.upper()} needs White or Yellow.")
        if form is None:
            return _base(
                review=f"Nivora {family.upper()} needs Dice or Shredded - they are different SKUs.",
                suggestion=NIVORA_TABLE[(family, colour, "dice")],
            )
        code = NIVORA_TABLE[(family, colour, form)]
        if re.search(r"\b2\s*kg\b", t) and not _word(t, "wp"):
            return _base(review="Nivora 2kg exists only as W.Poly - write WP, or order the 2.5kg item.", suggestion=code)
        return _base(code, f"nivora {family} {colour} {form}")

    # ---------- TOP COW (shred and dice are the SAME SKU) ----------
    if "top cow" in t:
        if _word(t, "premium") and white:
            return _base("FG-02-0079", "top cow premium white dice (W.Poly only)")
        if "cheddar" in t and block:
            return _base("FG-02-0068", "top cow cheddar block")
        if block and not (dice or shred):
            return _base("FG-02-0060", "top cow mozzarella block white")
        if yellow and (dice or shred):
            return _base("FG-02-0049", "top cow yellow dice/shred (same SKU)")
        if white or dice or shred:
            return _base("FG-02-0048", "top cow white dice/shred (same SKU)")
        return _base(review="Top Cow item needs block/dice/shred and colour.")

    # ---------- SILVER (cheddar is a different product from mozzarella) ----------
    if _word(t, "silver"):
        if "cheddar" in t:
            if _word(t, "new"):
                return _base("FG-02-0080", "new silver cheddar block")
            if shred:
                return _base("FG-02-0067", "silver cheddar shredded")
            return _base("FG-02-0040", "silver cheddar block")
        if shred:
            return _base("FG-01-0110", "silver mozzarella shredded")
        return _base("FG-01-0111", "silver mozzarella block")

    # ---------- SINGLE BRAND FAMILIES ----------
    if _word(t, "danish"):
        return _base("FG-01-0030", "danish mozzarella shredded") if shred else _base("FG-01-0018", "danish mozzarella block")
    if _word(t, "verona"):
        return _base("FG-03-0025", "verona mozzarella block") if block else _base("FG-01-0072", "verona mozzarella shredded")
    if _word(t, "latina"):
        return _base("FG-01-0066", "latina mozzarella shredded")

    if _word(t, "classic"):
        if "70/30" in t:
            return _base("FG-02-0072", "classic 70/30 shredded")
        if _word(t, "dc"):
            return _base("FG-02-0082", "classic mozzarella shredded dc")
        if "cheddar" in t and block:
            return _base("FG-02-0012", "classic cheddar block")
        if "mozzarella" in t and block:
            return _base("FG-01-0012", "classic mozzarella block")
        if shred:
            return _base("FG-02-0036", "classic (mozzarella) shredded")
        if block:
            return _base(review="Classic Block - is it Cheddar (FG-02-0012) or Mozzarella (FG-01-0012)?")

    if _word(t, "achha") and not ("70/30" in t or "50/50" in t):
        if "cheddar" in t and (block or _word(t, "pizza")):
            return _base("FG-02-0006", "achha pizza cheddar block")
        if block:
            return _base("FG-01-0006", "achha mozzarella block")
        if dice:
            return _base("FG-01-0125", "achha yellow dice") if yellow else _base("FG-01-0124", "achha white dice")
        if shred:
            return _base("FG-01-0054", "achha mozzarella shredded yellow") if yellow else _base("FG-01-0042", "achha mozzarella shredded white")

    # ---------- ORIGIN / RATIO FAMILIES ----------
    if _word(t, "m3") and (shred or dice or "70/30" in t):
        return _base("FG-02-0051", "m3 = new 70/30 shredded")
    if "70/30" in t:
        if _word(t, "local"):
            return _base("FG-03-0018", "local 70/30 shredded")
        if _word(t, "imported") or _word(t, "uk"):
            return _base("FG-03-0026", "imported 70/30 dice") if dice else _base("FG-03-0006", "imported 70/30 shredded")
        if _word(t, "new") or _word(t, "m3"):
            return _base("FG-02-0051", "new / m3 70/30 shredded")
        return _base(review="70/30 without a brand - Local, Imported, Classic, New/M3 or Allana?")
    if "50/50" in t:
        return _base("FG-03-0024", "50/50 shredded (imported)")

    if (_word(t, "imported") or _word(t, "uk")) and shred:
        return _base("FG-01-0036", "imported / uk mozzarella shredded")

    # ---------- PIZZA TOPPING / PIZZA CHEDDAR ----------
    if "pizza topping" in t:
        if block:
            return _base("FG-02-0065", "pizza topping block")
        if shred:
            return _base("FG-02-0064", "pizza topping shredded")
        return _base(review="Pizza Topping - Block (FG-02-0065) or Shredded (FG-02-0064)?")
    if "pizza" in t and "cheddar" in t:
        return _base("FG-02-0006", "pizza cheddar block")

    # ---------- SLICES ----------
    if slice_:
        if _word(t, "jalapeno"):
            return _base("FG-02-0039", "jalapeno cheddar slice 1kg")
        if white and not yellow:
            return _base("FG-02-0037", "white slice 800gm") if gm800 else _base("FG-02-0023", "white slice 1kg")
        if yellow:
            return _base("FG-02-0038", "yellow slice 800gm") if gm800 else _base("FG-02-0028", "yellow slice 1kg")
        return _base(review="Slice without colour - White, Yellow/Burger or Jalapeno?")

    # ---------- GENERIC DEFAULTS ----------
    if _word(t, "regular") and "cheddar" in t and block:
        return _base("FG-02-0018", "regular cheddar block")
    if "mozzarella" in t and block:
        return _base("FG-01-0006", "generic mozzarella block defaults to Achha")
    if "cheddar" in t and block:
        return _base(review="Cheddar Block without a brand - Classic, Regular, Top Cow, Silver, Pizza or Allana?")
    if shred or dice:
        return _base(review="Shredded/Dice without a brand - which brand?")
    return _base()


def _keyword_fallback(t: str, wp: bool) -> Optional[str]:
    """Last resort: longest item-master keyword contained in the text."""
    best: Optional[Tuple[int, str]] = None
    for code, product in PRODUCTS.items():
        if is_wp_code(code) != wp:
            continue
        for keyword in product.get("keywords", []) or []:
            key = normalize(keyword)
            if key and key in t:
                if best is None or len(key) > best[0]:
                    best = (len(key), code)
    return best[1] if best else None


_FG_CODE_RE = re.compile(r"\bfg[\s\-]?(\d{2})[\s\-]?(\d{4})\b", re.I)


def match_product(text: str, rules: Optional[Dict[str, List[dict]]] = None,
                  default_form: Optional[str] = None) -> ProductMatch:
    """Resolve an order line to a SAP item, following the master priority list."""
    rules = load_rules() if rules is None else rules
    t = normalize(text)
    if not t:
        return _base(review="Empty line.")
    wp = _word(t, "wp")

    # 1. explicit FG code always wins
    code_match = _FG_CODE_RE.search(t)
    if code_match:
        code = f"FG-{code_match.group(1)}-{code_match.group(2)}".upper()
        if code in PRODUCTS:
            return _finalise(_base(code, "explicit FG code"), wp, t)
        return _base(review=f"{code} is not in the item master.")

    # 2. aliases taught by the user
    taught = match_alias(t, rules, user_only=True, wp=wp)
    if taught:
        return _finalise(_base(taught, "user taught alias"), wp, t)

    # 3. brand + type rule cascade
    result = _resolve_base(t, default_form)
    if result.code or result.review:
        return _finalise(result, wp, t)

    # 4. seeded aliases from rules.json
    seeded = match_alias(t, rules, user_only=False, wp=wp)
    if seeded:
        return _finalise(_base(seeded, "saved alias"), wp, t)

    # 5. item-master keywords
    keyword = _keyword_fallback(t, wp)
    if keyword:
        return _finalise(_base(keyword, "item master keyword"), wp, t)

    return _base(review="No product could be identified on this line.")


def _finalise(result: ProductMatch, wp: bool, t: str) -> ProductMatch:
    """Apply the W.Poly rule and attach the product name."""
    if result.code and not result.review:
        code = result.code
        if wp and not is_wp_code(code):
            if code in WP_VARIANTS:
                result.code = WP_VARIANTS[code]
                result.reason = f"{result.reason} + W.Poly"
            else:
                name = PRODUCTS[code]["name"]
                return _base(
                    review=f"WP written but {name} has no W.Poly SAP code.",
                    suggestion=code,
                )
        elif not wp and is_wp_code(code):
            if code in REGULAR_OF_WP:
                result.code = REGULAR_OF_WP[code]
                result.reason = f"{result.reason} (regular, WP not written)"
            else:
                result.reason = f"{result.reason} (item exists only as W.Poly)"
    if result.code:
        result.name = PRODUCTS[result.code]["name"]
    if result.suggestion and result.suggestion not in PRODUCTS:
        result.suggestion = None
    return result


def find_product(text: str, rules: Optional[Dict[str, List[dict]]] = None) -> Optional[str]:
    """Backwards compatible helper: return a SAP code or None."""
    result = match_product(text, rules)
    return result.code if result.ok else None


# ============================================================================
# 4. QUANTITY PARSING
# ============================================================================


@dataclass
class Quantity:
    parts: List[Tuple[float, str]] = field(default_factory=list)  # [(3, "CTN"), (2, "PKT")]
    review: str = ""

    @property
    def text(self) -> str:
        return " + ".join(f"{_num(v)} {u}" for v, u in self.parts) if self.parts else ""

    @property
    def unit(self) -> str:
        units = {u for _, u in self.parts}
        return "MIXED" if len(units) > 1 else (self.parts[0][1] if self.parts else "")

    @property
    def value(self) -> Optional[float]:
        return self.parts[0][0] if len(self.parts) == 1 else None


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


_TIME_RE = re.compile(r"\b\d{1,2}\s*[:.]\s*\d{2}\s*(?:am|pm)?\b")
_AMPM_RE = re.compile(r"\b\d{1,2}\s*(?:am|pm)\b")
_RATIO_RE = re.compile(r"\b\d{2}/\d{2}\b")
_FAT_RE = re.compile(r"\b\d{2,3}\s*(?:%|fat)\b|\bfat\s*\d{2,3}\b")
_GM_RE = re.compile(r"\b\d+(?:\.\d+)?\s*gm\b")
_DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
_PHONE_RE = re.compile(r"\b\d{4}[\s-]?\d{6,}\b|\b\+\d[\d\s-]{8,}\b")
_PRICE_RE = re.compile(r"\b(?:rs|pkr|price|rate)\.?\s*\d+(?:\.\d+)?\b")
_QTY_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ctn|pkt|kg)\b")
_UNIT_QTY_RE = re.compile(r"\b(ctn|pkt|kg)\s*[:=]?\s*(\d+(?:\.\d+)?)\b")
_BARE_NUM_RE = re.compile(r"(?<![a-z0-9./])(\d+(?:\.\d+)?)(?![a-z0-9./])")
_STANDARD_PACK_KG = {0.5, 0.8, 1.0, 2.0, 2.5, 16.0}


def _mask(text: str, *patterns: re.Pattern) -> str:
    masked = text
    for pattern in patterns:
        masked = pattern.sub(lambda m: "#" * len(m.group(0)), masked)
    return masked


def parse_quantity(text: str, pack_kg: Optional[float] = None) -> Quantity:
    """Extract the ordered quantity, ignoring numbers that belong to the product.

    Numbers such as 70/30, 50/50, 800gm, "82 fat", timestamps, dates and phone
    numbers are never read as quantities.
    """
    t = normalize(text)
    if not t:
        return Quantity(review="Empty line.")

    masked = _mask(t, _PHONE_RE, _PRICE_RE, _TIME_RE, _AMPM_RE, _RATIO_RE, _FAT_RE, _GM_RE, _DATE_RE)

    found: List[Tuple[int, float, str]] = []
    taken: List[Tuple[int, int]] = []
    for regex, qty_first in ((_QTY_UNIT_RE, True), (_UNIT_QTY_RE, False)):
        for m in regex.finditer(masked):
            if any(start < m.end() and m.start() < end for start, end in taken):
                continue
            taken.append((m.start(), m.end()))
            value = float(m.group(1) if qty_first else m.group(2))
            unit = (m.group(2) if qty_first else m.group(1)).upper()
            found.append((m.start(), value, unit))
    found.sort()

    packed = [(v, u) for _, v, u in found if u in ("CTN", "PKT")]
    if packed:
        return _merge_parts(packed)

    kg_parts = [(v, u) for _, v, u in found if u == "KG"]
    if kg_parts:
        # "Achha block 2 kg" is a packing description, not a quantity;
        # "2 kg burger slice" (1kg packs) and "90 kg 70/30" are real quantities.
        if (
            len(kg_parts) == 1
            and pack_kg is not None
            and abs(kg_parts[0][0] - float(pack_kg)) < 1e-9
            and kg_parts[0][0] in _STANDARD_PACK_KG
        ):
            return Quantity(review="No quantity found - only the pack size is written.")
        return _merge_parts(kg_parts)

    if _word(t, "sample"):
        return Quantity(parts=[(1.0, "PKT")])

    bare = _BARE_NUM_RE.findall(masked)
    if len(bare) == 1:
        return Quantity(parts=[(float(bare[0]), "")], review="Quantity has no unit (CTN or PKT?).")
    if len(bare) > 1:
        return Quantity(review="Several numbers without a unit - cannot tell the quantity.")
    return Quantity(review="No quantity found on this line.")


def _merge_parts(parts: List[Tuple[float, str]]) -> Quantity:
    merged: Dict[str, float] = {}
    for value, unit in parts:
        merged[unit] = merged.get(unit, 0.0) + value
    return Quantity(parts=[(value, unit) for unit, value in merged.items()])


def sap_units(quantity: Quantity, code: str) -> Tuple[Optional[int], str]:
    """Convert a parsed quantity into SAP units (PKT). Returns (units, problem)."""
    product = PRODUCTS[code]
    total = 0.0
    for value, unit in quantity.parts:
        if unit == "CTN":
            total += value * product["pcs_ctn"]
        elif unit == "PKT":
            total += value
        elif unit == "KG":
            total += value / product["kg"]
        else:
            return None, "Quantity has no unit (CTN or PKT?)."
    if total <= 0:
        return None, "Quantity is zero."
    if abs(total - round(total)) > 1e-6:
        return None, f"{quantity.text} does not convert to whole packets ({total:.2f})."
    return int(round(total)), ""


# ============================================================================
# 5. ORDER PARSING (customer segmentation + line mapping)
# ============================================================================

CUSTOMER_CODE_RE = re.compile(r"\b(?:cfs|bp)[\s_\-]?(\d{3,})\b", re.I)
_CUSTOMER_PREFIX_RE = re.compile(r"^\s*(?:customer|cust|party|client|shop|bp)\s*[:\-]\s*(.+)$", re.I)
_BLOCK_MARKER_RE = re.compile(r"^\s*=+\s*customer\s+block\s*\d*\s*=+\s*$", re.I)
_NOISE_RE = re.compile(
    r"^(?:forwarded|self\s*pick|self\s*pickup|pick\s*up|today|tomorrow|yesterday|later|thanks?|thank\s*you|"
    r"ok(?:ay)?|noted|salam|salaam|assalam[\w\s]*|hello|hi|good\s*(?:morning|afternoon|evening|night)|"
    r"please|plz|order|orders|new\s*order|urgent|delivery|deliver|received|done|yes|no|add\s*in\s*v\d+|"
    r"\d{1,2}:\d{2}\s*(?:am|pm)?|<?\s*media\s*omitted\s*>?|image\s*omitted|sticker\s*omitted)\.?$",
    re.I,
)
_PRODUCT_HINT_RE = re.compile(
    r"cheese|cheddar|mozz|shred|dice|block|slice|butter|ghee|nivora|latina|verona|danish|top\s*cow|achha|"
    r"allana|silver|classic|burger|orange|jalapeno|topping|50/50|70/30|\bmf\b|\bpt\b|\bvf\b|\bpro\b|\bmax\b|\bwp\b",
    re.I,
)
_UNIT_HINT_RE = re.compile(r"\b(?:ctn|carton|cartons|box|boxes|pkt|packet|packets|pcs|pc|kg|gm)\b", re.I)
# Words that make a line a business/customer name even if it also reads like a product
# ("Cheese Wala Traders", "Pizza Point", "Danish Bakery").
_BUSINESS_RE = re.compile(
    r"\b(?:traders?|trading|foods?|shop|store|mart|market|hotel|restaurant|resturant|cafe|caf[eé]|"
    r"bakery|bakers?|kitchen|point|house|corner|centre|center|enterprises?|brothers?|bros|sons|"
    r"company|co\.?|ltd|pvt|caterers?|catering|distributors?|agency|agencies|general|super|"
    r"pizzeria|grill|broast|karahi|dhaba|sweets?|wala|walla|marquee|banquet|club|mess)\b",
    re.I,
)


def _customer_code(text: str) -> str:
    match = CUSTOMER_CODE_RE.search(text or "")
    if not match:
        return ""
    prefix = re.match(r"[a-z]+", normalize(match.group(0))).group(0).upper()
    return f"{prefix}{match.group(1)}"


def is_customer_code_line(line: str) -> bool:
    t = normalize(line)
    return bool(re.fullmatch(r"(?:cfs|bp)[\s\-_]*\d{3,}", t))


def is_noise(line: str) -> bool:
    t = re.sub(r"\s+", " ", str(line or "")).strip(" .-_*")
    if not t:
        return True
    if _NOISE_RE.fullmatch(t):
        return True
    if _PHONE_RE.fullmatch(t):
        return True
    return False


def is_customer_heading(line: str, rules: Optional[Dict[str, List[dict]]] = None) -> bool:
    """A short label without quantities that introduces an order block.

    A product name written without a quantity is NOT a heading - it is an order
    line that needs review, so we only accept a heading when the text does not
    resolve to a real item (or clearly looks like a business name).
    """
    raw = re.sub(r"\s+", " ", str(line or "")).strip()
    if not raw or is_noise(raw):
        return False
    if _CUSTOMER_PREFIX_RE.match(raw):
        return True
    if is_customer_code_line(raw):
        return False
    text = raw.split("|")[0].strip()
    if _UNIT_HINT_RE.search(text) or re.search(r"\d", text.replace("-", "")):
        return False
    if not 1 <= len(text.split()) <= 8:
        return False
    if _BUSINESS_RE.search(text):
        return True
    if _PRODUCT_HINT_RE.search(text):
        # "Achha shredded" (a product without a quantity) must not become a customer.
        return match_product(text, rules).code is None
    return True


@dataclass
class OrderLine:
    source: str
    code: Optional[str] = None
    product: str = ""
    quantity_text: str = ""
    unit: str = ""
    sap_units: Optional[int] = None
    status: str = "OK"
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "OK"


@dataclass
class Order:
    customer: str = ""
    customer_code: str = ""
    lines: List[OrderLine] = field(default_factory=list)
    ignored: List[str] = field(default_factory=list)

    @property
    def ok_lines(self) -> List[OrderLine]:
        return [line for line in self.lines if line.ok]

    @property
    def review_lines(self) -> List[OrderLine]:
        return [line for line in self.lines if not line.ok]

    @property
    def title(self) -> str:
        if self.customer and self.customer_code:
            return f"{self.customer} ({self.customer_code})"
        return self.customer or self.customer_code or "UNKNOWN CUSTOMER"

    def merged(self) -> Dict[str, int]:
        """SAP units per FG code - merged only inside this one customer."""
        merged: Dict[str, int] = {}
        for line in self.ok_lines:
            merged[line.code] = merged.get(line.code, 0) + int(line.sap_units or 0)
        return merged

    def sap_text(self) -> str:
        return "\n".join(sap_line(code, qty) for code, qty in self.merged().items())


def parse_line(text: str, rules: Optional[Dict[str, List[dict]]] = None,
               assume_unit: Optional[str] = None, default_form: Optional[str] = None) -> OrderLine:
    """Map one order line to a SAP item + quantity.

    ``assume_unit`` ("CTN" or "PKT") is an explicit opt-in for shops that always
    write quantities without a unit. It is off by default because the master
    training file says an unknown unit must be reviewed, not guessed.
    """
    source = re.sub(r"\s+", " ", str(text or "")).strip()
    line = OrderLine(source=source)
    match = match_product(source, rules, default_form=default_form)
    pack_kg = PRODUCTS[match.code]["kg"] if match.code else None
    quantity = parse_quantity(source, pack_kg=pack_kg)
    assumed = ""
    if assume_unit and len(quantity.parts) == 1 and quantity.parts[0][1] == "":
        quantity = Quantity(parts=[(quantity.parts[0][0], assume_unit.upper())])
        assumed = f"Unit not written - {assume_unit.upper()} assumed."
    line.quantity_text = quantity.text
    line.unit = quantity.unit

    problems: List[str] = []
    if match.code:
        line.code = match.code
        line.product = match.name
    else:
        problems.append(match.review or "Product not recognised.")
        if match.suggestion:
            problems.append(f"Closest item: {match.suggestion} {PRODUCTS[match.suggestion]['name']}.")
    if quantity.review:
        problems.append(quantity.review)

    if match.code and not quantity.review:
        units, issue = sap_units(quantity, match.code)
        if issue:
            problems.append(issue)
        else:
            line.sap_units = units

    if problems:
        line.status = "CHECK"
        line.note = " ".join(problems)
    else:
        line.note = " ".join(x for x in (match.reason, assumed) if x)
    return line


def parse_order(text: str, rules: Optional[Dict[str, List[dict]]] = None, progress=None,
                assume_unit: Optional[str] = None, default_form: Optional[str] = None) -> List[Order]:
    """Split raw text into per-customer orders. Customers are never merged."""
    rules = load_rules() if rules is None else rules
    raw_lines = [re.sub(r"\s+", " ", x).strip() for x in str(text or "").splitlines()]
    raw_lines = [x for x in raw_lines if x]
    orders: List[Order] = []
    current = Order()
    started = False

    def flush() -> None:
        nonlocal current, started
        if current.lines or current.ignored or current.customer:
            orders.append(current)
        current = Order()
        started = False

    total = max(1, len(raw_lines))
    for index, raw in enumerate(raw_lines):
        if progress:
            progress(min(0.9, (index + 1) / total), f"Reading line {index + 1}/{total}…")

        if _BLOCK_MARKER_RE.match(raw):
            flush()
            continue

        prefixed = _CUSTOMER_PREFIX_RE.match(raw)
        heading = prefixed.group(1).strip() if prefixed else raw

        if is_customer_code_line(raw):
            code = _customer_code(raw)
            if code:
                if current.customer_code and (current.lines or started):
                    flush()
                current.customer_code = code
            continue

        # "Al Madina Traders CFS-10234" -> heading plus customer code on one line.
        code_hit = CUSTOMER_CODE_RE.search(raw)
        if code_hit and not prefixed:
            remainder = (raw[:code_hit.start()] + " " + raw[code_hit.end():]).strip(" -|:•")
            if not remainder or is_customer_heading(remainder, rules):
                if current.lines or current.customer:
                    flush()
                current.customer = remainder
                current.customer_code = _customer_code(raw)
                started = True
                continue

        if prefixed or is_customer_heading(raw, rules):
            if current.lines or current.customer:
                flush()
            name, _, tail = heading.partition("|")
            current.customer = name.strip()
            current.customer_code = _customer_code(tail) or _customer_code(heading) or current.customer_code
            started = True
            continue

        if is_noise(raw):
            current.ignored.append(raw)
            continue

        current.lines.append(parse_line(raw, rules, assume_unit=assume_unit, default_form=default_form))
        started = True

    flush()
    return [order for order in orders if order.lines or order.customer]


# ============================================================================
# 6. SAP OUTPUT
# ============================================================================


def sap_line(code: str, qty: int) -> str:
    """FG CODE + 2 tabs + QTY + 5 tabs + HO-WH + 2 tabs + CHEESE (real tabs)."""
    return f"{code}\t\t{int(qty)}\t\t\t\t\tHO-WH\t\tCHEESE"


def sap_block(rows: Dict[str, int]) -> str:
    return "\n".join(sap_line(code, qty) for code, qty in rows.items())


# ============================================================================
# 7. TABULAR (Excel / CSV) ORDERS
# ============================================================================


def normalize_columns(df):
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    return out


def _first_column(columns: Iterable[str], *tests) -> Optional[str]:
    for column in columns:
        for test in tests:
            if test(column):
                return column
    return None


def _to_float(value) -> float:
    try:
        text = str(value).replace(",", "").strip()
        return float(text) if text and text.lower() not in ("nan", "none", "-") else 0.0
    except Exception:
        return 0.0


def process_tabular(df, rules: Optional[Dict[str, List[dict]]] = None):
    """Map an order sheet (SAP code / product / cartons / units) to SAP rows."""
    import pandas as pd  # imported lazily so the core stays dependency light

    rules = load_rules() if rules is None else rules
    data = normalize_columns(df)
    columns = list(data.columns)
    code_col = _first_column(columns, lambda c: ("sap" in c or "item" in c or "fg" in c) and "code" in c,
                             lambda c: c in ("item no", "item no.", "itemno", "code"))
    product_col = _first_column(columns, lambda c: "description" in c or "product" in c or "item name" in c,
                                lambda c: c == "item")
    ctn_col = _first_column(columns, lambda c: "carton" in c or c in ("ctn", "ctns", "box", "boxes"))
    unit_col = _first_column(columns, lambda c: c in ("units", "unit", "pcs", "pkt", "qty", "quantity", "pieces"))
    customer_col = _first_column(columns, lambda c: "customer" in c or "party" in c or "client" in c)

    rows: List[dict] = []
    for _, record in data.iterrows():
        customer = str(record.get(customer_col, "")).strip() if customer_col else ""
        if customer.lower() in ("nan", "none"):
            customer = ""
        raw_code = str(record.get(code_col, "")).strip().upper() if code_col else ""
        product_text = str(record.get(product_col, "")).strip() if product_col else ""
        code = raw_code if raw_code in PRODUCTS else None
        note = ""
        if code is None and product_text:
            match = match_product(product_text, rules)
            code = match.code if match.ok else None
            note = "" if code else (match.review or "Product not recognised.")
        if code is None:
            if raw_code or product_text:
                rows.append({
                    "Customer": customer, "FG Code": raw_code or "UNMAPPED", "Product": product_text,
                    "SAP Qty (PKT)": None, "Source": "sheet", "Status": "CHECK",
                    "Note": note or f"{raw_code} is not in the item master.",
                })
            continue

        units = _to_float(record.get(unit_col)) if unit_col else 0.0
        cartons = _to_float(record.get(ctn_col)) if ctn_col else 0.0
        pcs_ctn = PRODUCTS[code]["pcs_ctn"]
        status, note = "OK", ""
        if units > 0:
            sap_qty = int(round(units))
            if cartons > 0 and abs(cartons * pcs_ctn - units) > 1e-6:
                status, note = "CHECK", f"Units ({_num(units)}) != Cartons ({_num(cartons)}) x {pcs_ctn}/CTN."
        elif cartons > 0:
            sap_qty = int(round(cartons * pcs_ctn))
        else:
            continue
        rows.append({
            "Customer": customer, "FG Code": code, "Product": PRODUCTS[code]["name"],
            "SAP Qty (PKT)": sap_qty, "Source": "sheet", "Status": status, "Note": note,
        })
    return pd.DataFrame(rows, columns=["Customer", "FG Code", "Product", "SAP Qty (PKT)", "Source", "Status", "Note"])


def tabular_to_orders(frame) -> List[Order]:
    """Group mapped sheet rows into per-customer orders."""
    orders: List[Order] = []
    if frame is None or len(frame) == 0:
        return orders
    for customer, group in frame.groupby(frame["Customer"].fillna(""), sort=False):
        order = Order(customer=str(customer).strip())
        for _, row in group.iterrows():
            qty = row["SAP Qty (PKT)"]
            order.lines.append(OrderLine(
                source=f"{row['FG Code']} {row['Product']}".strip(),
                code=row["FG Code"] if row["Status"] == "OK" else None,
                product=row["Product"],
                quantity_text=f"{_num(qty)} PKT" if qty == qty and qty is not None else "",
                unit="PKT",
                sap_units=int(qty) if row["Status"] == "OK" and qty == qty and qty is not None else None,
                status=row["Status"],
                note=row.get("Note", ""),
            ))
        orders.append(order)
    return orders


# ============================================================================
# 8. TEACHING
# ============================================================================

_TEACH_CODE_RE = re.compile(r"\bfg[\s\-]?(\d{2})[\s\-]?(\d{4})\b", re.I)
_QUOTED_RE = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{2,40})[\"'“”‘’]")
_FILLER_RE = re.compile(
    r"^(?:customer\s+\S+\s+|the\s+|please\s+|always\s+)?"
    r"(?:calls?|call|names?|named|refers?\s+to|refer|use|uses|using|map|maps|mapped|treat|treats|"
    r"means|write[s]?|alias(?:\s+for)?|shortcut(?:\s+for)?|it)\s+",
    re.I,
)


def _alias_from_rule_text(text: str, code_start: int) -> str:
    quoted = _QUOTED_RE.findall(text)
    if quoted:
        return quoted[-1].strip()
    before = text[:code_start].strip()
    before = re.sub(r"\s*(?:means|is|are|=|->|→|:|as)\s*$", "", before, flags=re.I).strip(" .:-–—")
    previous = None
    while previous != before:
        previous = before
        before = _FILLER_RE.sub("", before).strip()
    words = before.split()
    return " ".join(words[-6:]) if len(words) > 6 else before


def teach_rule(rule_text: str, category: str = "general", customer: str = "",
               path: Optional[Path] = None) -> Tuple[bool, str]:
    text = str(rule_text or "").strip()
    if not text:
        return False, "Write a teaching rule first."
    rules = load_rules(path)
    match = _TEACH_CODE_RE.search(text)
    if match:
        code = f"FG-{match.group(1)}-{match.group(2)}"
        if code not in PRODUCTS:
            return False, f"{code} is not in the item master, so it cannot be taught."
        alias = _alias_from_rule_text(text, match.start())
        normalized = normalize(alias)
        if not normalized:
            return False, "Could not read the alias. Write it like: mf white dice = FG-02-0102"
        rules["product_aliases"] = [
            entry for entry in rules.get("product_aliases", [])
            if normalize(entry.get("alias", "")) != normalized
        ]
        rules["product_aliases"].append({"alias": alias, "code": code, "note": text, "source": "user"})
        save_rules(rules, path)
        return True, f"Saved product alias: {alias} → {code} ({PRODUCTS[code]['name']})"

    entry = {"rule": text, "customer": str(customer or "").strip(), "category": category}
    key = ("customer_rules" if entry["customer"] or category == "customer"
           else "quantity_rules" if category.startswith("quantity") else "general_rules")
    rules.setdefault(key, []).append(entry)
    save_rules(rules, path)
    return True, "Rule saved. It is shown in Parser Memory and applied as guidance."


__all__ = [
    "PRODUCTS", "Order", "OrderLine", "ProductMatch", "Quantity",
    "find_product", "has_wp", "is_customer_heading", "load_rules", "match_product",
    "normalize", "parse_line", "parse_order", "parse_quantity", "process_tabular",
    "sap_block", "sap_line", "sap_units", "save_rules", "tabular_to_orders", "teach_rule",
]
