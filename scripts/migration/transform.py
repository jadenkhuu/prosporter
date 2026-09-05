#!/usr/bin/env python3
"""Stage 2 - transform.

Turns the WooCommerce snapshot into Shopify-shaped records, one JSONL file per
record type, applying the normalization rules in execution-plan section 7 and
the approved storefront IA.

Anything the rules cannot decide safely is routed to the exception register
rather than guessed at. Records that carry an unresolved blocking exception are
marked ``held: true`` and are skipped by the load stage, so count differences in
reconciliation are always explained by a named exception.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

import normalize as N
from common import (
    checksum,
    clean_text,
    kilograms_to_grams,
    meta_value,
    slugify,
    to_decimal_string,
)
from errors import OWNER_AGENCY, OWNER_CLIENT

STAGE = "transform"

# Choice lists for the admin dropdowns. Every one is DERIVED from the same IA
# mapping the transform uses to populate the metafields, so a definition can
# never offer a value the pipeline does not emit, and the pipeline can never
# emit a value the definition rejects (enforced by _choice_checked below and by
# test_pipeline.MetafieldChoices).
SURFACE_CHOICES = sorted(handle for handle, _title in N.SURFACE_COLLECTIONS)
CLUB_CHOICES = sorted(handle for handle, _title in N.CLUB_COLLECTIONS)
# assign_gender() emits either the normalized Men/Women values or the "Unisex"
# default, so the choice list is exactly the range of normalize_gender().
GENDER_CHOICES = sorted(set(N.GENDER_SYNONYMS.values()))

CHOICES_BY_KEY = {
    "surface": SURFACE_CHOICES,
    "club": CLUB_CHOICES,
    "gender": GENDER_CHOICES,
}

# namespace, key, type, admin name, owner type, merchant-facing description,
# pinned on the product form?, choice list (None = no choices validation).
#
# The prosporter.* fields are pinned so a merchant adding a product by hand sees
# them on the product form instead of behind "Show all", and the three IA fields
# carry a `choices` validation so the admin renders a dropdown rather than a
# free-text box. migration.woo_id stays unpinned: it is machine-written trace
# data, not something a merchant should touch.
METAFIELD_DEFINITIONS = [
    ("prosporter", "surface", "single_line_text_field", "Playing surface", "PRODUCT",
     "Where the product is played: indoor or beach. Drives the Indoor and Beach collections and the storefront filter.",
     True, SURFACE_CHOICES),
    ("prosporter", "club", "list.single_line_text_field", "Club or team", "PRODUCT",
     "Clubs this product belongs to. Pick one or more; each value matches a club collection on the storefront.",
     True, CLUB_CHOICES),
    ("prosporter", "gender", "list.single_line_text_field", "Gender", "PRODUCT",
     "Who the product is cut for. Use Unisex unless the fit is specifically men's or women's.",
     True, GENDER_CHOICES),
    ("prosporter", "size_guide", "single_line_text_field", "Size guide", "PRODUCT",
     "Handle of the size-guide page to show on this product, e.g. size-guide-apparel. Leave blank for no guide.",
     True, None),
    ("prosporter", "personalisation", "json", "Personalisation fields", "PRODUCT",
     "JSON describing the name/number personalisation offered on this product. Leave blank unless the team-kit model has been approved.",
     True, None),
    ("migration", "woo_id", "single_line_text_field", "Source WooCommerce id", "PRODUCT",
     "Set by the WooCommerce migration to trace this product back to its source record. Do not edit or delete.",
     False, None),
]

# WordPress pages that are storefront routes, not content to migrate.
FUNCTIONAL_PAGE = re.compile(r"^(cart|checkout|my-account|wishlist|shop|order-tracking)(-\d+)?$")

BLOG_HANDLE = "news"


def transform(data: dict, exc) -> dict:
    snapshot = data["_meta"]["source_snapshot"]
    ctx = _Context(data, exc, snapshot)
    records = {
        "metafield_definitions": _metafield_definitions(snapshot),
        "collections": [],
        "products": [],
        "variants": [],
        "media": [],
        "metafields": [],
        "pages": [],
        "articles": [],
        "customers": [],
        "discounts": [],
        "id_map": [],
    }
    _products(ctx, records)
    _collections(ctx, records)
    _pages(ctx, records)
    _articles(ctx, records)
    _customers(ctx, records)
    _discounts(ctx, records)
    _id_map(records, snapshot)
    return records


class _Context:
    def __init__(self, data, exc, snapshot):
        self.data = data
        self.exc = exc
        self.snapshot = snapshot
        self.variations_by_parent = defaultdict(list)
        for variation in data["variations"]:
            self.variations_by_parent[variation.get("parent_id")].append(variation)
        for rows in self.variations_by_parent.values():
            rows.sort(key=lambda v: (v.get("menu_order", 0), v.get("id", 0)))
        self.media_by_id = {m.get("id"): m for m in data["media"]}
        self.reachable = {
            row.get("url"): row.get("status") for row in data.get("media_head") or []
        }
        self.collection_members = defaultdict(list)
        self.handles = {}

    def source(self, woo_id, woo_type):
        return {"woo_id": woo_id, "woo_type": woo_type, "source_snapshot": self.snapshot}

    def unique_handle(self, raw_slug, fallback, woo_id, record_type):
        handle = slugify(raw_slug or fallback)
        taken = self.handles.get(record_type, {})
        if handle in taken and taken[handle] != woo_id:
            self.exc.add(
                record_type=record_type, record_id=woo_id, record_ref=handle,
                stage=STAGE, severity="medium", code="duplicate_handle",
                message=f"handle '{handle}' already used by source id {taken[handle]}; "
                        f"suffixed with the source id",
                owner=OWNER_AGENCY, retry_status="resolved",
            )
            handle = f"{handle}-{woo_id}"
        self.handles.setdefault(record_type, {})[handle] = woo_id
        return handle


def _metafield_definitions(snapshot):
    rows = []
    for ns, key, mtype, name, owner, description, pin, choices in METAFIELD_DEFINITIONS:
        # Admin API 2026-07: the `choices` validation takes a JSON array string
        # and is supported by single_line_text_field and list.single_line_text_field.
        validations = (
            [{"name": "choices", "value": json.dumps(choices, separators=(",", ":"))}]
            if choices else []
        )
        rows.append({
            "namespace": ns,
            "key": key,
            "type": mtype,
            "name": name,
            "owner_type": owner,
            "description": description,
            "pin": pin,
            "validations": validations,
            "source": {"woo_id": None, "woo_type": "definition", "source_snapshot": snapshot},
        })
    return rows


# --------------------------------------------------------------------------
# Products, options, variants, media, metafields
# --------------------------------------------------------------------------
def _products(ctx, records):
    exc = ctx.exc
    sku_owners = defaultdict(list)

    for product in sorted(ctx.data["products"], key=lambda p: p["id"]):
        woo_id = product["id"]
        title = clean_text(product.get("name"))
        handle = ctx.unique_handle(product.get("slug"), title, woo_id, "product")
        categories = [clean_text(c.get("name")) for c in product.get("categories") or []]
        variations = ctx.variations_by_parent.get(woo_id, [])

        held_reasons = []

        if product.get("type") == "easy_product_bundle":
            exc.add(
                record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
                severity="high", code="bundle_product",
                message="Easy Product Bundles product has no Shopify equivalent; "
                        "rebuild manually or with a bundles app",
                owner=OWNER_CLIENT, retry_status="needs-decision",
            )
            held_reasons.append("bundle_product")

        options, option_issues = _build_options(ctx, product, variations, handle)
        held_reasons.extend(option_issues)

        product_type, how = N.assign_product_type(categories, title)
        if how != "category":
            exc.add(
                record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
                severity="medium", code=f"product_type_{how.replace('-', '_')}",
                message=f"no mapped product-type category; assigned '{product_type}' by {how}",
                owner=OWNER_CLIENT, retry_status="needs-decision",
                detail={"categories": categories, "assigned": product_type},
            )

        surface = N.assign_surface(categories, title)
        clubs = N.assign_clubs(categories, title)
        gender_values = [
            option
            for attribute in product.get("attributes") or []
            if clean_text(attribute.get("name")).lower() == "gender"
            for option in attribute.get("options") or []
        ]
        gender = N.assign_gender(categories, gender_values)

        tags = sorted(
            {N.legacy_tag(name) for name in categories}
            | {N.legacy_tag(clean_text(t.get("name"))) for t in product.get("tags") or []}
            | {f"type:{product_type}"}
            | ({f"surface:{surface}"} if surface else set())
            | {f"club:{c}" for c in clubs}
            | {f"gender:{g.lower()}" for g in gender}
        )

        yoast = product.get("yoast_head_json") or {}
        images = _product_images(ctx, product, handle, woo_id)
        if not images and product.get("status") == "publish":
            exc.add(
                record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
                severity="medium", code="product_without_image",
                message="published product has no image; storefront will show a placeholder",
                owner=OWNER_CLIENT, retry_status="needs-decision",
            )

        variants, variant_holds = _build_variants(
            ctx, product, variations, options, handle, sku_owners
        )
        if not variants:
            exc.add(
                record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
                severity="critical", code="product_without_sellable_variant",
                message="every variant was held (missing price or option value); "
                        "product cannot be loaded",
                owner=OWNER_CLIENT, retry_status="needs-decision",
                detail={"held_variants": variant_holds},
            )
            held_reasons.append("product_without_sellable_variant")

        held = bool(held_reasons)
        record = {
            "handle": handle,
            "title": title,
            "body_html": product.get("description") or "",
            "vendor": _vendor(product),
            "product_type": dict(N.TYPE_COLLECTIONS).get(product_type, product_type),
            "status": "DRAFT",  # dry runs never publish
            "tags": tags,
            "options": [
                {k: v for k, v in option.items() if k != "value_map"}
                for option in options
            ],
            "seo": {
                "title": clean_text(yoast.get("title")) or title,
                "description": clean_text(yoast.get("description") or yoast.get("og_description")),
            },
            "source_status": product.get("status"),
            "source_permalink": product.get("permalink"),
            "collections": _collection_handles(product_type, surface, clubs),
            "held": held,
            "held_reasons": sorted(set(held_reasons)),
            "source": ctx.source(woo_id, "product"),
        }
        records["products"].append(record)

        if not record["seo"]["description"]:
            exc.add(
                record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
                severity="low", code="seo_description_missing",
                message="no Yoast meta description; Shopify SEO description left empty",
                owner=OWNER_CLIENT, retry_status="needs-decision",
            )

        if not held:
            for collection_handle in record["collections"]:
                ctx.collection_members[collection_handle].append(handle)

        for variant in variants:
            variant["held"] = variant["held"] or held
            records["variants"].append(variant)
        for image in images:
            image["held"] = held
            records["media"].append(image)
        records["metafields"].extend(
            _product_metafields(ctx, handle, woo_id, surface, clubs, gender, held)
        )

    _flag_duplicate_skus(ctx, sku_owners)


def _vendor(product):
    brands = product.get("brands") or []
    if brands:
        return clean_text(brands[0].get("name"))
    return "ProSporter"


def _collection_handles(product_type, surface, clubs):
    handles = [product_type]
    if surface:
        handles.append(surface)
    handles.extend(clubs)
    return handles


def _build_options(ctx, product, variations, handle):
    """Return (options, held_reasons) for one product.

    Rules applied, in order:
      * Color and Colour collapse into one Colour option.
      * Attributes flagged "decision" (Condition, Number) are escalated.
      * Attributes flagged "label" (Hats) become legacy tags, never options.
      * An option whose variations only ever use one value is dropped.
      * Value synonyms are normalised; if normalising would collide two source
        values inside one product the raw values are kept and escalated.
      * More than three surviving options is a hard Shopify limit -> escalate.
    """
    exc, woo_id = ctx.exc, product["id"]
    held = []
    buckets = {}  # canonical name -> list of raw values in source order

    for attribute in product.get("attributes") or []:
        if not attribute.get("variation"):
            continue
        raw_name = clean_text(attribute.get("name"))
        policy, canonical = N.ATTRIBUTE_POLICY.get(raw_name.lower(), ("decision", raw_name))
        raw_values = [clean_text(v) for v in attribute.get("options") or [] if clean_text(v)]

        if policy == "label":
            exc.add(
                record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
                severity="low", code="attribute_demoted_to_tag",
                message=f"attribute '{raw_name}' is a label, not a variant axis; "
                        f"kept as a legacy tag only",
                owner=OWNER_AGENCY, retry_status="resolved",
                detail={"attribute": raw_name, "values": raw_values},
            )
            continue
        if policy == "decision":
            exc.add(
                record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
                severity="critical", code="attribute_needs_decision",
                message=f"attribute '{raw_name}' is not clearly variant-defining "
                        f"(condition vs personalisation); needs a client decision before load",
                owner=OWNER_CLIENT, retry_status="needs-decision",
                detail={"attribute": raw_name, "distinct_values": len(set(raw_values))},
            )
            held.append(f"attribute_needs_decision:{raw_name}")
            continue

        if canonical == "Size":
            resolved = N.size_option_name(raw_values)
            if resolved is None:
                exc.add(
                    record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
                    severity="high", code="mixed_size_systems",
                    message="one Size attribute mixes apparel sizes and numeric sock sizes; "
                            "split at source before load",
                    owner=OWNER_CLIENT, retry_status="needs-decision",
                    detail={"values": raw_values},
                )
                held.append("mixed_size_systems")
                continue
            canonical = resolved

        buckets.setdefault(canonical, [])
        buckets[canonical].extend(raw_values)

    options = []
    for canonical, raw_values in buckets.items():
        used = _values_used(variations, canonical, raw_values)
        if len(set(used)) <= 1:
            exc.add(
                record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
                severity="low", code="single_value_option_dropped",
                message=f"option '{canonical}' has one value across all variations; "
                        f"dropped so the product is single-variant",
                owner=OWNER_AGENCY, retry_status="resolved",
                detail={"option": canonical, "values": sorted(set(used))},
            )
            continue

        mapping = {}
        collisions = defaultdict(set)
        for value in used:
            normalized = N.normalize_option_value(canonical, value)
            mapping[value] = normalized
            collisions[normalized].add(value)
        collided = {k: sorted(v) for k, v in collisions.items() if len(v) > 1}
        if collided:
            exc.add(
                record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
                severity="high", code="option_value_collision",
                message=f"normalising '{canonical}' would merge distinct variants; "
                        f"raw source values kept",
                owner=OWNER_CLIENT, retry_status="needs-decision",
                detail={"option": canonical, "collisions": collided},
            )
            mapping = {value: value for value in used}

        options.append({
            "name": canonical,
            "values": N.sort_option_values(canonical, [mapping[v] for v in used]),
            "value_map": mapping,
        })

    if len(options) > N.SHOPIFY_MAX_OPTIONS:
        exc.add(
            record_type="product", record_id=woo_id, record_ref=handle, stage=STAGE,
            severity="critical", code="option_limit_exceeded",
            message=f"{len(options)} variant options exceeds Shopify's limit of "
                    f"{N.SHOPIFY_MAX_OPTIONS}; needs a client decision on which axes to keep",
            owner=OWNER_CLIENT, retry_status="needs-decision",
            detail={"options": [o["name"] for o in options]},
        )
        held.append("option_limit_exceeded")

    for position, option in enumerate(options, start=1):
        option["position"] = position
    return options, held


def _values_used(variations, canonical, declared_values):
    """Option values actually referenced by the variations (falls back to declared)."""
    used = []
    for variation in variations:
        for attribute in variation.get("attributes") or []:
            name = clean_text(attribute.get("name"))
            _, mapped = N.ATTRIBUTE_POLICY.get(name.lower(), ("decision", name))
            if mapped == canonical or (canonical == "Sock Size" and mapped == "Size"):
                value = clean_text(attribute.get("option"))
                if value:
                    used.append(value)
    return used or declared_values


def _build_variants(ctx, product, variations, options, handle, sku_owners):
    exc, woo_id = ctx.exc, product["id"]
    option_names = [o["name"] for o in options]
    value_maps = {o["name"]: o["value_map"] for o in options}
    held_ids = []
    out = []
    seen_combinations = {}  # option-combination -> first variation id

    if not variations:
        # Simple product: a single default variant.
        variations = [_synthetic_variation(product)]

    for position, variation in enumerate(variations, start=1):
        variation_id = variation["id"]
        raw_sku = clean_text(variation.get("sku"))
        generated = not raw_sku
        sku = raw_sku or N.generate_sku(woo_id, variation_id)
        if generated:
            exc.add(
                record_type="variant", record_id=variation_id, record_ref=sku, stage=STAGE,
                severity="low", code="sku_generated",
                message="variation had no SKU; generated deterministically as PS-<product>-<variation>",
                owner=OWNER_CLIENT, retry_status="needs-decision",
                detail={"product_handle": handle},
            )
        sku_owners[sku].append({"variation_id": variation_id, "product_handle": handle})

        regular = to_decimal_string(variation.get("regular_price"))
        sale = to_decimal_string(variation.get("sale_price"))
        current = to_decimal_string(variation.get("price"))
        parent_regular = to_decimal_string(product.get("regular_price"))
        parent_price = to_decimal_string(product.get("price"))

        price = sale or regular or current or parent_regular or parent_price
        compare_at = regular if (sale and regular and sale != regular) else None
        held_variant = False
        if price is None:
            exc.add(
                record_type="variant", record_id=variation_id, record_ref=sku, stage=STAGE,
                severity="high", code="variant_missing_price",
                message="no regular, sale or parent price; variant held out of the load",
                owner=OWNER_CLIENT, retry_status="needs-decision",
                detail={"product_handle": handle},
            )
            held_variant = True
            held_ids.append(variation_id)

        option_values, missing = _variant_option_values(variation, option_names, value_maps)
        if missing:
            exc.add(
                record_type="variant", record_id=variation_id, record_ref=sku, stage=STAGE,
                severity="high", code="variant_missing_option_value",
                message=f"WooCommerce 'Any' variation: no value for option(s) "
                        f"{', '.join(missing)}. Shopify has no equivalent, so the variant "
                        f"is held; expand it into explicit variants at source or approve "
                        f"an expansion rule",
                owner=OWNER_CLIENT, retry_status="needs-decision",
                detail={"product_handle": handle},
            )
            held_variant = True
            if variation_id not in held_ids:
                held_ids.append(variation_id)

        # Shopify allows one variant per option combination. A second Woo
        # variation with the same combination would silently overwrite the first
        # on load, so hold it and let the client pick which row survives.
        combination = tuple((o["name"], o["value"]) for o in option_values)
        if not missing and combination in seen_combinations:
            exc.add(
                record_type="variant", record_id=variation_id, record_ref=sku, stage=STAGE,
                severity="high", code="duplicate_option_combination",
                message=f"same option combination as variation {seen_combinations[combination]} "
                        f"({', '.join(v for _, v in combination) or 'Default Title'}); Shopify "
                        f"allows one variant per combination, so this row is held. Decide which "
                        f"variation (SKU, stock) is authoritative",
                owner=OWNER_CLIENT, retry_status="needs-decision",
                detail={"product_handle": handle, "first_variation_id": seen_combinations[combination]},
            )
            held_variant = True
            if variation_id not in held_ids:
                held_ids.append(variation_id)
        elif not missing:
            seen_combinations[combination] = variation_id

        manage_stock = bool(variation.get("manage_stock")) or bool(product.get("manage_stock"))
        quantity = variation.get("stock_quantity")
        if quantity is None and not manage_stock:
            quantity = 0 if variation.get("stock_status") == "outofstock" else None
        if isinstance(quantity, int) and quantity < 0:
            exc.add(
                record_type="variant", record_id=variation_id, record_ref=sku, stage=STAGE,
                severity="medium", code="negative_inventory",
                message=f"source stock quantity is {quantity}; staged as 0",
                owner=OWNER_CLIENT, retry_status="needs-decision",
            )
            quantity = 0

        weight = kilograms_to_grams(variation.get("weight")) or kilograms_to_grams(product.get("weight"))
        if weight is None:
            exc.add(
                record_type="variant", record_id=variation_id, record_ref=sku, stage=STAGE,
                severity="low", code="variant_missing_weight",
                message="no weight on the variation or its parent; shipping rates that "
                        "depend on weight cannot be calculated",
                owner=OWNER_CLIENT, retry_status="needs-decision",
            )

        barcode = clean_text(
            meta_value(variation.get("meta_data"), "usbs_barcode_field")
            or variation.get("global_unique_id")
        ) or None

        tax_status = variation.get("tax_status") or product.get("tax_status") or "taxable"
        out.append({
            "product_handle": handle,
            "sku": sku,
            "sku_generated": generated,
            "barcode": barcode,
            "price": price,
            "compare_at_price": compare_at,
            "currency": "AUD",
            "weight_grams": weight,
            "weight_unit": "GRAMS",
            "inventory_quantity": quantity,
            "inventory_management": "SHOPIFY" if manage_stock else None,
            "inventory_policy": "CONTINUE" if variation.get("backorders_allowed") else "DENY",
            "requires_shipping": not bool(variation.get("virtual") or product.get("virtual")),
            "taxable": tax_status == "taxable",
            "option_values": option_values,
            "position": position,
            "held": held_variant,
            "source": ctx.source(variation_id, "product_variation"),
        })
    return out, held_ids


def _synthetic_variation(product):
    """Simple products have no Woo variation row; model the default variant."""
    return {
        "id": product["id"],
        "sku": product.get("sku"),
        "regular_price": product.get("regular_price"),
        "sale_price": product.get("sale_price"),
        "price": product.get("price"),
        "manage_stock": product.get("manage_stock"),
        "stock_quantity": product.get("stock_quantity"),
        "stock_status": product.get("stock_status"),
        "backorders_allowed": product.get("backorders_allowed"),
        "weight": product.get("weight"),
        "virtual": product.get("virtual"),
        "tax_status": product.get("tax_status"),
        "attributes": [],
        "meta_data": product.get("meta_data"),
        "global_unique_id": product.get("global_unique_id"),
    }


def _variant_option_values(variation, option_names, value_maps):
    values, missing = [], []
    supplied = {}
    for attribute in variation.get("attributes") or []:
        name = clean_text(attribute.get("name"))
        _, canonical = N.ATTRIBUTE_POLICY.get(name.lower(), ("decision", name))
        supplied[canonical] = clean_text(attribute.get("option"))
    for name in option_names:
        raw = supplied.get(name)
        if raw is None and name == "Sock Size":
            raw = supplied.get("Size")
        if not raw:
            missing.append(name)
            continue
        values.append({"name": name, "value": value_maps[name].get(raw, raw)})
    if not option_names:
        values = [{"name": "Title", "value": "Default Title"}]
    return values, missing


COLOUR_ATTRIBUTE_NAMES = {"colour", "color", "pa_colour", "pa_color"}


def _variation_colour(variation):
    for attribute in variation.get("attributes") or []:
        if clean_text(attribute.get("name")).lower() in COLOUR_ATTRIBUTE_NAMES:
            return clean_text(attribute.get("option")) or None
    return None


def _variant_images(ctx, woo_id):
    """src -> [variant SKUs] that should show that image.

    WooCommerce lets a merchant put a photo on a single variation, so typically
    only one size of each colour carries the colour's image and the other
    sizes fall back to the product's first photo (often a different colour).
    Propagate each colour's image to every variation of that colour that has
    no image of its own; variations with their own image keep it.
    """
    variations = ctx.variations_by_parent.get(woo_id, [])
    own_image, colour_of, sku_of = {}, {}, {}
    for variation in variations:
        sku_of[variation["id"]] = clean_text(variation.get("sku")) or N.generate_sku(woo_id, variation["id"])
        colour_of[variation["id"]] = _variation_colour(variation)
        src = (variation.get("image") or {}).get("src")
        if src:
            own_image[variation["id"]] = src
    src_for_colour = {}
    for variation in variations:
        colour = colour_of[variation["id"]]
        if colour and variation["id"] in own_image:
            src_for_colour.setdefault(colour, own_image[variation["id"]])
    by_src = {}
    for variation in variations:
        vid = variation["id"]
        src = own_image.get(vid) or src_for_colour.get(colour_of[vid] or "")
        if src:
            by_src.setdefault(src, []).append(sku_of[vid])
    return by_src


def _product_images(ctx, product, handle, woo_id):
    images, seen = [], set()
    variant_skus_by_src = _variant_images(ctx, woo_id)
    variant_image_by_src = {src: skus[0] for src, skus in variant_skus_by_src.items()}

    sources = list(product.get("images") or [])
    for variation in ctx.variations_by_parent.get(woo_id, []):
        image = variation.get("image") or {}
        if image.get("src"):
            sources.append(image)

    position = 0
    for image in sources:
        src = image.get("src")
        if not src or src in seen:
            continue
        seen.add(src)
        position += 1
        media_row = ctx.media_by_id.get(image.get("id")) or {}
        alt = clean_text(image.get("alt")) or clean_text(media_row.get("alt_text"))
        status = ctx.reachable.get(src)
        if status is not None and status != 200:
            ctx.exc.add(
                record_type="media", record_id=image.get("id"), record_ref=handle, stage=STAGE,
                severity="high", code="media_unreachable",
                message=f"source image returned HTTP {status}",
                owner=OWNER_AGENCY, retry_status="auto-retryable",
            )
        if not alt:
            ctx.exc.add(
                record_type="media", record_id=image.get("id"), record_ref=handle, stage=STAGE,
                severity="low", code="media_missing_alt",
                message="image has no alt text",
                owner=OWNER_CLIENT, retry_status="needs-decision",
            )
        images.append({
            "product_handle": handle,
            "original_url": src,
            "alt": alt,
            "position": position,
            "variant_sku": variant_image_by_src.get(src),
            "variant_skus": variant_skus_by_src.get(src, []),
            # The real checksum needs the bytes; the dry run hashes the URL so
            # reruns are stable and the field is shaped for the real loader.
            "checksum": {
                "algorithm": "sha256",
                "value": checksum(src),
                "computed_over": "source_url",
                "status": "placeholder",
            },
            "reachable": status == 200 if status is not None else None,
            "http_status": status,
            "woo_media_id": image.get("id"),
            "source": ctx.source(image.get("id"), "product_image"),
        })
    return images


def _product_metafields(ctx, handle, woo_id, surface, clubs, gender, held):
    rows = [{
        "owner_type": "PRODUCT",
        "owner_handle": handle,
        "namespace": "migration",
        "key": "woo_id",
        "type": "single_line_text_field",
        "value": str(woo_id),
        "held": held,
        "source": ctx.source(woo_id, "product"),
    }]
    # Every value below must be one of the definition's `choices`, or Shopify
    # rejects the metafield. _choice_checked drops the offender and raises
    # metafield_value_outside_choices rather than loading an invalid value.
    surface = _choice_checked(ctx, handle, woo_id, "surface", surface)
    clubs = _choice_checked(ctx, handle, woo_id, "club", clubs)
    gender = _choice_checked(ctx, handle, woo_id, "gender", gender)
    if surface:
        rows.append(_mf(ctx, handle, woo_id, "surface", "single_line_text_field", surface, held))
    if clubs:
        rows.append(_mf(ctx, handle, woo_id, "club", "list.single_line_text_field", clubs, held))
    if gender:
        rows.append(_mf(ctx, handle, woo_id, "gender", "list.single_line_text_field", gender, held))
    # prosporter.size_guide and prosporter.personalisation are defined but not
    # populated: no size-guide field exists in Woo, and PPOM personalisation
    # evidence lives on order lines (workstream 5), not on products.
    return rows


def _choice_checked(ctx, handle, woo_id, key, value):
    """Drop any value the ``prosporter.<key>`` definition would reject.

    The choice lists are derived from the same IA mapping that produces these
    values, so a hit here means the mapping and the definition have drifted
    apart. That is a bug worth a named exception, never a silently invalid
    metafield: Shopify would reject the value at load time.
    """
    if not value:
        return value
    choices = CHOICES_BY_KEY[key]
    values = value if isinstance(value, list) else [value]
    bad = [v for v in values if v not in choices]
    if not bad:
        return value
    ctx.exc.add(
        record_type="metafield", record_id=woo_id, record_ref=f"{handle}:prosporter.{key}",
        stage=STAGE, severity="high", code="metafield_value_outside_choices",
        message=f"prosporter.{key} value(s) {', '.join(sorted(bad))} are not in the "
                f"definition's choice list; dropped rather than loaded as invalid",
        owner=OWNER_AGENCY, retry_status="needs-decision",
        detail={"key": f"prosporter.{key}", "rejected": sorted(bad), "choices": choices},
    )
    kept = [v for v in values if v in choices]
    if isinstance(value, list):
        return kept
    return kept[0] if kept else None


def _mf(ctx, handle, woo_id, key, mtype, value, held):
    return {
        "owner_type": "PRODUCT",
        "owner_handle": handle,
        "namespace": "prosporter",
        "key": key,
        "type": mtype,
        "value": value,
        "held": held,
        "source": ctx.source(woo_id, "product"),
    }


def _flag_duplicate_skus(ctx, sku_owners):
    for sku, owners in sorted(sku_owners.items()):
        if len(owners) > 1:
            ctx.exc.add(
                record_type="variant", record_id=sku, record_ref=sku, stage=STAGE,
                severity="high", code="duplicate_sku",
                message=f"SKU used by {len(owners)} variants; left unchanged, "
                        f"client must supply unique SKUs",
                owner=OWNER_CLIENT, retry_status="needs-decision",
                detail={"variation_ids": [o["variation_id"] for o in owners]},
            )


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------
def _collections(ctx, records):
    definitions = (
        [(h, t, "product-type") for h, t in N.TYPE_COLLECTIONS]
        + [(h, t, "surface") for h, t in N.SURFACE_COLLECTIONS]
        + [(h, t, "club") for h, t in N.CLUB_COLLECTIONS]
    )
    for handle, title, axis in definitions:
        members = sorted(set(ctx.collection_members.get(handle, [])))
        records["collections"].append({
            "handle": handle,
            "title": title,
            "axis": axis,
            "rule_set": "MANUAL",
            "body_html": "",
            "seo": {"title": title, "description": ""},
            "product_handles": members,
            "product_count": len(members),
            "held": False,
            "source": {"woo_id": None, "woo_type": "collection", "source_snapshot": ctx.snapshot},
        })
        if not members:
            ctx.exc.add(
                record_type="collection", record_id=handle, record_ref=handle, stage=STAGE,
                severity="medium", code="empty_collection",
                message="collection has no members after the IA mapping",
                owner=OWNER_AGENCY, retry_status="needs-decision",
            )


# --------------------------------------------------------------------------
# Pages and articles
# --------------------------------------------------------------------------
def _pages(ctx, records):
    for page in sorted(ctx.data["pages"], key=lambda p: p["id"]):
        woo_id = page["id"]
        slug = clean_text(page.get("slug"))
        title = clean_text(page.get("title"))
        handle = ctx.unique_handle(slug, title, woo_id, "page")
        held_reasons = []
        if FUNCTIONAL_PAGE.match(slug):
            ctx.exc.add(
                record_type="page", record_id=woo_id, record_ref=slug, stage=STAGE,
                severity="medium", code="page_is_storefront_route",
                message="WooCommerce functional page; the Next.js storefront owns this route, "
                        "so it is not loaded as a Shopify page",
                owner=OWNER_AGENCY, retry_status="needs-decision",
            )
            held_reasons.append("page_is_storefront_route")
        if re.search(r"-\d+$", slug):
            ctx.exc.add(
                record_type="page", record_id=woo_id, record_ref=slug, stage=STAGE,
                severity="low", code="page_duplicate_suffix",
                message="slug looks like a WordPress duplicate; confirm the canonical page",
                owner=OWNER_CLIENT, retry_status="needs-decision",
            )
        yoast = page.get("yoast_head_json") or {}
        records["pages"].append({
            "handle": handle,
            "title": title,
            "body_html": clean_text(page.get("content")),
            "published": page.get("status") == "publish",
            "source_status": page.get("status"),
            "published_at": page.get("date_gmt"),
            "seo": {
                "title": clean_text(yoast.get("title")) or title,
                "description": clean_text(yoast.get("description") or yoast.get("og_description")),
            },
            "source_permalink": page.get("link"),
            "held": bool(held_reasons),
            "held_reasons": held_reasons,
            "source": ctx.source(woo_id, "page"),
        })


def _articles(ctx, records):
    tag_names = {t["id"]: clean_text(t.get("name")) for t in ctx.data.get("post_tags") or []}
    category_names = {
        c["id"]: clean_text(c.get("name")) for c in ctx.data.get("post_categories") or []
    }
    for post in sorted(ctx.data["posts"], key=lambda p: p["id"]):
        woo_id = post["id"]
        title = clean_text(post.get("title"))
        handle = ctx.unique_handle(post.get("slug"), title, woo_id, "article")
        yoast = post.get("yoast_head_json") or {}
        author = clean_text(yoast.get("author")) or f"wp-user-{post.get('author')}"
        tags = sorted(
            {tag_names.get(t, f"wp-tag-{t}") for t in post.get("tags") or []}
            | {category_names.get(c, f"wp-cat-{c}") for c in post.get("categories") or []}
        )
        records["articles"].append({
            "blog_handle": BLOG_HANDLE,
            "handle": handle,
            "title": title,
            "body_html": clean_text(post.get("content")),
            "excerpt": clean_text(post.get("excerpt")),
            "author": author,
            "published": post.get("status") == "publish",
            "published_at": post.get("date_gmt"),
            "tags": tags,
            "seo": {
                "title": clean_text(yoast.get("title")) or title,
                "description": clean_text(yoast.get("description") or yoast.get("og_description")),
            },
            "source_permalink": post.get("link"),
            "held": False,
            "source": ctx.source(woo_id, "post"),
        })


# --------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------
def _customers(ctx, records):
    seen_emails = {}
    for customer in sorted(ctx.data["customers"], key=lambda c: c["id"]):
        woo_id = customer["id"]
        if customer.get("role") != "customer":
            # 4 administrator accounts are staff, not shoppers.
            continue
        email = clean_text(customer.get("email")).lower()
        if not email:
            ctx.exc.add(
                record_type="customer", record_id=woo_id, record_ref=f"customer:{woo_id}",
                stage=STAGE, severity="high", code="customer_without_email",
                message="customer has no email address; Shopify requires one",
                owner=OWNER_CLIENT, retry_status="needs-decision",
            )
            continue
        if email in seen_emails:
            ctx.exc.add(
                record_type="customer", record_id=woo_id, record_ref=f"customer:{woo_id}",
                stage=STAGE, severity="high", code="duplicate_customer_email",
                message=f"email already used by source customer {seen_emails[email]}",
                owner=OWNER_CLIENT, retry_status="needs-decision",
            )
            continue
        seen_emails[email] = woo_id

        billing = customer.get("billing") or {}
        shipping = customer.get("shipping") or {}
        address = _address(shipping) or _address(billing)
        if not address:
            ctx.exc.add(
                record_type="customer", record_id=woo_id, record_ref=f"customer:{woo_id}",
                stage=STAGE, severity="low", code="customer_without_address",
                message="no billing or shipping address on the source account",
                owner=OWNER_CLIENT, retry_status="needs-decision",
            )
        records["customers"].append({
            "email": email,
            "first_name": clean_text(customer.get("first_name")),
            "last_name": clean_text(customer.get("last_name")),
            "phone": clean_text(billing.get("phone")) or None,
            "default_address": address,
            "tags": ["migrated:woocommerce", f"woo:{woo_id}"],
            # The audit found no marketing-consent field anywhere in the source,
            # so nothing is opted in. Never invent consent.
            "email_marketing_consent": {"state": "NOT_SUBSCRIBED", "opt_in_level": None,
                                        "consent_updated_at": None, "evidence": "none-in-source"},
            "sms_marketing_consent": None,
            "tax_exempt": False,
            "note": None,
            "held": False,
            "source": ctx.source(woo_id, "customer"),
        })


def _address(block):
    if not block:
        return None
    if not clean_text(block.get("address_1")):
        return None
    return {
        "first_name": clean_text(block.get("first_name")),
        "last_name": clean_text(block.get("last_name")),
        "company": clean_text(block.get("company")) or None,
        "address1": clean_text(block.get("address_1")),
        "address2": clean_text(block.get("address_2")) or None,
        "city": clean_text(block.get("city")),
        "province_code": clean_text(block.get("state")) or None,
        "zip": clean_text(block.get("postcode")),
        "country_code": clean_text(block.get("country")) or "AU",
        "phone": clean_text(block.get("phone")) or None,
    }


# --------------------------------------------------------------------------
# Discounts
# --------------------------------------------------------------------------
ADVANCED_COUPON_PREFIXES = ("_acfw", "_wjecf", "_flexible_coupon")


def _discounts(ctx, records):
    for coupon in sorted(ctx.data["coupons"], key=lambda c: c["id"]):
        woo_id = coupon["id"]
        code = clean_text(coupon.get("code"))
        discount_type = coupon.get("discount_type")
        if discount_type == "percent":
            value = {"type": "percentage", "amount": to_decimal_string(coupon.get("amount"))}
        elif discount_type in ("fixed_cart", "fixed_product"):
            value = {"type": "fixed_amount", "amount": to_decimal_string(coupon.get("amount")),
                     "currency": "AUD",
                     "applies_on_each_item": discount_type == "fixed_product"}
        else:
            value = {"type": "unsupported", "amount": to_decimal_string(coupon.get("amount"))}
            ctx.exc.add(
                record_type="discount", record_id=woo_id, record_ref=code, stage=STAGE,
                severity="high", code="unsupported_discount_type",
                message=f"WooCommerce discount type '{discount_type}' has no direct "
                        f"discountCodeBasic equivalent",
                owner=OWNER_AGENCY, retry_status="needs-decision",
            )

        advanced = sorted({
            entry.get("key")
            for entry in coupon.get("meta_data") or []
            if str(entry.get("key", "")).startswith(ADVANCED_COUPON_PREFIXES)
            and entry.get("value") not in (None, "", [], {}, "no")
        })
        if advanced:
            ctx.exc.add(
                record_type="discount", record_id=woo_id, record_ref=code, stage=STAGE,
                severity="medium", code="advanced_coupon_rules",
                message="coupon carries Advanced Coupons / Flexible Coupons rules that "
                        "Shopify discountCodeBasic cannot express",
                owner=OWNER_CLIENT, retry_status="needs-decision",
                detail={"meta_keys": advanced},
            )

        minimum = to_decimal_string(coupon.get("minimum_amount"))
        records["discounts"].append({
            "code": code,
            "title": code,
            "value": value,
            "free_shipping": bool(coupon.get("free_shipping")),
            "starts_at": coupon.get("date_created_gmt"),
            "ends_at": coupon.get("date_expires_gmt"),
            "status": "ACTIVE" if coupon.get("status") == "publish" else "DISABLED",
            "usage_limit": coupon.get("usage_limit"),
            "applies_once_per_customer": bool(coupon.get("usage_limit_per_user")),
            "minimum_subtotal": minimum if minimum and float(minimum) > 0 else None,
            "entitled_product_ids": coupon.get("product_ids") or [],
            "entitled_category_ids": coupon.get("product_categories") or [],
            "excluded_product_ids": coupon.get("excluded_product_ids") or [],
            "customer_selection": "ALL",
            "combines_with": {"orderDiscounts": not coupon.get("individual_use"),
                              "productDiscounts": not coupon.get("individual_use"),
                              "shippingDiscounts": not coupon.get("individual_use")},
            "unsupported_rules": advanced,
            "held": value["type"] == "unsupported",
            "source": ctx.source(woo_id, "coupon"),
        })


# --------------------------------------------------------------------------
# Source id -> handle map
# --------------------------------------------------------------------------
def _id_map(records, snapshot):
    rows = []
    for record_type, key in (
        ("products", "handle"), ("pages", "handle"), ("articles", "handle"),
        ("variants", "sku"), ("discounts", "code"), ("customers", "email"),
    ):
        for row in records[record_type]:
            rows.append({
                "woo_type": row["source"]["woo_type"],
                "woo_id": row["source"]["woo_id"],
                "shopify_key": key,
                # Customer emails are personal data; the map keeps a stable
                # reference instead. exports/ still holds the real value.
                "value": row[key] if record_type != "customers" else f"customer:{row['source']['woo_id']}",
                "held": row.get("held", False),
                "source_snapshot": snapshot,
            })
    for row in records["collections"]:
        rows.append({"woo_type": "collection", "woo_id": None, "shopify_key": "handle",
                     "value": row["handle"], "held": False, "source_snapshot": snapshot})
    records["id_map"] = rows
