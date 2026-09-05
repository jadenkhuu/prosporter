#!/usr/bin/env python3
"""Catalog normalization rules (execution plan section 7) and the storefront IA
mapping (mock-data/IA-SPEC.md, mock-data/build_taxonomy.py).

Pure functions only, so scripts/migration/tests can exercise every rule without
touching the exports.
"""
from __future__ import annotations

import re

from common import clean_text, slugify

# --------------------------------------------------------------------------
# Attribute names
# --------------------------------------------------------------------------
# How each WooCommerce attribute name is handled.
#   "option"   -> becomes a Shopify product option under the canonical name
#   "label"    -> not an axis; kept as a legacy tag, never an option
#   "decision" -> cannot be classified without a client decision; routed to the
#                 exception register instead of being guessed at
ATTRIBUTE_POLICY = {
    "color": ("option", "Colour"),
    "colour": ("option", "Colour"),
    "size": ("option", "Size"),
    "gender": ("option", "Gender"),
    # "Hats" holds one value per product that just restates the product name
    # ("Unisex Hats"); it is a label, not a variant axis.
    "hats": ("label", "Hats"),
    # "Condition" mixes goods condition (Used/Returned/Defect) with jersey
    # personalisation (With Surname/No Number). "Number" is a jersey number,
    # i.e. a line-item property, not a merchandising axis. Both need a client
    # decision before they can be modelled.
    "condition": ("decision", "Condition"),
    "number": ("decision", "Number"),
}

SHOPIFY_MAX_OPTIONS = 3

# --------------------------------------------------------------------------
# Option values
# --------------------------------------------------------------------------
COLOUR_SYNONYMS = {
    "navy blue": "Navy",
    "navy": "Navy",
    "gray": "Grey",
    "light gray": "Grey",
    "grey": "Grey",
    "light grey": "Grey",
    "royal blue": "Royal Blue",
    "sky blue": "Sky Blue",
    "black": "Black",
    "white": "White",
    "blue": "Blue",
    "red": "Red",
    "green": "Green",
    "orange": "Orange",
    "yellow": "Yellow",
    "pink": "Pink",
    "royal": "Royal",
}

SIZE_SYNONYMS = {
    "XXS": "2XS",
    "XXL": "2XL",
    "XXXL": "3XL",
    "3X": "3XL",
    "2X": "2XL",
    "SM": "S/M",
    "ML": "M/L",
}

GENDER_SYNONYMS = {
    "male": "Men",
    "man": "Men",
    "men": "Men",
    "mens": "Men",
    "female": "Women",
    "woman": "Women",
    "women": "Women",
    "womens": "Women",
    "unisex": "Unisex",
}

APPAREL_SIZE_ORDER = [
    "4XS", "3XS", "2XS", "XS", "S", "S/M", "M", "M/L", "L", "XL",
    "2XL", "3XL", "4XL", "5XL", "6XL", "7XL", "8XL",
]

# Sock/shoe sizing: "42", "36-41", "47 - 52".
NUMERIC_SIZE = re.compile(r"^\d+(\s*-\s*\d+)?$")


def is_numeric_size(value: str) -> bool:
    return bool(NUMERIC_SIZE.match(clean_text(value)))


def normalize_colour(value: str) -> str:
    value = clean_text(value)
    if not value:
        return value
    # "Black / Gray" is a two-tone swatch: normalise each half.
    if "/" in value:
        parts = [normalize_colour(part) for part in value.split("/")]
        return " / ".join(p for p in parts if p)
    return COLOUR_SYNONYMS.get(value.lower(), value.title())


def normalize_size(value: str) -> str:
    value = clean_text(value)
    if not value:
        return value
    if is_numeric_size(value):
        return re.sub(r"\s*-\s*", "-", value)
    upper = value.upper()
    return SIZE_SYNONYMS.get(upper, upper if len(upper) <= 4 else value)


def normalize_gender(value: str) -> str:
    value = clean_text(value)
    return GENDER_SYNONYMS.get(value.lower(), value.title())


def normalize_option_value(option_name: str, value: str) -> str:
    if option_name == "Colour":
        return normalize_colour(value)
    if option_name in ("Size", "Sock Size"):
        return normalize_size(value)
    if option_name == "Gender":
        return normalize_gender(value)
    return clean_text(value)


def size_option_name(values) -> str | None:
    """'Sock Size' when every value is numeric, 'Size' when none are.

    A product that mixes both in one attribute returns None so the caller can
    raise an exception rather than silently merging two sizing systems.
    """
    values = [v for v in values if clean_text(v)]
    if not values:
        return "Size"
    numeric = [is_numeric_size(v) for v in values]
    if all(numeric):
        return "Sock Size"
    if not any(numeric):
        return "Size"
    return None


def sort_option_values(option_name: str, values):
    """Deterministic ordering: apparel sizes in wearing order, rest alphabetical."""
    unique = list(dict.fromkeys(values))
    if option_name == "Size":
        return sorted(
            unique,
            key=lambda v: (APPAREL_SIZE_ORDER.index(v) if v in APPAREL_SIZE_ORDER else 99, v),
        )
    if option_name == "Sock Size":
        return sorted(unique, key=lambda v: (int(re.split(r"-", v)[0]), v))
    return sorted(unique)


# --------------------------------------------------------------------------
# SKUs
# --------------------------------------------------------------------------
def generate_sku(product_id, variation_id) -> str:
    """Deterministic placeholder for the 219 variations with no SKU."""
    return f"PS-{product_id}-{variation_id}"


# --------------------------------------------------------------------------
# Information architecture (approved storefront IA)
# --------------------------------------------------------------------------
# Product-type primary nav. Protective gear and coaching are folded into
# accessories per the approved IA.
TYPE_COLLECTIONS = [
    ("tops", "Tops"),
    ("shorts-pants", "Shorts & Pants"),
    ("hoodies-jackets", "Hoodies & Jackets"),
    ("jerseys", "Jerseys"),
    ("accessories", "Accessories"),
]
SURFACE_COLLECTIONS = [("beach", "Beach"), ("indoor", "Indoor")]
CLUB_COLLECTIONS = [
    ("provolley-academy", "ProVolley Academy"),
    ("inner-west-volley", "Inner West Volley"),
    ("teamwear", "Teamwear"),
]

CATEGORY_TO_TYPE = {
    "shorts": "shorts-pants",
    "pants": "shorts-pants",
    "bikini bottoms": "shorts-pants",
    "t-shirts": "tops",
    "singlets": "tops",
    "top crop": "tops",
    "polo shirts": "tops",
    "hoodies": "hoodies-jackets",
    "jackets": "hoodies-jackets",
    "sweater": "hoodies-jackets",
    "rain jacket": "hoodies-jackets",
    "sweat suit": "hoodies-jackets",
    "jerseys": "jerseys",
    "kneepads": "accessories",
    "sleeves": "accessories",
    "elbow pads": "accessories",
    "socks": "accessories",
    "backpacks & bags": "accessories",
    "ball cart / trolley": "accessories",
    "coaching": "accessories",
}

TYPE_PRIORITY = ["jerseys", "hoodies-jackets", "shorts-pants", "tops", "accessories"]

NAME_RULES = [
    ("jersey", "jerseys"),
    ("knee", "accessories"),
    ("elbow", "accessories"),
    ("sleeve", "accessories"),
    ("hoodie", "hoodies-jackets"),
    ("jacket", "hoodies-jackets"),
    ("sweat", "hoodies-jackets"),
    ("tracksuit", "hoodies-jackets"),
    ("jogger", "hoodies-jackets"),
    ("pant", "shorts-pants"),
    ("short", "shorts-pants"),
    ("bikini", "shorts-pants"),
    ("singlet", "tops"),
    ("tee", "tops"),
    ("t-shirt", "tops"),
    ("t shirt", "tops"),
    ("polo", "tops"),
    ("crop", "tops"),
    ("shirt", "tops"),
    ("top", "tops"),
    ("sock", "accessories"),
    ("bag", "accessories"),
    ("backpack", "accessories"),
    ("cart", "accessories"),
    ("hat", "accessories"),
    ("cap", "accessories"),
    ("towel", "accessories"),
    ("tape", "accessories"),
    ("board", "accessories"),
]


def assign_product_type(category_names, product_name):
    """Return (type_handle, how) where how is category|name-inferred|fallback."""
    lowered = [clean_text(c).lower() for c in category_names]
    mapped = [CATEGORY_TO_TYPE[c] for c in lowered if c in CATEGORY_TO_TYPE]
    for candidate in TYPE_PRIORITY:
        if candidate in mapped:
            return candidate, "category"
    name = clean_text(product_name).lower()
    for keyword, candidate in NAME_RULES:
        if keyword in name:
            return candidate, "name-inferred"
    return "accessories", "fallback"


def assign_surface(category_names, product_name):
    lowered = [clean_text(c).lower() for c in category_names]
    name = clean_text(product_name).lower()
    if "beach volleyball" in lowered or "bikini bottoms" in lowered or "beach" in name:
        return "beach"
    if {"jerseys", "kneepads", "elbow pads"} & set(lowered):
        return "indoor"
    return None


def assign_clubs(category_names, product_name):
    lowered = [clean_text(c).lower() for c in category_names]
    name = clean_text(product_name).lower()
    clubs = []
    if "provolley academy" in lowered or "provolley" in name:
        clubs.append("provolley-academy")
    if "inner west volley" in lowered or "inner west" in name:
        clubs.append("inner-west-volley")
    if "teamwear" in lowered and not clubs:
        clubs.append("teamwear")
    return clubs


def assign_gender(category_names, attribute_values):
    """Gender for the prosporter.gender metafield (a filter axis, not a category)."""
    lowered = [clean_text(c).lower() for c in category_names]
    found = set()
    if {"women", "top crop", "bikini bottoms"} & set(lowered):
        found.add("Women")
    for value in attribute_values:
        normalized = normalize_gender(value)
        if normalized in ("Men", "Women"):
            found.add(normalized)
    return sorted(found) if found else ["Unisex"]


def legacy_tag(category_name: str) -> str:
    """Every original category name survives as a tag for traceability."""
    return f"legacy:{slugify(category_name)}"
