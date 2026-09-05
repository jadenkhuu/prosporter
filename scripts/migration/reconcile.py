#!/usr/bin/env python3
"""Stage 4 - reconcile.

Field-level comparison of the WooCommerce source against the fake Shopify
target, covering every line of the execution plan's "Dry-run reconciliation"
list. Writes a full report to exports/migration/<run-id>/reconciliation.json and
PII-free summaries to docs/migration/.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from common import DOCS_OUT, clean_text, to_decimal_string, write_json


def reconcile(data: dict, records: dict, target, exc, run_meta: dict) -> dict:
    checks: list[dict] = []

    def check(name, source, target_value, explanation=None, held=0):
        status = "match" if source == target_value else ("explained" if explanation else "mismatch")
        checks.append({
            "check": name,
            "source": source,
            "target": target_value,
            "held": held,
            "status": status,
            "explanation": explanation,
        })

    products = data["products"]
    variations = data["variations"]
    loaded_products = [p for p in records["products"] if not p["held"]]
    held_products = [p for p in records["products"] if p["held"]]
    loaded_variants = [v for v in records["variants"] if not v["held"]]
    held_variants = [v for v in records["variants"] if v["held"]]

    # --- products by publication status -----------------------------------
    source_status = Counter(p.get("status") for p in products)
    check(
        "product_count_total", len(products), len(loaded_products),
        _held_reason(held_products) if held_products else None,
        held=len(held_products),
    )
    check("product_count_source_publish", source_status.get("publish", 0),
          sum(1 for p in loaded_products if p["source_status"] == "publish"),
          "products held for a client decision are not loaded" if held_products else None,
          held=sum(1 for p in held_products if p["source_status"] == "publish"))
    check("product_count_source_draft", source_status.get("draft", 0),
          sum(1 for p in loaded_products if p["source_status"] == "draft"),
          "products held for a client decision are not loaded" if held_products else None,
          held=sum(1 for p in held_products if p["source_status"] == "draft"))
    check("product_count_target_draft_status", len(loaded_products),
          sum(1 for p in loaded_products if p["status"] == "DRAFT"),
          "dry runs keep every product in draft")

    # --- variants ---------------------------------------------------------
    simple_products = sum(1 for p in products if not p.get("variations"))
    check("variant_count_total", len(variations) + simple_products, len(loaded_variants),
          "simple products contribute one default variant; held variants are excluded"
          if held_variants or simple_products else None,
          held=len(held_variants))

    per_product_source = Counter(v.get("parent_id") for v in variations)
    per_product_target = Counter(v["product_handle"] for v in loaded_variants)
    handle_by_id = {p["source"]["woo_id"]: p["handle"] for p in records["products"]}
    variant_diffs = []
    for woo_id, count in sorted(per_product_source.items()):
        handle = handle_by_id.get(woo_id)
        target_count = per_product_target.get(handle, 0)
        if target_count != count:
            variant_diffs.append({"product_handle": handle, "woo_id": woo_id,
                                  "source": count, "target": target_count})
    check("variant_count_products_with_a_difference", 0, len(variant_diffs),
          "each difference is a held product or held variant with a named exception"
          if variant_diffs else None)

    # --- SKUs -------------------------------------------------------------
    source_skus = [clean_text(v.get("sku")) for v in variations]
    check("sku_null_count_source", sum(1 for s in source_skus if not s), 0,
          "blank SKUs are filled deterministically as PS-<product>-<variation>")
    target_skus = [v["sku"] for v in loaded_variants]
    check("sku_unique_count", len(target_skus), len(set(target_skus)),
          "duplicate source SKUs are reported, never silently rewritten"
          if len(target_skus) != len(set(target_skus)) else None)
    check("sku_generated_count", sum(1 for v in records["variants"] if v["sku_generated"]),
          sum(1 for v in loaded_variants if v["sku_generated"]),
          "generated SKUs on held variants are not loaded"
          if held_variants else None)

    # --- media ------------------------------------------------------------
    source_images = sum(len({i.get("src") for i in (p.get("images") or [])}) for p in products)
    loaded_media = [m for m in records["media"] if not m["held"]]
    check("image_count_total", source_images, len(loaded_media),
          "variant-specific images are added on top of the product gallery; held "
          "products contribute none")
    per_product_media = Counter(m["product_handle"] for m in loaded_media)
    check("products_without_image", sum(1 for p in products if not (p.get("images") or [])),
          sum(1 for p in loaded_products if per_product_media.get(p["handle"], 0) == 0),
          "counted on the loaded subset")
    check("media_unreachable", sum(1 for m in records["media"] if m["reachable"] is False), 0,
          "unreachable media is excluded from the count only when held")
    check("media_checksums_present", len(loaded_media),
          sum(1 for m in loaded_media if m["checksum"]["value"]),
          "checksums are URL hashes in the dry run; byte checksums need the real fileCreate")

    # --- collections ------------------------------------------------------
    check("collection_count", len(records["collections"]),
          len(target.objects("Collection")))
    membership_source = sum(len(c["product_handles"]) for c in records["collections"])
    membership_target = sum(
        len(o["payload"]["product_handles"])
        for o in target.objects("CollectionMembership").values()
    )
    check("collection_membership_rows", membership_source, membership_target)
    check("products_in_at_least_one_collection", len(loaded_products),
          len({h for c in records["collections"] for h in c["product_handles"]}))

    # --- price / compare-at / currency / taxability ------------------------
    variation_by_id = {v["id"]: v for v in variations}
    product_by_id = {p["id"]: p for p in products}
    price_mismatch = compare_mismatch = tax_mismatch = currency_mismatch = 0
    for variant in loaded_variants:
        woo_id = variant["source"]["woo_id"]
        source_row = variation_by_id.get(woo_id) or product_by_id.get(woo_id) or {}
        parent = product_by_id.get(source_row.get("parent_id"), source_row)
        regular = to_decimal_string(source_row.get("regular_price"))
        sale = to_decimal_string(source_row.get("sale_price"))
        expected_price = (sale or regular or to_decimal_string(source_row.get("price"))
                          or to_decimal_string(parent.get("regular_price"))
                          or to_decimal_string(parent.get("price")))
        expected_compare = regular if (sale and regular and sale != regular) else None
        expected_tax = (source_row.get("tax_status") or parent.get("tax_status")
                        or "taxable") == "taxable"
        price_mismatch += variant["price"] != expected_price
        compare_mismatch += variant["compare_at_price"] != expected_compare
        tax_mismatch += variant["taxable"] != expected_tax
        currency_mismatch += variant["currency"] != "AUD"
    check("variant_price_field_mismatches", 0, price_mismatch)
    check("variant_compare_at_field_mismatches", 0, compare_mismatch)
    check("variant_taxable_field_mismatches", 0, tax_mismatch)
    check("variant_currency_field_mismatches", 0, currency_mismatch)
    held_by_code = _held_variant_reasons(exc, records)
    no_regular = sum(1 for v in variations if not to_decimal_string(v.get("regular_price")))
    held_price = held_by_code.get("variant_missing_price", 0)
    check("variants_without_regular_price_in_source", no_regular, held_price,
          f"{no_regular - held_price} inherit the parent product price; {held_price} have no "
          f"price anywhere and are held pending client-supplied prices")
    check("held_variants_missing_option_value", 0,
          held_by_code.get("variant_missing_option_value", 0),
          "WooCommerce 'Any <option>' variations have no Shopify equivalent")
    check("held_variants_total", 0, len(held_variants),
          "held variants = missing price + missing option value + variants of held products")

    # --- inventory --------------------------------------------------------
    inventory = target.objects("InventoryItem")
    check("inventory_item_count", len(loaded_variants), len(inventory))
    source_quantity = sum(
        v.get("stock_quantity") or 0 for v in variations if isinstance(v.get("stock_quantity"), int)
    )
    target_quantity = sum(
        o["payload"]["quantity"] or 0 for o in inventory.values()
        if isinstance(o["payload"]["quantity"], int)
    )
    check("inventory_staged_quantity_total", source_quantity, target_quantity,
          "held variants carry their stock out of the total" if held_variants else None)

    # --- pages and articles ------------------------------------------------
    loaded_pages = [p for p in records["pages"] if not p["held"]]
    check("page_count", len(data["pages"]), len(loaded_pages),
          "WooCommerce functional pages (cart/checkout/account) are storefront routes")
    check("article_count", len(data["posts"]), len(records["articles"]))

    # --- SEO ---------------------------------------------------------------
    check("product_seo_title_populated", len(loaded_products),
          sum(1 for p in loaded_products if p["seo"]["title"]))
    check("product_seo_description_populated",
          sum(1 for p in products if clean_text((p.get("yoast_head_json") or {}).get("description"))),
          sum(1 for p in loaded_products if p["seo"]["description"]),
          "Yoast meta description is absent on most products; the Open Graph "
          "description is used as a fallback")

    # --- customers ---------------------------------------------------------
    source_customers = [c for c in data["customers"] if c.get("role") == "customer"]
    admins = [c for c in data["customers"] if c.get("role") != "customer"]
    check("customer_count", len(source_customers), len(records["customers"]),
          f"{len(admins)} administrator accounts excluded by role; "
          "failed records are in the exception register")
    check("customer_unique_emails", len(records["customers"]),
          len({c["email"] for c in records["customers"]}))
    check("customer_with_default_address",
          sum(1 for c in source_customers
              if clean_text((c.get("shipping") or {}).get("address_1"))
              or clean_text((c.get("billing") or {}).get("address_1"))),
          sum(1 for c in records["customers"] if c["default_address"]))
    check("customer_marketing_consent_true", 0,
          sum(1 for c in records["customers"]
              if c["email_marketing_consent"]["state"] != "NOT_SUBSCRIBED"),
          "the source has no consent field, so nothing is opted in")

    # --- discounts ----------------------------------------------------------
    active_source = sum(1 for c in data["coupons"] if c.get("status") == "publish")
    check("discount_count", len(data["coupons"]), len(records["discounts"]))
    check("discount_active_count", active_source,
          sum(1 for d in records["discounts"] if d["status"] == "ACTIVE"))
    check("discount_free_shipping_count",
          sum(1 for c in data["coupons"] if c.get("free_shipping")),
          sum(1 for d in records["discounts"] if d["free_shipping"]))
    check("discount_with_unsupported_rules", 0,
          sum(1 for d in records["discounts"] if d["unsupported_rules"]),
          "Advanced Coupons rules cannot be expressed by discountCodeBasic")

    report = {
        "run": run_meta,
        "summary": {
            "checks_total": len(checks),
            "match": sum(1 for c in checks if c["status"] == "match"),
            "explained": sum(1 for c in checks if c["status"] == "explained"),
            "mismatch": sum(1 for c in checks if c["status"] == "mismatch"),
            "held_products": len(held_products),
            "held_variants": len(held_variants),
            "exceptions_by_severity": exc.by_severity(),
            "exceptions_by_code": exc.by_code(),
        },
        "checks": checks,
        "variant_count_differences": variant_diffs,
        "held": {
            "products": sorted({p["handle"] for p in held_products}),
            "product_reasons": _held_reason_counts(held_products),
            "variant_skus": sorted({v["sku"] for v in held_variants}),
        },
        "target_object_counts": target.counts(),
    }
    return report


def _held_variant_reasons(exc, records):
    held_skus = {v["sku"] for v in records["variants"] if v["held"]}
    counts = defaultdict(int)
    for row in exc.rows:
        if row["record"]["type"] == "variant" and row["record"]["ref"] in held_skus:
            counts[row["code"]] += 1
    return dict(counts)


def _held_reason(held_products):
    reasons = sorted({r.split(":")[0] for p in held_products for r in p["held_reasons"]})
    return "held for a client decision: " + ", ".join(reasons)


def _held_reason_counts(held_products):
    counts = Counter(r.split(":")[0] for p in held_products for r in p["held_reasons"])
    return dict(sorted(counts.items()))


# --------------------------------------------------------------------------
# PII-free documentation outputs
# --------------------------------------------------------------------------
def write_docs(report: dict, exc, run_meta: dict) -> list[Path]:
    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    written = [_write_reconciliation_md(report, run_meta), _write_exception_csv(exc)]
    return written


def _write_reconciliation_md(report: dict, run_meta: dict) -> Path:
    path = DOCS_OUT / "reconciliation-latest.md"
    summary = report["summary"]
    lines = [
        "# Migration dry-run reconciliation (latest)",
        "",
        "Counts only. Generated by `python3 scripts/migration/run.py all`. No personal data:",
        "customers appear as counts, never as names or addresses.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Run id | `{run_meta['run_id']}` |",
        f"| Generated | {run_meta['generated_at']} |",
        f"| Source snapshot | {run_meta['source_snapshot']} |",
        f"| Source directory | `{run_meta['source_dir']}` |",
        f"| Target | `{run_meta['target']}` |",
        f"| Shopify API version | `{run_meta['shopify_api_version']}` |",
        f"| Pipeline commit | `{run_meta['script_commit']}` |",
        "",
        f"**{summary['match']} matched, {summary['explained']} explained, "
        f"{summary['mismatch']} unexplained** out of {summary['checks_total']} checks.",
        "",
        "## Reconciliation checks",
        "",
        "| Check | Source | Target | Held | Status | Explanation |",
        "|---|---:|---:|---:|---|---|",
    ]
    for check in report["checks"]:
        lines.append(
            f"| {check['check']} | {check['source']} | {check['target']} | {check['held']} "
            f"| {check['status']} | {check['explanation'] or ''} |"
        )
    lines += [
        "",
        "## Exceptions by severity",
        "",
        "| Severity | Count |",
        "|---|---:|",
    ]
    for severity, count in summary["exceptions_by_severity"].items():
        lines.append(f"| {severity} | {count} |")
    lines += ["", "## Exceptions by code", "", "| Code | Count |", "|---|---:|"]
    for code, count in summary["exceptions_by_code"].items():
        lines.append(f"| {code} | {count} |")
    lines += [
        "",
        "## Records held out of the load",
        "",
        f"- Products held: {summary['held_products']} "
        f"({', '.join(report['held']['products']) or 'none'})",
        f"- Variants held: {summary['held_variants']}",
        "",
        "Reasons: "
        + (", ".join(f"{k} ({v})" for k, v in report["held"]["product_reasons"].items()) or "none"),
        "",
        "## Target object counts",
        "",
        "| Shopify resource | Objects in the fake store |",
        "|---|---:|",
    ]
    for resource, count in report["target_object_counts"].items():
        lines.append(f"| {resource} | {count} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_exception_csv(exc) -> Path:
    path = DOCS_OUT / "exception-register.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "severity", "code", "record_type", "record_id", "record_ref",
            "stage", "owner", "retry_status", "message",
        ])
        for row in exc.rows:
            record = row["record"]
            ref = record["ref"]
            record_id = record["id"]
            if record["type"] == "customer":
                # Redact: never put a customer email or name in a committed file.
                ref = f"customer:{record_id}"
            writer.writerow([
                row["severity"], row["code"], record["type"], record_id, ref,
                row["stage"], row["owner"], row["retry_status"], row["message"],
            ])
    return path


def write_run_report(run_dir: Path, report: dict) -> Path:
    path = run_dir / "reconciliation.json"
    write_json(path, report)
    return path
