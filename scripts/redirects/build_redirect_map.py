#!/usr/bin/env python3
"""Build the complete ProSporter legacy URL redirect map (CLNT-175).

Reads the git-ignored authenticated WooCommerce/WordPress exports in ``exports/``
and emits the PII-free redirect artefacts in ``docs/redirects/``:

  * redirect-map.csv        one row per normalized legacy path, exactly one outcome
  * redirects.json          the Next.js ``redirects()`` payload (nextjs-owned 301s)
  * gone.json               source paths that must answer 410
  * README.md               counts, mapping tables, decisions, rerun instructions

Python 3 standard library only. Deterministic and re-runnable: the same exports
always produce byte-identical output.

    python3 scripts/redirects/build_redirect_map.py

No customer, order, address or account data is read or written.
"""

from __future__ import annotations

import csv
import html
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from urllib.parse import parse_qsl, unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXPORTS = os.path.join(ROOT, "exports")
OUT = os.path.join(ROOT, "docs", "redirects")

LEGACY_HOSTS = {"prosporter.com.au", "www.prosporter.com.au"}

# Query params that survive normalization/attribution. Everything else is
# dropped from the source inventory key. See README "Query parameters".
TRACKING_ALLOWLIST = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
)

# ---------------------------------------------------------------------------
# Approved storefront IA (mock-data/taxonomy.json + src/lib/catalog.ts routes)
# ---------------------------------------------------------------------------

SHOP_ALL = "/shop"
TYPE_ROUTES = {
    "tops": "/shop/tops",
    "shorts-pants": "/shop/shorts-pants",
    "hoodies-jackets": "/shop/hoodies-jackets",
    "jerseys": "/shop/jerseys",
    "accessories": "/shop/accessories",
}
SURFACE_ROUTES = {"beach": "/shop/beach", "indoor": "/shop/indoor"}
CLUB_ROUTES = {
    "provolley-academy": "/shop/clubs/provolley-academy",
    "inner-west-volley": "/shop/clubs/inner-west-volley",
    "teamwear": "/shop/clubs/teamwear",
}
BLOG_INDEX = "/blog"

# Legacy WooCommerce product_cat slug -> approved destination.
# Derived from mock-data/build_taxonomy.py TYPE_MAP, with protective-gear and
# coaching folded into accessories (commits 6293089, fcc9c6d).
CATEGORY_MAP = {
    # product type
    "t-shirts": ("tops", "type: T-Shirts -> Tops"),
    "singlets": ("tops", "type: Singlets -> Tops"),
    "top-crop": ("tops", "type: Top Crop -> Tops"),
    "polo-shirts": ("tops", "type: Polo Shirts -> Tops"),
    "shorts": ("shorts-pants", "type: Shorts -> Shorts & Pants"),
    "pants": ("shorts-pants", "type: Pants -> Shorts & Pants"),
    "bikini-bottoms": (
        "shorts-pants",
        "type axis wins over surface: Bikini Bottoms -> Shorts & Pants",
    ),
    "hoodies": ("hoodies-jackets", "type: Hoodies -> Hoodies & Jackets"),
    "jackets": ("hoodies-jackets", "type: Jackets -> Hoodies & Jackets"),
    "rain-jacket": ("hoodies-jackets", "type: Rain Jacket -> Hoodies & Jackets"),
    "sweater": ("hoodies-jackets", "type: Sweater -> Hoodies & Jackets"),
    "sweat-suit": (
        "hoodies-jackets",
        "singleton legacy category folded into Hoodies & Jackets (IA-SPEC rule 5)",
    ),
    "jerseys": ("jerseys", "type: Jerseys -> Jerseys"),
    "socks": ("accessories", "type: Socks -> Accessories"),
    "backpacks-bags": ("accessories", "type: Backpacks & Bags -> Accessories"),
    # protective gear folded into accessories
    "kneepads": ("accessories", "protective gear folded into Accessories"),
    "sleeves": ("accessories", "protective gear folded into Accessories"),
    "elbow-pads": ("accessories", "protective gear folded into Accessories"),
    # coaching / equipment folded into accessories
    "coaching": ("accessories", "coaching folded into Accessories"),
    "ball-cart-trolley": (
        "accessories",
        "coaching/equipment singleton folded into Accessories",
    ),
    # surface axis
    "beach-volleyball": ("beach", "surface axis -> Beach collection"),
    # club axis
    "teamwear": ("teamwear", "club axis -> Clubs & Teams / Teamwear"),
    "provolley-academy": ("provolley-academy", "club axis -> ProVolley Academy"),
    "inner-west-volley": ("inner-west-volley", "club axis -> Inner West Volley"),
}
# Categories with no defensible single destination.
CATEGORY_CLIENT_DECISION = {
    "women": "gender is a filter axis in the approved IA, not a collection route; "
    "client to choose a filtered landing page or retirement",
}


def _dest_for_axis(key: str) -> str:
    if key in TYPE_ROUTES:
        return TYPE_ROUTES[key]
    if key in SURFACE_ROUTES:
        return SURFACE_ROUTES[key]
    if key in CLUB_ROUTES:
        return CLUB_ROUTES[key]
    raise KeyError(key)


# product_tag slug -> axis. Precedence: club > surface > type > brand > generic.
TAG_CLUB_TOKENS = (
    ("inner-west-volley", "inner-west-volley"),
    ("provolley", "provolley-academy"),
    ("teamwear", "teamwear"),
)
TAG_SURFACE_TOKENS = (("beach", "beach"), ("indoor", "indoor"))
TAG_TYPE_TOKENS = (
    ("jersey", "jerseys"),
    ("uniform", "jerseys"),
    ("polo", "tops"),
    ("t-shirt", "tops"),
    ("tshirt", "tops"),
    ("shirt", "tops"),
    ("singlet", "tops"),
    ("crop", "tops"),
    ("hoodie", "hoodies-jackets"),
    ("jacket", "hoodies-jackets"),
    ("sweater", "hoodies-jackets"),
    ("jumper", "hoodies-jackets"),
    ("tracksuit", "hoodies-jackets"),
    ("short", "shorts-pants"),
    ("pant", "shorts-pants"),
    ("sock", "accessories"),
    ("bag", "accessories"),
    ("backpack", "accessories"),
    ("kneepad", "accessories"),
    ("knee-pad", "accessories"),
)
# Tag slugs that name a brand. No brand collection exists in the approved IA.
TAG_BRANDS = {
    "ninesquared",
    "nine-australia",
    "nine-volleyball-apparel",
    "prosporter",
    "sette",
    "varone",
}
# Tag slugs that are internal merchandising flags, not public archives.
TAG_INTERNAL = {"homepage"}
# "uniform" is a kit, not a single approved type: implement now, confirm later.
TAG_SOFT_FLAG_TOKENS = ("uniform",)


def classify_tag(slug: str, count: int, in_sitemap: bool):
    """Return (outcome, destination, reason, needs_client_decision)."""
    for token, club in TAG_CLUB_TOKENS:
        if token in slug:
            return (
                "301",
                CLUB_ROUTES[club],
                f"club axis: tag contains '{token}'",
                False,
            )
    for token, surface in TAG_SURFACE_TOKENS:
        if re.search(rf"(^|-){token}(-|$)", slug):
            return (
                "301",
                SURFACE_ROUTES[surface],
                f"surface axis: tag contains '{token}'",
                False,
            )
    for token, type_id in TAG_TYPE_TOKENS:
        if token in slug:
            return (
                "301",
                TYPE_ROUTES[type_id],
                f"type axis: tag contains '{token}'",
                any(t in slug for t in TAG_SOFT_FLAG_TOKENS),
            )
    if slug in TAG_BRANDS:
        return (
            "client_decision",
            "",
            "brand tag; the approved IA has no brand collection - client to decide "
            "a Shopify vendor collection or retirement",
            True,
        )
    if slug in TAG_INTERNAL:
        return (
            "410",
            "",
            "internal merchandising flag with no user-facing equivalent",
            False,
        )
    if count == 0 and not in_sitemap:
        return ("410", "", "empty tag archive, not in the Yoast sitemap", False)
    return (
        "301",
        SHOP_ALL,
        "geographic/marketing SEO tag with no approved collection; Shop All is the "
        "nearest genuine listing (never the home page)",
        True,
    )


# ---------------------------------------------------------------------------
# Page dispositions (exports/pages.json slugs)
# ---------------------------------------------------------------------------
# slug -> (outcome, destination, owner, reason, needs_client_decision)
PAGE_MAP = {
    "": ("same_url", "/", "nextjs", "home page, path preserved", False),
    "about": ("same_url", "/about", "nextjs", "content page, path preserved", False),
    "contact": ("same_url", "/contact", "nextjs", "content page, path preserved", False),
    "faq": ("same_url", "/faq", "nextjs", "content page, path preserved", False),
    "size-guide": (
        "same_url",
        "/size-guide",
        "nextjs",
        "content page, path preserved",
        False,
    ),
    "privacy-policy": (
        "same_url",
        "/privacy-policy",
        "nextjs",
        "policy page, path preserved",
        False,
    ),
    "refund-policy": (
        "same_url",
        "/refund-policy",
        "nextjs",
        "policy page, path preserved",
        False,
    ),
    "terms-of-service": (
        "same_url",
        "/terms-of-service",
        "nextjs",
        "policy page, path preserved",
        False,
    ),
    "blog": ("same_url", "/blog", "nextjs", "blog index, path preserved", False),
    "blog-2": ("301", "/blog", "nextjs", "duplicate '-2' page -> canonical sibling", False),
    "shop-sporter": (
        "301",
        SHOP_ALL,
        "nextjs",
        "legacy WooCommerce shop base -> Shop All",
        False,
    ),
    "collections": (
        "301",
        SHOP_ALL,
        "nextjs",
        "thin brand 'collections' page -> Shop All (nearest genuine listing)",
        False,
    ),
    "knee-pads": (
        "301",
        "/shop/accessories",
        "nextjs",
        "knee-pad landing page; protective gear folded into Accessories",
        False,
    ),
    "cart": (
        "410",
        "",
        "shopify",
        "WooCommerce cart retired; the cart is a storefront drawer and checkout is "
        "Shopify-hosted (Shopify owns the checkout path)",
        False,
    ),
    "cart-2": ("410", "", "shopify", "duplicate of the retired WooCommerce cart page", False),
    "checkout": (
        "410",
        "",
        "shopify",
        "checkout moves to Shopify-hosted checkout (Shopify owns the path)",
        False,
    ),
    "checkout-2": ("410", "", "shopify", "duplicate of the retired checkout page", False),
    "my-account": (
        "410",
        "",
        "shopify",
        "customer accounts move to Shopify-hosted new customer accounts "
        "(Shopify owns the path)",
        False,
    ),
    "my-account-2": ("410", "", "shopify", "duplicate of the retired my-account page", False),
    "wishlist": (
        "410",
        "",
        "nextjs",
        "Wishlist plugin excluded from migration by data evidence (audit README)",
        False,
    ),
    "wishlist-2": ("410", "", "nextjs", "duplicate of the retired wishlist page", False),
    "cancel-request-form": ("410", "", "nextjs", "RMA plugin form; archive only, no Shopify equivalent", False),
    "exchange-request-form": ("410", "", "nextjs", "RMA plugin form; archive only, no Shopify equivalent", False),
    "guest-request-form": ("410", "", "nextjs", "RMA plugin form; archive only, no Shopify equivalent", False),
    "refund-request-form": ("410", "", "nextjs", "RMA plugin form; archive only, no Shopify equivalent", False),
    "view-order-msg": ("410", "", "nextjs", "empty RMA plugin page", False),
    "1687-2": (
        "client_decision",
        "",
        "none",
        "untitled duplicate page containing only WooCommerce filter widgets; "
        "client to confirm retirement",
        True,
    ),
}

# ---------------------------------------------------------------------------
# Static system URLs
# ---------------------------------------------------------------------------
SYSTEM_URLS = [
    # (path, source_type, outcome, destination, owner, reason, needs_decision)
    ("/shop", "woo_system", "same_url", SHOP_ALL, "nextjs",
     "storefront Shop All; the legacy Woo shop base was /shop-sporter", False),
    ("/cart", "woo_system", "410", "", "shopify",
     "WooCommerce cart retired; checkout is Shopify-hosted", False),
    ("/checkout", "woo_system", "410", "", "shopify",
     "checkout moves to Shopify-hosted checkout", False),
    ("/checkout/order-received", "woo_system", "410", "", "shopify",
     "order-received endpoint; Shopify owns the order status page", False),
    ("/checkout/order-pay", "woo_system", "410", "", "shopify",
     "pay-for-order endpoint; Shopify owns checkout", False),
    ("/order-received/thank-you", "woo_system", "410", "", "shopify",
     "XLWCTY custom thank-you page; Shopify owns the order status page", False),
    ("/my-account", "woo_system", "410", "", "shopify",
     "customer accounts move to Shopify-hosted new customer accounts", False),
    ("/my-account/orders", "woo_system", "410", "", "shopify",
     "account endpoint; Shopify owns customer accounts", False),
    ("/my-account/edit-address", "woo_system", "410", "", "shopify",
     "account endpoint; Shopify owns customer accounts", False),
    ("/my-account/edit-account", "woo_system", "410", "", "shopify",
     "account endpoint; Shopify owns customer accounts", False),
    ("/my-account/lost-password", "woo_system", "410", "", "shopify",
     "account endpoint; Shopify owns customer accounts", False),
    ("/my-account/downloads", "woo_system", "410", "", "shopify",
     "account endpoint; Shopify owns customer accounts", False),
    ("/wishlist", "woo_system", "410", "", "nextjs",
     "Wishlist plugin excluded from migration by data evidence", False),
    ("/carousels-category/home", "theme_taxonomy", "410", "", "nextjs",
     "theme carousel taxonomy archive; not user-facing content", False),
    ("/author/prosporter-com-au", "author_archive", "410", "", "nextjs",
     "author archives retired; the storefront blog has a single flat index", False),
    ("/brand/ninesquared", "product_brand", "client_decision", "", "none",
     "product brand archive; the approved IA has no brand collection - client to "
     "decide a Shopify vendor collection or retirement", True),
    ("/?s=", "search", "410", "", "nextjs",
     "WordPress search endpoint; storefront search is a future route and cannot be "
     "matched by a path redirect", False),
]

# On-page action links injected by WooCommerce and by plugins that are excluded
# from the migration. They are never indexed and never linked from off-site, so
# they are dropped from the source inventory rather than given an outcome.
PLUGIN_ACTION_PARAMS = {
    "add_to_wishlist",
    "quick_view_button",
    "add-to-cart",
    "remove_item",
    "removed_item",
    "undo_item",
    "wc-ajax",
    "filtering",
    "filter_",
    "orderby",
    "product-page",
    "really_curr_tax",
    "min_price",
    "max_price",
}

FEED_PATHS = [
    ("/feed", "site feed"),
    ("/comments/feed", "site comments feed"),
    ("/blog/feed", "blog page feed"),
    ("/shop-sporter/feed", "shop page feed"),
]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize(url: str) -> str | None:
    """Normalize a legacy URL to a comparable path (+ structural query).

    Strips the legacy host, lowercases, collapses slashes, removes the trailing
    slash (except for the root) and drops every tracking parameter in
    TRACKING_ALLOWLIST. Returns None for off-site, mailto and asset URLs.
    """
    if not url:
        return None
    url = html.unescape(url.strip())
    if url.startswith(("mailto:", "tel:", "#", "javascript:")):
        return None
    parts = urlsplit(url)
    if parts.netloc and parts.netloc.lower() not in LEGACY_HOSTS:
        return None
    path = unquote(parts.path or "/").lower()
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith("/wp-json") or path.startswith("/wp-admin"):
        return None
    if re.search(r"\.(png|jpe?g|gif|webp|svg|pdf|css|js|ico)$", path):
        return None
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_ALLOWLIST
    ]
    if kept and all(k.lower() in PLUGIN_ACTION_PARAMS for k, _ in kept):
        return None
    if kept:
        return path + "?" + "&".join(f"{k}={v}" for k, v in sorted(kept))
    if parts.query and not kept:
        return path
    return path


# ---------------------------------------------------------------------------
# Row registry
# ---------------------------------------------------------------------------


class Registry:
    def __init__(self) -> None:
        self.rows: "OrderedDict[str, dict]" = OrderedDict()

    def add(
        self,
        source_path: str,
        source_type: str,
        source_status: str,
        outcome: str,
        destination: str,
        owner: str,
        reason: str,
        needs_client_decision: bool,
        evidence: str,
    ) -> None:
        if source_path is None:
            return
        existing = self.rows.get(source_path)
        if existing:
            # First registration wins the disposition; later discoveries only
            # contribute evidence (keeps the map deterministic).
            if evidence and evidence not in existing["evidence"]:
                existing["evidence"] = existing["evidence"] + "; " + evidence
            return
        self.rows[source_path] = {
            "source_path": source_path,
            "source_type": source_type,
            "source_status": source_status,
            "outcome": outcome,
            "destination": destination,
            "status_code": "",
            "owner": owner,
            "reason": reason,
            "needs_client_decision": "true" if needs_client_decision else "false",
            "evidence": evidence,
        }

    def note(self, source_path: str, evidence: str) -> bool:
        row = self.rows.get(source_path)
        if row is None:
            return False
        if evidence and evidence not in row["evidence"]:
            row["evidence"] = row["evidence"] + "; " + evidence
        return True


def load(name: str):
    with open(os.path.join(EXPORTS, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    if not os.path.isdir(EXPORTS):
        print(
            f"error: {EXPORTS} not found. Run scripts/audit/woo_audit.py first.",
            file=sys.stderr,
        )
        return 1

    products = load("products")
    product_categories = load("product_categories")
    product_tags = load("product_tags")
    pages = load("pages")
    posts = load("posts")
    post_categories = load("post_categories")
    post_tags = load("post_tags")
    menu_items = load("menu_items")
    sitemap_urls = load("sitemap_urls")

    sitemap_by_norm: dict[str, list[str]] = {}
    for entry in sitemap_urls:
        n = normalize(entry["loc"])
        if n:
            sitemap_by_norm.setdefault(n, []).append(entry["sitemap"])

    reg = Registry()
    published_product_slugs = {p["slug"] for p in products if p["status"] == "publish"}
    all_product_slugs = {p["slug"] for p in products}

    def sitemap_evidence(path: str) -> str:
        files = sitemap_by_norm.get(path)
        return "sitemap:" + ",".join(sorted(set(files))) if files else ""

    # --- 1. products ------------------------------------------------------
    dirty_slug_notes = []
    for p in sorted(products, key=lambda x: x["slug"]):
        slug = p["slug"]
        status = p["status"]
        path = f"/product/{slug}"
        ev = "exports/products.json"
        sm = sitemap_evidence(path)
        if sm:
            ev += "; " + sm
        if status != "publish":
            reg.add(
                path,
                "product",
                status,
                "client_decision",
                "",
                "none",
                "draft product has no public legacy URL; client to confirm whether it "
                "is published on Shopify (then same path) or retired",
                True,
                ev + f"; no public permalink (?post_type=product&p={p['id']})",
            )
            continue
        base = re.sub(r"-2$", "", slug)
        if slug.endswith("-2") and base in all_product_slugs:
            dirty_slug_notes.append(slug)
            reg.add(
                path,
                "product",
                status,
                "client_decision",
                "",
                "none",
                f"duplicate handle: '{slug}' and '{base}' are both live products; "
                "client to pick the canonical handle before the loser is 301'd",
                True,
                ev,
            )
            continue
        if slug.endswith("-2"):
            dirty_slug_notes.append(slug)
            reg.add(
                path,
                "product",
                status,
                "client_decision",
                "",
                "none",
                f"dirty '-2' handle with no canonical sibling; client to approve a "
                "clean Shopify handle (then the legacy path 301s to it)",
                True,
                ev,
            )
            continue
        reg.add(
            path,
            "product",
            status,
            "same_url",
            path,
            "nextjs",
            "product handle is clean and preserved 1:1 on /product/<slug>",
            False,
            ev,
        )

    # --- 2. Yoast product redirect origins (chains collapsed) -------------
    raw_yoast: dict[str, str] = {}
    for p in products:
        for meta in p.get("meta_data", []):
            if meta.get("key") != "_yoast_post_redirect_info":
                continue
            value = meta.get("value")
            if not isinstance(value, dict):
                continue
            origin = normalize("/" + str(value.get("origin", "")).lstrip("/"))
            target = normalize("/" + str(value.get("target", "")).lstrip("/"))
            if origin and target and origin != target:
                raw_yoast[origin] = target

    def resolve_chain(target: str, seen: set[str]) -> str:
        while target in raw_yoast and target not in seen:
            seen.add(target)
            target = raw_yoast[target]
        return target

    for origin in sorted(raw_yoast):
        final = resolve_chain(raw_yoast[origin], {origin})
        hops = final != raw_yoast[origin]
        target_slug = final.rsplit("/", 1)[-1]
        if target_slug in published_product_slugs:
            reg.add(
                origin,
                "yoast_redirect",
                "gone",
                "301",
                final,
                "nextjs",
                "Yoast Premium redirect from the source site"
                + (", chain collapsed to the final destination" if hops else ""),
                False,
                "exports/products.json:_yoast_post_redirect_info",
            )
        else:
            reg.add(
                origin,
                "yoast_redirect",
                "gone",
                "client_decision",
                "",
                "none",
                f"Yoast redirect target '{final}' is not a published product; client "
                "to confirm the replacement",
                True,
                "exports/products.json:_yoast_post_redirect_info",
            )

    # --- 3. pages ---------------------------------------------------------
    for pg in sorted(pages, key=lambda x: (x["slug"], x["id"])):
        slug = pg["slug"]
        status = pg["status"]
        if not slug:
            path = f"/?page_id={pg['id']}"
            reg.add(
                path,
                "page",
                status,
                "client_decision",
                "",
                "none",
                "draft page with no slug and no public path; query-only legacy URL "
                "cannot be matched by a path redirect",
                True,
                "exports/pages.json",
            )
            continue
        path = "/" + slug if slug != "home" else "/"
        if slug == "home":
            slug_key = ""
        else:
            slug_key = slug
        mapping = PAGE_MAP.get(slug_key)
        ev = "exports/pages.json"
        sm = sitemap_evidence(path)
        if sm:
            ev += "; " + sm
        if mapping is None:
            reg.add(
                path,
                "page",
                status,
                "client_decision",
                "",
                "none",
                "page has no approved storefront equivalent; client to confirm "
                "migration or retirement",
                True,
                ev,
            )
            continue
        outcome, dest, owner, reason, needs = mapping
        reg.add(path, "page", status, outcome, dest, owner, reason, needs, ev)

    # --- 4. posts ---------------------------------------------------------
    demo_post_slugs = set()
    for po in sorted(posts, key=lambda x: x["slug"]):
        slug = po["slug"]
        path = "/" + slug
        ev = "exports/posts.json"
        sm = sitemap_evidence(path)
        if sm:
            ev += "; " + sm
        if re.fullmatch(r"\d+", slug):
            reg.add(
                path,
                "post",
                po["status"],
                "client_decision",
                "",
                "none",
                "numeric post slug with no title-derived handle; client to approve a "
                "clean /blog/<slug> handle or retirement",
                True,
                ev,
            )
            continue
        # Theme demo content (beauty/skin care) unrelated to the ProSporter brand.
        is_demo = any(
            cid in (22, 23, 24, 25, 27) for cid in po.get("categories", [])
        )
        if is_demo:
            demo_post_slugs.add(slug)
        reg.add(
            path,
            "post",
            po["status"],
            "301",
            f"{BLOG_INDEX}/{slug}",
            "nextjs",
            "post handle preserved under the /blog prefix"
            + (
                "; theme demo content unrelated to ProSporter - recommend retirement, "
                "client to confirm"
                if is_demo
                else ""
            ),
            is_demo,
            ev,
        )

    # --- 5. product categories -------------------------------------------
    cat_by_id = {c["id"]: c for c in product_categories}

    def cat_paths(cat) -> list[str]:
        """Hierarchical path plus the bare-slug path (both are linkable)."""
        chain = [cat["slug"]]
        parent = cat["parent"]
        guard = 0
        while parent and parent in cat_by_id and guard < 6:
            chain.insert(0, cat_by_id[parent]["slug"])
            parent = cat_by_id[parent]["parent"]
            guard += 1
        out = ["/product-category/" + "/".join(chain)]
        bare = "/product-category/" + cat["slug"]
        if bare not in out:
            out.append(bare)
        return out

    for cat in sorted(product_categories, key=lambda x: x["slug"]):
        slug = cat["slug"]
        for idx, path in enumerate(cat_paths(cat)):
            ev = f"exports/product_categories.json (count={cat['count']})"
            sm = sitemap_evidence(path)
            if sm:
                ev += "; " + sm
            elif idx == 1:
                ev += "; non-hierarchical alias path"
            if slug in CATEGORY_CLIENT_DECISION:
                reg.add(
                    path,
                    "product_category",
                    "publish",
                    "client_decision",
                    "",
                    "none",
                    CATEGORY_CLIENT_DECISION[slug],
                    True,
                    ev,
                )
                continue
            key, reason = CATEGORY_MAP[slug]
            reg.add(
                path,
                "product_category",
                "publish",
                "301",
                _dest_for_axis(key),
                "nextjs",
                reason,
                False,
                ev,
            )

    # --- 6. product tags --------------------------------------------------
    for tag in sorted(product_tags, key=lambda x: x["slug"]):
        path = "/product-tag/" + tag["slug"]
        sm = sitemap_evidence(path)
        ev = f"exports/product_tags.json (count={tag['count']})"
        if sm:
            ev += "; " + sm
        outcome, dest, reason, needs = classify_tag(
            tag["slug"], tag["count"], bool(sm)
        )
        owner = "nextjs" if outcome in ("301", "410") else "none"
        reg.add(path, "product_tag", "publish", outcome, dest, owner, reason, needs, ev)

    # --- 7. post categories, tags, feeds ---------------------------------
    for cat in sorted(post_categories, key=lambda x: x["slug"]):
        path = "/category/" + cat["slug"]
        ev = f"exports/post_categories.json (count={cat['count']})"
        sm = sitemap_evidence(path)
        if sm:
            ev += "; " + sm
        reg.add(
            path,
            "post_category",
            "publish",
            "301",
            BLOG_INDEX,
            "nextjs",
            "the storefront blog has a single flat index; no category archives",
            False,
            ev,
        )
    for tag in sorted(post_tags, key=lambda x: x["slug"]):
        path = "/tag/" + tag["slug"]
        ev = f"exports/post_tags.json (count={tag['count']})"
        sm = sitemap_evidence(path)
        if sm:
            ev += "; " + sm
        reg.add(
            path,
            "post_tag",
            "publish",
            "301",
            BLOG_INDEX,
            "nextjs",
            "the storefront blog has a single flat index; no tag archives",
            False,
            ev,
        )

    # --- 8. WooCommerce/WordPress system URLs ----------------------------
    for path, stype, outcome, dest, owner, reason, needs in SYSTEM_URLS:
        ev = "system URL (WooCommerce/WordPress convention)"
        sm = sitemap_evidence(path)
        if sm:
            ev += "; " + sm
        reg.add(path, stype, "publish", outcome, dest, owner, reason, needs, ev)

    feed_paths = list(FEED_PATHS)
    feed_paths += [(f"/category/{c['slug']}/feed", "post category feed") for c in post_categories]
    feed_paths += [(f"/tag/{t['slug']}/feed", "post tag feed") for t in post_tags]
    for path, label in sorted(feed_paths):
        reg.add(
            path,
            "feed",
            "publish",
            "410",
            "",
            "nextjs",
            f"RSS {label} retired; the storefront publishes no feeds",
            False,
            "WordPress feed convention",
        )

    # --- 9. sitemap URLs not covered above --------------------------------
    for path in sorted(sitemap_by_norm):
        if reg.note(path, sitemap_evidence(path)):
            continue
        reg.add(
            path,
            "sitemap_other",
            "publish",
            "client_decision",
            "",
            "none",
            "indexed URL with no matching entity in the exports; client to confirm",
            True,
            sitemap_evidence(path),
        )

    # --- 10. menu items ---------------------------------------------------
    for item in menu_items:
        path = normalize(item.get("url") or "")
        if not path:
            continue
        if reg.note(path, "menu_items.json"):
            continue
        reg.add(
            path,
            "menu_link",
            "publish",
            "client_decision",
            "",
            "none",
            "navigation link with no matching entity in the exports",
            True,
            "menu_items.json",
        )

    # --- 11. internal links in page/post HTML ----------------------------
    link_counts: Counter[str] = Counter()
    for collection in (pages, posts):
        for item in collection:
            rendered = (item.get("content") or {}).get("rendered", "") or ""
            for match in re.finditer(r'href=["\']([^"\']+)["\']', rendered):
                n = normalize(match.group(1))
                if n:
                    link_counts[n] += 1
    page_path_by_id = {
        pg["id"]: ("/" if pg["slug"] == "home" else "/" + pg["slug"])
        for pg in pages
        if pg["slug"]
    }
    for path in sorted(link_counts):
        ev = f"internal link x{link_counts[path]}"
        if reg.note(path, ev):
            continue
        m = re.fullmatch(r"/\?page_id=(\d+)", path)
        if m and int(m.group(1)) in page_path_by_id:
            target = page_path_by_id[int(m.group(1))]
            reg.add(
                path,
                "internal_link",
                "publish",
                "301",
                target,
                "nextjs",
                "legacy ?page_id link resolved to the page's canonical path; "
                "query-only source needs a `has` query matcher, so it is not in "
                "redirects.json",
                False,
                ev,
            )
            continue
        reg.add(
            path,
            "internal_link",
            "unknown",
            "client_decision",
            "",
            "none",
            "internally linked URL with no matching entity in the exports",
            True,
            ev,
        )

    # ------------------------------------------------------------------
    # Status codes, chain collapse and integrity checks
    # ------------------------------------------------------------------
    rows = list(reg.rows.values())
    by_path = {r["source_path"]: r for r in rows}

    for row in rows:
        if row["outcome"] == "301":
            dest = row["destination"]
            seen = {row["source_path"]}
            guard = 0
            while (
                dest in by_path
                and by_path[dest]["outcome"] == "301"
                and dest not in seen
                and guard < 10
            ):
                seen.add(dest)
                dest = by_path[dest]["destination"]
                guard += 1
                row["reason"] += "; chain collapsed"
            row["destination"] = dest
            row["status_code"] = "308" if row["owner"] == "nextjs" else "301"
        elif row["outcome"] == "same_url":
            row["status_code"] = "200"
        elif row["outcome"] == "410":
            row["status_code"] = "410"
        else:
            row["status_code"] = ""

    problems = []
    for row in rows:
        if row["outcome"] == "301":
            if row["destination"] == row["source_path"]:
                problems.append(f"self-redirect: {row['source_path']}")
            if row["destination"] in ("/", ""):
                problems.append(f"redirect to home/empty: {row['source_path']}")
            target = by_path.get(row["destination"])
            if target and target["outcome"] == "301":
                problems.append(
                    f"chain remains: {row['source_path']} -> {row['destination']}"
                )
            if target and target["outcome"] == "410":
                problems.append(
                    f"redirect to a 410 path: {row['source_path']} -> {row['destination']}"
                )
    if problems:
        for p in problems:
            print("INTEGRITY: " + p, file=sys.stderr)
        return 2

    rows.sort(key=lambda r: (r["source_type"], r["source_path"]))

    os.makedirs(OUT, exist_ok=True)
    fields = [
        "source_path",
        "source_type",
        "source_status",
        "outcome",
        "destination",
        "status_code",
        "owner",
        "reason",
        "needs_client_decision",
        "evidence",
    ]
    with open(os.path.join(OUT, "redirect-map.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fields})

    nextjs_redirects = [
        {"source": r["source_path"], "destination": r["destination"], "permanent": True}
        for r in rows
        if r["outcome"] == "301" and r["owner"] == "nextjs" and "?" not in r["source_path"]
    ]
    nextjs_redirects.sort(key=lambda r: r["source"])
    with open(os.path.join(OUT, "redirects.json"), "w", encoding="utf-8") as fh:
        json.dump(nextjs_redirects, fh, indent=2)
        fh.write("\n")

    gone = sorted(
        r["source_path"] for r in rows if r["outcome"] == "410" and "?" not in r["source_path"]
    )
    with open(os.path.join(OUT, "gone.json"), "w", encoding="utf-8") as fh:
        json.dump(gone, fh, indent=2)
        fh.write("\n")

    write_readme(rows, nextjs_redirects, gone, product_categories, product_tags,
                 demo_post_slugs, dirty_slug_notes)

    by_outcome = Counter(r["outcome"] for r in rows)
    by_type = Counter(r["source_type"] for r in rows)
    print(f"{len(rows)} source URLs")
    print("by outcome: " + ", ".join(f"{k}={v}" for k, v in sorted(by_outcome.items())))
    print("by type:    " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    print(f"redirects.json: {len(nextjs_redirects)} rules  gone.json: {len(gone)} paths")
    print(f"client decisions: {sum(1 for r in rows if r['needs_client_decision'] == 'true')}")
    return 0


def write_readme(rows, nextjs_redirects, gone, product_categories, product_tags,
                 demo_post_slugs, dirty_slug_notes) -> None:
    by_outcome = Counter(r["outcome"] for r in rows)
    by_type = Counter(r["source_type"] for r in rows)
    cross = Counter((r["source_type"], r["outcome"]) for r in rows)
    hard = [r for r in rows if r["outcome"] == "client_decision"]
    soft = [
        r for r in rows if r["needs_client_decision"] == "true" and r["outcome"] != "client_decision"
    ]

    lines = []
    a = lines.append
    a("# ProSporter legacy URL redirect map (CLNT-175)")
    a("")
    a("Generated by `scripts/redirects/build_redirect_map.py` from the git-ignored")
    a("`exports/` snapshot (5 September 2026). Everything in this folder is derived and")
    a("contains no customer, order or account data.")
    a("")
    a("| File | Purpose |")
    a("|---|---|")
    a("| `redirect-map.csv` | One row per normalized legacy path with exactly one outcome |")
    a("| `redirects.json` | The Next.js `redirects()` payload (nextjs-owned permanent redirects) |")
    a("| `gone.json` | Source paths that must answer 410 |")
    a("| `verification-report.md` | Output of `scripts/redirects/verify_redirects.py` |")
    a("")
    a("## Outcomes")
    a("")
    a(f"{len(rows)} de-duplicated source URLs.")
    a("")
    a("| Outcome | Count | Meaning |")
    a("|---|---:|---|")
    a(f"| `same_url` | {by_outcome.get('same_url', 0)} | Path preserved 1:1 in Next.js, must return 200 |")
    a(f"| `301` | {by_outcome.get('301', 0)} | Permanent redirect to a direct equivalent |")
    a(f"| `410` | {by_outcome.get('410', 0)} | Intentional retirement |")
    a(f"| `client_decision` | {by_outcome.get('client_decision', 0)} | Ambiguous, blocked on the client |")
    a("")
    a("> `outcome = 301` means *permanent redirect*. Next.js `permanent: true` emits **308**")
    a("> (it preserves the request method); the `status_code` column records 308 for")
    a("> nextjs-owned rows and 301 for Shopify-owned rows. Both are permanent for SEO.")
    a("")
    a("## Counts by source type")
    a("")
    a("| Source type | Total | same_url | 301 | 410 | client_decision |")
    a("|---|---:|---:|---:|---:|---:|")
    for stype in sorted(by_type):
        a(
            f"| `{stype}` | {by_type[stype]} | {cross.get((stype, 'same_url'), 0)} | "
            f"{cross.get((stype, '301'), 0)} | {cross.get((stype, '410'), 0)} | "
            f"{cross.get((stype, 'client_decision'), 0)} |"
        )
    a("")
    a("## Source inventory")
    a("")
    a("Built from, in registration order (first registration wins the disposition,")
    a("later discoveries only add evidence):")
    a("")
    a("1. Every product permalink, any status (`exports/products.json`).")
    a("2. Yoast Premium `_yoast_post_redirect_info` origins found on products.")
    a("3. Every page permalink, any status (`exports/pages.json`).")
    a("4. Every post permalink (`exports/posts.json`).")
    a("5. Every `product_cat` term URL - hierarchical path *and* bare-slug alias.")
    a("6. Every `product_tag` term URL.")
    a("7. Post category, post tag, author and feed archive URLs.")
    a("8. WooCommerce/WordPress system URLs (cart, checkout, my-account and endpoints,")
    a("   wishlist, shop, order-received, search).")
    a("9. Every Yoast sitemap URL not already covered.")
    a("10. Every navigation menu item URL.")
    a("11. Every internal link found in page/post HTML.")
    a("")
    a("### Normalization")
    a("")
    a("Legacy host stripped, path lowercased and percent-decoded, repeated slashes")
    a("collapsed, trailing slash removed (except the root), tracking parameters dropped.")
    a("Asset, `wp-json` and `wp-admin` URLs are excluded, as are on-page plugin action")
    a("links whose query is entirely made of action parameters (" +
      ", ".join(f"`{p}`" for p in sorted(PLUGIN_ACTION_PARAMS)) + ").")
    a("Those come from the Wishlist and Quick View plugins, both of which the audit")
    a("excluded from the migration; they are never indexed and never linked off-site.")
    a("")
    a("### Trailing slash")
    a("")
    a("Every legacy URL ends in `/`. Out of the box Next.js normalizes that away with")
    a("its own 308 **before** matching `redirects()` and before `src/proxy.ts` runs, so a")
    a("`source` written with a trailing slash is unreachable (verified against a running")
    a("server: it 404s without the slash and only ever 308s to the slash-free form).")
    a("Sources are therefore stored slash-free, which is the only form that matches, and")
    a("a legacy `/path/` request costs one platform normalization hop before the")
    a("redirect. That is not a chain in the map; `verification-report.md` counts it")
    a("separately.")
    a("")
    a("The fix is `skipTrailingSlashRedirect: true` in `next.config.ts`. That hands the")
    a("normalization to `src/proxy.ts`, which strips the slash itself, looks the path up")
    a("in `redirects.json` / `gone.json`, and answers with the final destination (or a")
    a("410) in **one** hop; anything that is not a legacy URL still gets the ordinary 308")
    a("to its slash-free form, so canonical URLs are unchanged. Measured both ways on the")
    a("same tree: without the flag 175 rows cost two hops and no 410 row answers 410")
    a("without a hop first; with it, 231 rows are single-hop, 48 answer 410 directly and")
    a("nothing is multi-hop. Rewriting the sources to match both forms cannot work,")
    a("because the normalization happens before matching. Stripping the slash at the")
    a("CDN/edge is the alternative if the flag is unwanted.")
    a("")
    a("### Query parameters")
    a("")
    a("Allowlist preserved for attribution: " + ", ".join(f"`{p}`" for p in TRACKING_ALLOWLIST) + ".")
    a("")
    a("Two things to know:")
    a("")
    a("- These parameters are removed from the **inventory key** so that")
    a("  `/product/x?utm_source=meta` and `/product/x` are one row.")
    a("- At request time Next.js `redirects()` forwards **all** query parameters to the")
    a("  destination. Dropping the non-allowlisted ones needs a proxy/edge rule and is")
    a("  deliberately out of scope here; the allowlist is what analytics should honour.")
    a("  Query-only legacy URLs (`/?s=`, `/?page_id=N`) cannot be matched by a path")
    a("  redirect at all and are excluded from `redirects.json`.")
    a("")
    a("## Category mapping (`/product-category/<slug>/` -> approved collection)")
    a("")
    a("Reuses the `TYPE_MAP` in `mock-data/build_taxonomy.py`, with Protective Gear and")
    a("Coaching folded into Accessories (commits `6293089`, `fcc9c6d`). Each legacy")
    a("category maps to exactly one collection. Both the hierarchical URL")
    a("(`/product-category/beach-volleyball/top-crop/`) and the bare alias")
    a("(`/product-category/top-crop/`) are in the map.")
    a("")
    a("| Legacy category | Products | Destination | Rationale |")
    a("|---|---:|---|---|")
    for cat in sorted(product_categories, key=lambda c: c["slug"]):
        slug = cat["slug"]
        if slug in CATEGORY_CLIENT_DECISION:
            a(f"| `{slug}` | {cat['count']} | *client decision* | {CATEGORY_CLIENT_DECISION[slug]} |")
        else:
            key, reason = CATEGORY_MAP[slug]
            a(f"| `{slug}` | {cat['count']} | `{_dest_for_axis(key)}` | {reason} |")
    a("")
    a("## Tag mapping (`/product-tag/<slug>/`)")
    a("")
    a("Rule-based, evaluated in this order. Precedence is club > surface > type,")
    a("so `provolley-polo` lands on the ProVolley collection rather than Tops.")
    a("")
    a("| Rule | Matches | Destination |")
    a("|---|---|---|")
    a("| Club token | " + ", ".join(f"`{t}`" for t, _ in TAG_CLUB_TOKENS) + " | the club collection |")
    a("| Surface token | " + ", ".join(f"`{t}`" for t, _ in TAG_SURFACE_TOKENS) + " | the surface collection |")
    a("| Type token | " + ", ".join(f"`{t}`" for t, _ in TAG_TYPE_TOKENS) + " | the type collection |")
    a("| Brand name | " + ", ".join(f"`{t}`" for t in sorted(TAG_BRANDS)) + " | *client decision* (no brand collection in the approved IA) |")
    a("| Internal flag | " + ", ".join(f"`{t}`" for t in sorted(TAG_INTERNAL)) + " | 410 |")
    a("| Empty and unindexed | count 0 and absent from the sitemap | 410 |")
    a("| Everything else | geographic/marketing SEO tags | `/shop` (Shop All), flagged for the client |")
    a("")
    a("`uniform` resolves to `/shop/jerseys` (a volleyball uniform is a playing kit) and")
    a("is flagged so the client can confirm.")
    a("")
    a("Resulting tag destinations:")
    a("")
    a("| Tag | Products | Outcome | Destination |")
    a("|---|---:|---|---|")
    tag_rows = {r["source_path"]: r for r in rows if r["source_type"] == "product_tag"}
    for tag in sorted(product_tags, key=lambda t: t["slug"]):
        r = tag_rows.get("/product-tag/" + tag["slug"])
        if r:
            a(f"| `{tag['slug']}` | {tag['count']} | `{r['outcome']}` | {'`' + r['destination'] + '`' if r['destination'] else '-'} |")
    a("")
    a("## Blog decision")
    a("")
    a("The storefront blog is a **single flat index at `/blog`**. Posts keep their handle")
    a("under the prefix (`/<slug>/` -> `/blog/<slug>`). There are no")
    a("`/blog/category/<slug>` or `/blog/tag/<slug>` routes, so every legacy")
    a("`/category/<slug>/` and `/tag/<slug>/` archive redirects to `/blog`, and author")
    a("archives and feeds are 410. This is applied consistently across all rows.")
    a("")
    if demo_post_slugs:
        a(f"{len(demo_post_slugs)} posts are WordPress theme demo content (beauty/skin care)")
        a("unrelated to the ProSporter brand. They are mapped to `/blog/<slug>` so nothing")
        a("breaks, but flagged: the recommendation is to retire them (410) and drop them")
        a("from the sitemap.")
        a("")
        for slug in sorted(demo_post_slugs):
            a(f"- `/{slug}`")
        a("")
    a("## Client decisions required")
    a("")
    a(f"{len(hard)} URLs have **no** destination until the client decides:")
    a("")
    a("| Source | Type | Reason |")
    a("|---|---|---|")
    for r in sorted(hard, key=lambda x: (x["source_type"], x["source_path"])):
        a(f"| `{r['source_path']}` | `{r['source_type']}` | {r['reason']} |")
    a("")
    a(f"A further {len(soft)} URLs have a working destination but are flagged for")
    a("confirmation (they are live in `redirects.json` today):")
    a("")
    a("| Source | Destination | Reason |")
    a("|---|---|---|")
    for r in sorted(soft, key=lambda x: (x["source_type"], x["source_path"])):
        a(f"| `{r['source_path']}` | `{r['destination'] or '-'}` | {r['reason']} |")
    a("")
    a("## Still to be merged in manually")
    a("")
    a("This map is complete for everything the authenticated exports expose. Three")
    a("sources are **not** in it and must be merged before cutover:")
    a("")
    a("1. **Yoast Premium redirect manager export.** Yoast's redirect table is not")
    a("   exposed over REST (audit README finding 12). Only the 10 redirects stored as")
    a("   product meta (`_yoast_post_redirect_info`) are captured here. Export the full")
    a("   table from SEO -> Redirects as CSV and re-run the builder with it merged, so")
    a("   any legacy chain collapses to the final destination in one hop.")
    a("2. **GA4 landing pages.** Pull the last 12-16 months of landing-page URLs and add")
    a("   any that are not already rows here; they are the URLs with real traffic and")
    a("   should be prioritised for a genuine destination over a generic listing.")
    a("3. **Search Console.** Export Performance -> Pages and the Indexing report; add")
    a("   indexed URLs missing from the sitemaps, and use impressions to re-rank the")
    a("   client decisions above.")
    a("")
    a("Also worth a crawl of the live site before cutover to catch URLs that exist only")
    a("in theme templates or widgets rather than in page/post HTML.")
    a("")
    a("## Rerun and verify")
    a("")
    a("```bash")
    a("# 1. Rebuild the map from exports/ (deterministic)")
    a("python3 scripts/redirects/build_redirect_map.py")
    a("")
    a("# 2. Build and start the app (next.config.ts reads docs/redirects/redirects.json)")
    a("SHOPIFY_OPTIONAL=1 npm run build")
    a("SHOPIFY_OPTIONAL=1 NODE_ENV=production PORT=3114 npx next start &")
    a("")
    a("# 3. Verify every row against the running server")
    a("python3 scripts/redirects/verify_redirects.py --base-url http://localhost:3114")
    a("")
    a("# 4. Stop the server")
    a("kill %1")
    a("```")
    a("")
    a("The verifier writes `verification-report.md` and exits non-zero on a real")
    a("failure. Destinations that 404 only because the page is not built in the")
    a("prototype yet are reported separately and do not fail the run.")
    a("")
    a("## Implementation")
    a("")
    a(f"- `next.config.ts` imports `redirects.json` ({len(nextjs_redirects)} rules) and returns it from `redirects()`.")
    a(f"- `src/proxy.ts` imports `gone.json` ({len(gone)} paths) and answers each one with a")
    a("  real 410, a small retired-page body, `Cache-Control: public, max-age=3600,")
    a("  must-revalidate` (never `immutable`, so wiring a real page later is not stuck")
    a("  behind a CDN cache) and `X-Robots-Tag: noindex`. The same file also imports")
    a("  `redirects.json`, which is what lets it resolve a trailing-slash legacy URL to")
    a("  its final destination in one hop once `skipTrailingSlashRedirect: true` is set.")
    a("  The one 410 row not in `gone.json` is `/?s=`, a query-only URL no path rule can")
    a("  match.")
    a("- `src/app/blog/page.tsx` and `src/app/blog/[slug]/page.tsx` are **placeholders**")
    a("  so that the 31 redirects pointing at `/blog` and `/blog/<slug>` land on a 200")
    a("  rather than a 404. They render \"coming soon\", carry `robots: noindex`, and the")
    a("  post route serves only the slugs named in `redirects.json` (anything else 404s).")
    a("  Delete them when the real blog lands.")
    a("- Rows owned by `shopify` are listed for completeness. If the legacy paths keep")
    a("  resolving to the Next.js app after cutover, Next serves the 410; if any of them")
    a("  is pointed at Shopify instead, Shopify owns the response.")
    a("")

    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
