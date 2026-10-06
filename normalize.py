"""Turn messy site/CRM values into comparable keys.

Every function here is pure (string in, string out) so it is easy to test
and easy to extend live: add a pair to one of the dicts below.
"""
import re
from difflib import SequenceMatcher

# Street suffixes -> one canonical abbreviation.
SUFFIXES = {
    "ROAD": "RD", "STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "LANE": "LN",
    "BOULEVARD": "BLVD", "BLV": "BLVD", "DRIVE": "DR", "COURT": "CT", "PLACE": "PL",
    "PIKE": "PIKE", "PK": "PIKE", "PARKWAY": "PKWY", "HIGHWAY": "HWY", "CIRCLE": "CIR",
    "TERRACE": "TER", "TRAIL": "TRL", "SQUARE": "SQ", "SAINT": "ST",
}
DIRECTIONALS = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}
# Site label -> CRM care_type value.
CARE_MAP = {
    "short-term rehabilitation & nursing": "Skilled Nursing",
    "short-term rehabilitation and nursing": "Skilled Nursing",
    "memory support": "Memory Care",
    "assisted living": "Assisted Living",
}
# Word-level spelling variants used in names.
NAME_WORDS = {"centre": "center", "&": "and"}

PO_BOX = re.compile(r"\bP\.?\s*O\.?\s*BOX\b|\bPOST OFFICE BOX\b", re.I)


def street(value):
    """'1250 NW Franklin Street' -> '1250 NW FRANKLIN ST'."""
    if not value:
        return ""
    value = value.upper().replace("&", " AND ")
    value = re.sub(r"[.,#]", " ", value)
    tokens = [DIRECTIONALS.get(t, SUFFIXES.get(t, t)) for t in value.split()]
    return " ".join(tokens)


def is_po_box(value):
    return bool(value and PO_BOX.search(value))


def zip5(value):
    digits = re.sub(r"\D", "", value or "")
    return digits[:5]


def phone(value):
    """Keep the last 10 digits so '+1 (614) 555-1234' == '614.555.1234'."""
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else ""


def name(value):
    """'Bellhaven Healthcare Centre & Rehab' -> 'bellhaven healthcare center and rehab'."""
    value = (value or "").lower().replace("&", " & ")
    value = re.sub(r"[^\w&\s]", " ", value)
    return " ".join(NAME_WORDS.get(w, w) for w in value.split())


def person(value):
    return " ".join(re.sub(r"[^\w\s]", " ", (value or "").lower()).split())


def name_similarity(a, b):
    """0..1 similarity of normalized names. Supporting evidence only, never a match on its own."""
    return round(SequenceMatcher(None, name(a), name(b)).ratio(), 2)


def care(label):
    return CARE_MAP.get((label or "").strip().lower(), (label or "").strip())


def address_key(street_value, zip_value):
    """The primary match key: normalized street + 5-digit zip."""
    return f"{street(street_value)}|{zip5(zip_value)}"
