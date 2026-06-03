#!/usr/bin/env python3
"""Build taxonomy.json (IA + filters) and catalog.json (per-product facet mapping)
from the scraped products.json. Re-runnable."""
import json, re, os
from collections import Counter, OrderedDict

HERE = os.path.dirname(__file__)
prods = json.load(open(os.path.join(HERE, "products.json")))

# --- current WooCommerce category -> new primary type ---
TYPE_MAP = {
    "Shorts": "shorts-pants", "Pants": "shorts-pants", "Bikini Bottoms": "shorts-pants",
    "T-Shirts": "tops", "Singlets": "tops", "Top Crop": "tops", "Polo Shirts": "tops",
    "Hoodies": "hoodies-jackets", "Jackets": "hoodies-jackets", "Sweater": "hoodies-jackets",
    "Rain Jacket": "hoodies-jackets", "Sweat Suit": "hoodies-jackets", "Jerseys": "jerseys",
    "Kneepads": "protective-gear", "Sleeves": "protective-gear", "Elbow Pads": "protective-gear",
    "Socks": "accessories", "Backpacks & Bags": "accessories", "Coaching": "coaching",
}
TYPE_PRIORITY = ["jerseys", "protective-gear", "coaching", "hoodies-jackets",
                 "shorts-pants", "tops", "accessories"]
TYPE_DEFS = OrderedDict([
    ("shorts-pants", "Shorts & Pants"), ("tops", "Tops"),
    ("hoodies-jackets", "Hoodies & Jackets"), ("jerseys", "Jerseys"),
    ("protective-gear", "Protective Gear"), ("accessories", "Accessories"),
    ("coaching", "Coaching"),
])
NAME_RULES = [
    ("jersey", "jerseys"), ("knee", "protective-gear"), ("elbow", "protective-gear"),
    ("sleeve", "protective-gear"), ("hoodie", "hoodies-jackets"), ("jacket", "hoodies-jackets"),
    ("sweat", "hoodies-jackets"), ("tracksuit", "hoodies-jackets"), ("pant", "shorts-pants"),
    ("short", "shorts-pants"), ("bikini", "shorts-pants"), ("singlet", "tops"), ("tee", "tops"),
    ("t-shirt", "tops"), ("t shirt", "tops"), ("shirt", "tops"), ("crop", "tops"),
    ("polo", "tops"), ("top", "tops"), ("sock", "accessories"), ("bag", "accessories"),
    ("backpack", "accessories"), ("cap", "accessories"), ("towel", "accessories"),
    ("tape", "accessories"), ("board", "coaching"),
]

def assign_type(p):
    cats = [TYPE_MAP[c] for c in p["categories"] if c in TYPE_MAP]
    for t in TYPE_PRIORITY:
        if t in cats:
            return t, "category"
    n = p["name"].lower()
    for kw, t in NAME_RULES:
        if kw in n:
            return t, "name-inferred"
    return "accessories", "fallback"

COLOUR_SYN = {
    "navy blue": "Navy", "navy": "Navy", "royal blue": "Royal Blue", "blue": "Blue",
    "sky blue": "Sky Blue", "light gray": "Grey", "gray": "Grey", "grey": "Grey",
    "black": "Black", "white": "White", "yellow": "Yellow", "red": "Red",
    "orange": "Orange", "green": "Green",
}
def norm_colours(attrs):
    out = []
    for k, v in attrs.items():
        if k.lower() in ("color", "colour"):
            for c in v:
                out.append(COLOUR_SYN.get(c.strip().lower(), c.strip().title()))
    return list(dict.fromkeys(out))

APPAREL_ORDER = ["4XS", "3XS", "2XS", "XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL"]
SIZE_SYN = {"XXS": "2XS", "XXXL": "3XL", "XXL": "2XL", "3X": "3XL", "SM": "S/M", "ML": "M/L"}
NUMERIC_SIZE = re.compile(r"^\d+(\s*-\s*\d+)?$")  # e.g. 36-41, 42 (sock/shoe ranges)

def norm_sizes(attrs):
    ap, num, raw = [], [], []
    for k, v in attrs.items():
        if k.lower() == "size":
            raw += v
    for s in raw:
        s = SIZE_SYN.get(s.strip().upper(), s.strip().upper())
        (num if NUMERIC_SIZE.match(s) else ap).append(s)
    ap = sorted(dict.fromkeys(ap),
                key=lambda x: APPAREL_ORDER.index(x) if x in APPAREL_ORDER else 99)
    return ap, list(dict.fromkeys(num))

def assign_surface(p):
    cats, n = p["categories"], p["name"].lower()
    if "Beach Volleyball" in cats or "Bikini Bottoms" in cats or "beach" in n:
        return "beach"
    if "Jerseys" in cats or "Kneepads" in cats or "Elbow Pads" in cats:
        return "indoor"
    return None

def assign_clubs(p):
    cats, n, c = p["categories"], p["name"].lower(), []
    if "ProVolley Academy" in cats or "provolley" in n:
        c.append("provolley-academy")
    if "Inner West Volley" in cats or "inner west" in n:
        c.append("inner-west-volley")
    if "Teamwear" in cats and not c:
        c.append("teamwear")
    return c

def assign_gender(p):
    cats, g = p["categories"], set()
    if "Women" in cats or "Top Crop" in cats or "Bikini Bottoms" in cats:
        g.add("women")
    for k, v in p["attributes"].items():
        if k.lower() == "gender":
            for x in v:
                if x.lower() in ("women", "female"):
                    g.add("women")
                if x.lower() in ("men", "male"):
                    g.add("men")
    return sorted(g) if g else ["unisex"]

# --- build catalog ---
catalog, inferred, sock_sized = [], [], []
for p in prods:
    t, how = assign_type(p)
    if how != "category":
        inferred.append((p["name"], t, how))
    ap, num = norm_sizes(p["attributes"])
    if num:
        sock_sized.append((p["name"], num))
    catalog.append({
        "id": p["id"], "name": p["name"], "slug": p["slug"], "type": p["type"],
        "price": p["price"], "currency": p["currency"], "on_sale": p["on_sale"],
        "in_stock": p["in_stock"], "image_local": p["image_local"],
        "primary_category": t, "surface": assign_surface(p), "clubs": assign_clubs(p),
        "gender": assign_gender(p), "colours": norm_colours(p["attributes"]),
        "sizes": ap, "numeric_sizes": num, "original_categories": p["categories"],
    })
json.dump(catalog, open(os.path.join(HERE, "catalog.json"), "w"), indent=2, ensure_ascii=False)

def count(field):
    c = Counter()
    for p in catalog:
        v = p[field]
        if isinstance(v, list):
            for x in v:
                c[x] += 1
        elif v is not None:
            c[v] += 1
    return c

tc, sc, cc = count("primary_category"), count("surface"), count("clubs")
gc, colc, szc = count("gender"), count("colours"), count("sizes")
prices = [p["price"] for p in catalog]

taxonomy = {
    "primary_nav": [
        {"id": k, "slug": k, "label": TYPE_DEFS[k], "count": tc.get(k, 0)} for k in TYPE_DEFS
    ],
    "collections": [
        {"id": "beach", "slug": "beach", "label": "Beach", "type": "surface", "count": sc.get("beach", 0)},
        {"id": "indoor", "slug": "indoor", "label": "Indoor", "type": "surface", "count": sc.get("indoor", 0)},
        {"id": "provolley-academy", "slug": "clubs/provolley-academy", "label": "ProVolley Academy", "type": "club", "count": cc.get("provolley-academy", 0)},
        {"id": "inner-west-volley", "slug": "clubs/inner-west-volley", "label": "Inner West Volley", "type": "club", "count": cc.get("inner-west-volley", 0)},
        {"id": "teamwear", "slug": "clubs/teamwear", "label": "Teamwear", "type": "club", "count": cc.get("teamwear", 0)},
        {"id": "new", "slug": "new-arrivals", "label": "New Arrivals", "type": "dynamic", "count": None},
        {"id": "sale", "slug": "sale", "label": "Sale", "type": "dynamic", "count": sum(1 for p in catalog if p["on_sale"])},
    ],
    "filters": [
        {"id": "gender", "label": "Gender", "type": "checkbox", "values": [{"value": k, "count": v} for k, v in gc.most_common()]},
        {"id": "surface", "label": "Surface", "type": "checkbox", "values": [{"value": k, "count": v} for k, v in sc.most_common()]},
        {"id": "colour", "label": "Colour", "type": "swatch", "values": [{"value": k, "count": v} for k, v in colc.most_common()]},
        {"id": "size", "label": "Size", "type": "checkbox", "values": [{"value": k, "count": szc[k]} for k in sorted(szc, key=lambda x: APPAREL_ORDER.index(x) if x in APPAREL_ORDER else 99)]},
        {"id": "price", "label": "Price", "type": "range", "min": min(prices), "max": max(prices)},
        {"id": "availability", "label": "Availability", "type": "checkbox", "values": [
            {"value": "in_stock", "count": sum(1 for p in catalog if p["in_stock"])},
            {"value": "on_sale", "count": sum(1 for p in catalog if p["on_sale"])}]},
    ],
    "sort_options": ["featured", "price-asc", "price-desc", "newest", "name-asc"],
}
json.dump(taxonomy, open(os.path.join(HERE, "taxonomy.json"), "w"), indent=2, ensure_ascii=False)

# --- report ---
print("PRIMARY CATEGORIES:")
for k in TYPE_DEFS:
    print(f"  {tc.get(k, 0):>3}  {TYPE_DEFS[k]}")
print(f"\nCOLLECTIONS: beach={sc.get('beach',0)} indoor={sc.get('indoor',0)} "
      f"general(no-surface)={sum(1 for p in catalog if p['surface'] is None)} | "
      f"provolley={cc.get('provolley-academy',0)} innerwest={cc.get('inner-west-volley',0)} teamwear={cc.get('teamwear',0)}")
print(f"GENDER: {dict(gc)}")
print(f"COLOURS ({len(colc)}): {dict(colc.most_common())}")
print(f"APPAREL SIZES: {[k for k in sorted(szc, key=lambda x: APPAREL_ORDER.index(x) if x in APPAREL_ORDER else 99)]}")
print(f"\n{len(inferred)} products had NO type-category (inferred from name):")
for n, t, how in inferred:
    print(f"   [{how}] {n[:48]:48} -> {t}")
print(f"\n{len(sock_sized)} products use numeric (sock) sizing: {[n[:30] for n, _ in sock_sized]}")
