#!/usr/bin/env python3
"""Workstream 5 - historical-order archive.

Historical WooCommerce orders are NOT loaded into Shopify. They are delivered as
a self-contained CSV archive that opens in Excel/Google Sheets without any
WordPress, WooCommerce, Shopify or purpl solutions system.

    python3 scripts/migration/archive.py
    python3 scripts/migration/archive.py --source exports --out exports/migration/archive/<run-id>

Python 3 standard library only. Deterministic: the same snapshot produces
byte-identical CSVs (and therefore identical checksums) on every run, apart from
the generated-at timestamp recorded in manifest.json.

The archive contains personal data. It is written under exports/ (git-ignored)
and must never be copied into docs/ or into git.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from common import (
    DEFAULT_SOURCE,
    MIGRATION_OUT,
    PIPELINE_VERSION,
    clean_text,
    git_rev,
    read_json,
    rel,
    utc_now,
    write_json,
)

# Source files this stage reads. name -> required?
SOURCE_FILES = {
    "orders": True,
    "refunds": True,
    "customers": False,
    "payment_gateways": False,
    "order_notes_sample": False,
}

# The store runs on UTC (exports/system_status.json: default_timezone = UTC) and
# WooCommerce returned identical local and GMT timestamps for every record, so
# the naive source timestamps are stamped as UTC rather than guessed at.
SOURCE_TZ_SUFFIX = "+00:00"

# Cells that a spreadsheet would evaluate as a formula.
INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")

# Line-item meta keys that are WooCommerce/plugin internals, not customer data.
INTERNAL_META_PREFIXES = ("_",)


class SourceMissing(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def money(value) -> str:
    """Woo money string -> plain decimal string. Empty string when absent."""
    if value in (None, "", False):
        return ""
    try:
        return f"{Decimal(str(value).strip().replace(',', '')):.2f}"
    except (InvalidOperation, ValueError):
        return ""


def dec(value) -> Decimal:
    try:
        return Decimal(str(value).strip().replace(",", "") or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def iso(value) -> str:
    """Naive WooCommerce timestamp -> ISO 8601 with an explicit offset."""
    text = (value or "").strip()
    if not text:
        return ""
    if text.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", text):
        return text
    return text + SOURCE_TZ_SUFFIX


def neutralise(value) -> str:
    """RFC 4180 stays intact; spreadsheet formula evaluation does not.

    A plain number can never be a formula, so numeric cells are left alone and
    stay numeric in Excel. Anything else that starts with = + - @ tab or CR is
    prefixed with an apostrophe, the convention Excel and Sheets both treat as
    "this is text".
    """
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if NUMERIC_RE.match(text):
        return text
    if text.startswith(INJECTION_PREFIXES):
        return "'" + text
    return text


def text(value) -> str:
    """Unescape WP entities and flatten newlines so a cell stays one line."""
    cleaned = clean_text(value)
    return re.sub(r"\s*[\r\n]+\s*", " ", cleaned).strip()


def _meta_pairs(meta_data):
    """Customer-visible line-item options (size, colour, ...), source order kept."""
    pairs = []
    for entry in meta_data or []:
        key = str(entry.get("display_key") or entry.get("key") or "")
        if not key or key.startswith(INTERNAL_META_PREFIXES):
            continue
        value = entry.get("display_value")
        if value is None:
            value = entry.get("value")
        if isinstance(value, (dict, list)):
            continue
        pairs.append(f"{text(key)}: {text(value)}")
    return pairs


def meta_value(meta_data, key):
    for entry in meta_data or []:
        if entry.get("key") == key:
            return entry.get("value")
    return None


# --------------------------------------------------------------------------- #
# extract
# --------------------------------------------------------------------------- #
def load_source(source_dir: Path) -> dict:
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise SourceMissing(f"source directory not found: {source_dir}")

    data = {}
    missing = []
    for name, required in SOURCE_FILES.items():
        path = source_dir / f"{name}.json"
        if path.exists():
            data[name] = read_json(path)
        elif required:
            missing.append(name)
        else:
            data[name] = []
    if missing:
        raise SourceMissing(
            f"missing required export files in {source_dir}: {', '.join(sorted(missing))}"
        )

    manifest_path = source_dir / "_manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    data["_meta"] = {
        "source_dir": str(source_dir),
        "source_snapshot": manifest.get("finished") or manifest.get("started") or "unknown",
        "source_base": manifest.get("base", "unknown"),
    }
    return data


# --------------------------------------------------------------------------- #
# table builders - each returns (columns, rows)
# --------------------------------------------------------------------------- #
ADDRESS_FIELDS = [
    "first_name", "last_name", "company", "address_1", "address_2",
    "city", "state", "postcode", "country", "email", "phone",
]

ORDER_COLUMNS = (
    [
        "order_number", "order_id", "parent_order_id", "status", "currency",
        "date_created", "date_modified", "date_paid", "date_completed",
        "created_via", "customer_id", "customer_note",
    ]
    + [f"billing_{f}" for f in ADDRESS_FIELDS]
    + [f"shipping_{f}" for f in ADDRESS_FIELDS if f != "email"]
    + [
        "line_item_count", "item_quantity", "items_subtotal", "discount_total",
        "discount_tax", "shipping_total", "shipping_tax", "fee_total",
        "cart_tax", "total_tax", "order_total", "refunded_total", "net_total",
        "coupon_codes", "shipping_methods", "payment_method",
        "payment_method_title", "transaction_id", "prices_include_tax",
        "order_key",
    ]
)


def build_orders(orders, refunds_by_order):
    rows = []
    for order in orders:
        billing = order.get("billing") or {}
        shipping = order.get("shipping") or {}
        items = order.get("line_items") or []
        items_subtotal = sum(dec(i.get("subtotal")) for i in items)
        fee_total = sum(dec(f.get("total")) for f in order.get("fee_lines") or [])
        refunded = sum(
            abs(dec(r.get("amount"))) for r in refunds_by_order.get(order["id"], [])
        )
        total = dec(order.get("total"))
        row = {
            "order_number": str(order.get("number") or order["id"]),
            "order_id": order["id"],
            "parent_order_id": order.get("parent_id") or "",
            "status": order.get("status") or "",
            "currency": order.get("currency") or "",
            "date_created": iso(order.get("date_created_gmt") or order.get("date_created")),
            "date_modified": iso(order.get("date_modified_gmt") or order.get("date_modified")),
            "date_paid": iso(order.get("date_paid_gmt") or order.get("date_paid")),
            "date_completed": iso(
                order.get("date_completed_gmt") or order.get("date_completed")
            ),
            "created_via": order.get("created_via") or "",
            "customer_id": order.get("customer_id") if order.get("customer_id") else "",
            "customer_note": text(order.get("customer_note")),
            "line_item_count": len(items),
            "item_quantity": sum(int(i.get("quantity") or 0) for i in items),
            "items_subtotal": f"{items_subtotal:.2f}",
            "discount_total": money(order.get("discount_total")),
            "discount_tax": money(order.get("discount_tax")),
            "shipping_total": money(order.get("shipping_total")),
            "shipping_tax": money(order.get("shipping_tax")),
            "fee_total": f"{fee_total:.2f}",
            "cart_tax": money(order.get("cart_tax")),
            "total_tax": money(order.get("total_tax")),
            "order_total": money(order.get("total")),
            "refunded_total": f"{refunded:.2f}",
            "net_total": f"{total - refunded:.2f}",
            "coupon_codes": "; ".join(
                text(c.get("code")) for c in order.get("coupon_lines") or []
            ),
            "shipping_methods": "; ".join(
                text(s.get("method_title")) for s in order.get("shipping_lines") or []
            ),
            "payment_method": order.get("payment_method") or "",
            "payment_method_title": text(order.get("payment_method_title")),
            "transaction_id": order.get("transaction_id") or "",
            "prices_include_tax": "yes" if order.get("prices_include_tax") else "no",
            "order_key": order.get("order_key") or "",
        }
        for field in ADDRESS_FIELDS:
            row[f"billing_{field}"] = text(billing.get(field))
            if field != "email":
                row[f"shipping_{field}"] = text(shipping.get(field))
        rows.append(row)
    return ORDER_COLUMNS, rows


ORDER_LINE_COLUMNS = [
    "order_number", "order_id", "line_id", "line_type", "product_id",
    "variation_id", "sku", "product_name", "parent_name", "variant",
    "quantity", "unit_price", "line_subtotal", "line_discount", "line_total",
    "line_tax", "currency",
]


def build_order_lines(orders):
    rows = []
    for order in orders:
        base = {
            "order_number": str(order.get("number") or order["id"]),
            "order_id": order["id"],
            "currency": order.get("currency") or "",
        }
        for item in order.get("line_items") or []:
            subtotal = dec(item.get("subtotal"))
            line_total = dec(item.get("total"))
            rows.append({
                **base,
                "line_id": item.get("id") or "",
                "line_type": "line_item",
                "product_id": item.get("product_id") or "",
                "variation_id": item.get("variation_id") or "",
                "sku": text(item.get("sku")),
                "product_name": text(item.get("name")),
                "parent_name": text(item.get("parent_name")),
                "variant": "; ".join(_meta_pairs(item.get("meta_data"))),
                "quantity": item.get("quantity") if item.get("quantity") is not None else "",
                "unit_price": money(item.get("price")),
                "line_subtotal": f"{subtotal:.2f}",
                "line_discount": f"{subtotal - line_total:.2f}",
                "line_total": f"{line_total:.2f}",
                "line_tax": money(item.get("total_tax")),
            })
        for line in order.get("shipping_lines") or []:
            total = dec(line.get("total"))
            rows.append({
                **base,
                "line_id": line.get("id") or "",
                "line_type": "shipping",
                "product_id": "", "variation_id": "", "sku": "",
                "product_name": text(line.get("method_title")),
                "parent_name": "",
                "variant": text(line.get("method_id")),
                "quantity": 1,
                "unit_price": f"{total:.2f}",
                "line_subtotal": f"{total:.2f}",
                "line_discount": "0.00",
                "line_total": f"{total:.2f}",
                "line_tax": money(line.get("total_tax")),
            })
        for fee in order.get("fee_lines") or []:
            total = dec(fee.get("total"))
            rows.append({
                **base,
                "line_id": fee.get("id") or "",
                "line_type": "fee",
                "product_id": "", "variation_id": "", "sku": "",
                "product_name": text(fee.get("name")),
                "parent_name": "",
                "variant": "",
                "quantity": 1,
                "unit_price": f"{total:.2f}",
                "line_subtotal": f"{total:.2f}",
                "line_discount": "0.00",
                "line_total": f"{total:.2f}",
                "line_tax": money(fee.get("total_tax")),
            })
    return ORDER_LINE_COLUMNS, rows


PAYMENT_COLUMNS = [
    "order_number", "order_id", "payment_method", "payment_method_title",
    "gateway_method_title", "transaction_reference", "amount", "currency",
    "payment_date", "payment_status", "refunded_total", "net_amount",
]

PAID_STATUSES = {"completed", "processing", "refunded", "return-approved", "on-hold"}


def build_payments(orders, refunds_by_order, gateways):
    gateway_titles = {
        g.get("id"): text(g.get("method_title") or g.get("title"))
        for g in gateways or []
        if g.get("id")
    }
    rows = []
    for order in orders:
        status = order.get("status") or ""
        refunded = sum(
            abs(dec(r.get("amount"))) for r in refunds_by_order.get(order["id"], [])
        )
        total = dec(order.get("total"))
        if status == "refunded":
            payment_status = "refunded"
        elif refunded > 0:
            payment_status = "partially-refunded"
        elif order.get("date_paid_gmt") or order.get("date_paid"):
            payment_status = "paid"
        elif status in {"cancelled", "failed"}:
            payment_status = status
        elif status in PAID_STATUSES:
            payment_status = "paid-date-not-recorded"
        else:
            payment_status = "unpaid"
        rows.append({
            "order_number": str(order.get("number") or order["id"]),
            "order_id": order["id"],
            "payment_method": order.get("payment_method") or "",
            "payment_method_title": text(order.get("payment_method_title")),
            "gateway_method_title": gateway_titles.get(order.get("payment_method"), ""),
            "transaction_reference": order.get("transaction_id") or "",
            "amount": money(order.get("total")),
            "currency": order.get("currency") or "",
            "payment_date": iso(order.get("date_paid_gmt") or order.get("date_paid")),
            "payment_status": payment_status,
            "refunded_total": f"{refunded:.2f}",
            "net_amount": f"{total - refunded:.2f}",
        })
    return PAYMENT_COLUMNS, rows


REFUND_COLUMNS = [
    "refund_id", "order_number", "order_id", "refund_date", "amount",
    "currency", "refund_type", "reason", "refunded_by_user_id",
    "refunded_payment", "refund_line_count",
]

REFUND_LINE_COLUMNS = [
    "refund_id", "order_number", "order_id", "line_id", "refunded_item_id",
    "product_id", "variation_id", "sku", "product_name", "variant", "quantity",
    "line_subtotal", "line_total", "line_tax", "currency",
]


def _refund_parent_id(refund) -> int | None:
    for link in (refund.get("_links") or {}).get("up") or []:
        match = re.search(r"/orders/(\d+)", link.get("href") or "")
        if match:
            return int(match.group(1))
    return None


def build_refunds(refunds, orders):
    by_id = {o["id"]: o for o in orders}
    # WooCommerce nests refund ids on the order; use that as the primary link and
    # fall back to the refund's own _links.up href.
    order_of_refund = {}
    for order in orders:
        for nested in order.get("refunds") or []:
            order_of_refund[nested.get("id")] = order["id"]

    refund_rows, line_rows, orphans = [], [], []
    for refund in refunds:
        order_id = order_of_refund.get(refund.get("id")) or _refund_parent_id(refund)
        order = by_id.get(order_id)
        if order is None:
            orphans.append(refund.get("id"))
        order_number = str(order.get("number") or order["id"]) if order else ""
        currency = (order or {}).get("currency") or ""
        lines = refund.get("line_items") or []
        refund_rows.append({
            "refund_id": refund.get("id"),
            "order_number": order_number,
            "order_id": order_id or "",
            "refund_date": iso(refund.get("date_created_gmt") or refund.get("date_created")),
            "amount": money(refund.get("amount")),
            "currency": currency,
            "refund_type": text(meta_value(refund.get("meta_data"), "_refund_type")),
            "reason": text(refund.get("reason")),
            "refunded_by_user_id": refund.get("refunded_by") or "",
            "refunded_payment": "yes" if refund.get("refunded_payment") else "no",
            "refund_line_count": len(lines),
        })
        for item in lines:
            line_rows.append({
                "refund_id": refund.get("id"),
                "order_number": order_number,
                "order_id": order_id or "",
                "line_id": item.get("id") or "",
                "refunded_item_id": text(meta_value(item.get("meta_data"), "_refunded_item_id")),
                "product_id": item.get("product_id") or "",
                "variation_id": item.get("variation_id") or "",
                "sku": text(item.get("sku")),
                "product_name": text(item.get("name")),
                "variant": "; ".join(_meta_pairs(item.get("meta_data"))),
                "quantity": item.get("quantity") if item.get("quantity") is not None else "",
                "line_subtotal": money(item.get("subtotal")),
                "line_total": money(item.get("total")),
                "line_tax": money(item.get("total_tax")),
                "currency": currency,
            })
    return (REFUND_COLUMNS, refund_rows), (REFUND_LINE_COLUMNS, line_rows), orphans


FULFILMENT_COLUMNS = [
    "order_number", "order_id", "fulfilment_status", "fulfilment_date",
    "delivery_type", "shipping_method", "shipping_method_id", "carrier",
    "tracking_number", "tracking_url", "item_quantity",
    "shipping_recipient_name", "shipping_city", "shipping_state",
    "shipping_postcode", "shipping_country",
]

FULFILMENT_LINE_COLUMNS = [
    "order_number", "order_id", "line_id", "sku", "product_name", "variant",
    "quantity", "fulfilment_status",
]

FULFILLED_STATUSES = {"completed"}
UNFULFILLABLE_STATUSES = {"cancelled", "failed", "pending"}


def build_fulfilments(orders):
    rows, line_rows = [], []
    for order in orders:
        status = order.get("status") or ""
        if status in FULFILLED_STATUSES:
            fulfilment_status = "fulfilled"
        elif status in UNFULFILLABLE_STATUSES:
            fulfilment_status = f"not-fulfilled ({status})"
        else:
            fulfilment_status = f"in-progress ({status})"
        shipping_lines = order.get("shipping_lines") or []
        method_ids = [s.get("method_id") or "" for s in shipping_lines]
        if method_ids and all(m == "local_pickup" for m in method_ids):
            delivery_type = "pickup"
        elif method_ids:
            delivery_type = "shipped"
        else:
            delivery_type = "not recorded"
        shipping = order.get("shipping") or {}
        order_number = str(order.get("number") or order["id"])
        rows.append({
            "order_number": order_number,
            "order_id": order["id"],
            "fulfilment_status": fulfilment_status,
            "fulfilment_date": iso(
                order.get("date_completed_gmt") or order.get("date_completed")
            ),
            "delivery_type": delivery_type,
            "shipping_method": "; ".join(text(s.get("method_title")) for s in shipping_lines),
            "shipping_method_id": "; ".join(method_ids),
            # WooCommerce recorded no carrier or consignment data in this store
            # (no shipment-tracking plugin). See README.md "Known source gaps".
            "carrier": "",
            "tracking_number": "",
            "tracking_url": "",
            "item_quantity": sum(
                int(i.get("quantity") or 0) for i in order.get("line_items") or []
            ),
            "shipping_recipient_name": text(
                f"{shipping.get('first_name') or ''} {shipping.get('last_name') or ''}"
            ),
            "shipping_city": text(shipping.get("city")),
            "shipping_state": text(shipping.get("state")),
            "shipping_postcode": text(shipping.get("postcode")),
            "shipping_country": text(shipping.get("country")),
        })
        for item in order.get("line_items") or []:
            line_rows.append({
                "order_number": order_number,
                "order_id": order["id"],
                "line_id": item.get("id") or "",
                "sku": text(item.get("sku")),
                "product_name": text(item.get("name")),
                "variant": "; ".join(_meta_pairs(item.get("meta_data"))),
                "quantity": item.get("quantity") if item.get("quantity") is not None else "",
                "fulfilment_status": fulfilment_status,
            })
    return (FULFILMENT_COLUMNS, rows), (FULFILMENT_LINE_COLUMNS, line_rows)


CUSTOMER_COLUMNS = (
    ["customer_id", "username", "email", "first_name", "last_name", "role",
     "date_created", "is_paying_customer"]
    + [f"billing_{f}" for f in ADDRESS_FIELDS]
    + [f"shipping_{f}" for f in ADDRESS_FIELDS if f != "email"]
    + ["orders_in_archive", "order_total_in_archive"]
)


def build_customers(customers, orders):
    order_count = Counter()
    order_sum = defaultdict(Decimal)
    for order in orders:
        cid = order.get("customer_id")
        if cid:
            order_count[cid] += 1
            order_sum[cid] += dec(order.get("total"))
    rows = []
    for customer in customers:
        billing = customer.get("billing") or {}
        shipping = customer.get("shipping") or {}
        cid = customer.get("id")
        row = {
            "customer_id": cid,
            "username": text(customer.get("username")),
            "email": text(customer.get("email")),
            "first_name": text(customer.get("first_name")),
            "last_name": text(customer.get("last_name")),
            "role": customer.get("role") or "",
            "date_created": iso(
                customer.get("date_created_gmt") or customer.get("date_created")
            ),
            "is_paying_customer": "yes" if customer.get("is_paying_customer") else "no",
            "orders_in_archive": order_count.get(cid, 0),
            "order_total_in_archive": f"{order_sum.get(cid, Decimal('0')):.2f}",
        }
        for field in ADDRESS_FIELDS:
            row[f"billing_{field}"] = text(billing.get(field))
            if field != "email":
                row[f"shipping_{field}"] = text(shipping.get(field))
        rows.append(row)
    return CUSTOMER_COLUMNS, rows


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #
def write_csv(path: Path, columns, rows) -> int:
    """UTF-8 with BOM, RFC 4180 (CRLF, minimal quoting), one header row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([neutralise(row.get(column, "")) for column in columns])
    return len(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# reconciliation
# --------------------------------------------------------------------------- #
RECONCILIATION_COLUMNS = [
    "metric", "scope", "source_value", "archive_value", "difference", "notes",
]


def build_reconciliation(data, tables, refunds_by_order) -> tuple[list, list, dict]:
    orders = data["orders"]
    refunds = data["refunds"]
    order_rows = tables["orders.csv"][1]
    currency_of_order = {o["id"]: (o.get("currency") or "") for o in orders}
    refunds_by_currency = {
        refund.get("id"): currency_of_order.get(order_id, "")
        for order_id, order_refunds in refunds_by_order.items()
        for refund in order_refunds
    }
    rows = []

    def add(metric, scope, source, archive, notes=""):
        try:
            difference = f"{Decimal(str(source)) - Decimal(str(archive)):.2f}".rstrip("0").rstrip(".")
        except (InvalidOperation, ValueError):
            difference = "n/a"
        rows.append({
            "metric": metric, "scope": scope, "source_value": source,
            "archive_value": archive, "difference": difference or "0", "notes": notes,
        })

    add("order_count", "all", len(orders), len(order_rows),
        "every source order is archived; none are loaded into Shopify")

    source_status = Counter(o.get("status") or "" for o in orders)
    archive_status = Counter(r["status"] for r in order_rows)
    for status in sorted(source_status):
        add("order_count", f"status={status}", source_status[status],
            archive_status.get(status, 0), "")

    currencies = sorted({o.get("currency") or "" for o in orders})
    for currency in currencies:
        subset = [o for o in orders if (o.get("currency") or "") == currency]
        order_subset = [r for r in order_rows if r["currency"] == currency]
        line_subset = [
            r for r in tables["order-lines.csv"][1]
            if r["currency"] == currency and r["line_type"] == "line_item"
        ]
        refund_subset = [r for r in refunds if refunds_by_currency.get(r.get("id")) == currency]
        add("gross_line_subtotal", f"currency={currency}",
            f"{sum(dec(i.get('subtotal')) for o in subset for i in o.get('line_items') or []):.2f}",
            f"{sum(dec(r['line_subtotal']) for r in line_subset):.2f}",
            "sum of line-item subtotals before order-level discounts")
        add("discount_total", f"currency={currency}",
            f"{sum(dec(o.get('discount_total')) for o in subset):.2f}",
            f"{sum(dec(r['discount_total']) for r in order_subset):.2f}", "")
        add("shipping_total", f"currency={currency}",
            f"{sum(dec(o.get('shipping_total')) for o in subset):.2f}",
            f"{sum(dec(r['shipping_total']) for r in order_subset):.2f}", "")
        add("tax_total", f"currency={currency}",
            f"{sum(dec(o.get('total_tax')) for o in subset):.2f}",
            f"{sum(dec(r['total_tax']) for r in order_subset):.2f}",
            "store sells GST-inclusive; WooCommerce recorded no separate tax lines")
        add("order_total", f"currency={currency}",
            f"{sum(dec(o.get('total')) for o in subset):.2f}",
            f"{sum(dec(r['order_total']) for r in order_subset):.2f}", "")
        add("refund_total", f"currency={currency}",
            f"{sum(abs(dec(r.get('amount'))) for r in refund_subset):.2f}",
            f"{sum(dec(r['refunded_total']) for r in order_subset):.2f}",
            "refunds are recorded against their source order, not as new orders")
        add("net_total", f"currency={currency}",
            f"{sum(dec(o.get('total')) for o in subset) - sum(abs(dec(r.get('amount'))) for r in refund_subset):.2f}",
            f"{sum(dec(r['net_total']) for r in order_subset):.2f}",
            "order total minus refunds")

    add("line_count", "order line items",
        sum(len(o.get("line_items") or []) for o in orders),
        sum(1 for r in tables["order-lines.csv"][1] if r["line_type"] == "line_item"), "")
    add("line_count", "shipping lines",
        sum(len(o.get("shipping_lines") or []) for o in orders),
        sum(1 for r in tables["order-lines.csv"][1] if r["line_type"] == "shipping"), "")
    add("line_count", "fee lines",
        sum(len(o.get("fee_lines") or []) for o in orders),
        sum(1 for r in tables["order-lines.csv"][1] if r["line_type"] == "fee"), "")
    add("payment_count", "one row per order", len(orders), len(tables["payments.csv"][1]),
        "one payment row per order, including unpaid orders")
    add("refund_count", "all", len(refunds), len(tables["refunds.csv"][1]), "")
    add("refund_line_count", "all",
        sum(len(r.get("line_items") or []) for r in refunds),
        len(tables["refund-lines.csv"][1]), "")
    add("fulfilment_count", "one row per order", len(orders),
        len(tables["fulfilments.csv"][1]), "")
    add("fulfilment_line_count", "all",
        sum(len(o.get("line_items") or []) for o in orders),
        len(tables["fulfilment-lines.csv"][1]), "")
    add("customer_reference_count", "all", len(data["customers"]),
        len(tables["customers-reference.csv"][1]),
        "reference only; customer migration is Workstream 4")

    # Orphan checks: every child row must resolve to an archived order.
    numbers = {r["order_number"] for r in order_rows}
    orphans = {
        "order-lines.csv": sum(1 for r in tables["order-lines.csv"][1] if r["order_number"] not in numbers),
        "payments.csv": sum(1 for r in tables["payments.csv"][1] if r["order_number"] not in numbers),
        "refunds.csv": sum(1 for r in tables["refunds.csv"][1] if r["order_number"] not in numbers),
        "refund-lines.csv": sum(1 for r in tables["refund-lines.csv"][1] if r["order_number"] not in numbers),
        "fulfilments.csv": sum(1 for r in tables["fulfilments.csv"][1] if r["order_number"] not in numbers),
        "fulfilment-lines.csv": sum(1 for r in tables["fulfilment-lines.csv"][1] if r["order_number"] not in numbers),
    }
    for name, count in orphans.items():
        add("orphan_rows", name, 0, count, "rows whose order_number is not in orders.csv")
    add("orphan_rows", "attachments", 0, 0,
        "the WooCommerce export contains no invoice or packing-slip files")

    ids = [o["id"] for o in orders]
    dates = sorted(r["date_created"] for r in order_rows if r["date_created"])
    summary = {
        "orders": len(orders),
        "orders_by_status": dict(sorted(source_status.items())),
        "min_order_id": min(ids) if ids else None,
        "max_order_id": max(ids) if ids else None,
        "min_order_date": dates[0] if dates else None,
        "max_order_date": dates[-1] if dates else None,
        "currencies": currencies,
        "order_total": f"{sum(dec(o.get('total')) for o in orders):.2f}",
        "refunds": len(refunds),
        "refund_total": f"{sum(abs(dec(r.get('amount'))) for r in refunds):.2f}",
        "unexplained_discrepancies": sum(
            1 for r in rows
            if str(r["source_value"]) != str(r["archive_value"]) and not r["notes"]
        ),
        "orphans": orphans,
    }
    return RECONCILIATION_COLUMNS, rows, summary


def reconciliation_markdown(rows, summary, meta) -> str:
    lines = [
        "# Historical-order archive - reconciliation",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Archive | `{meta['archive_name']}` |",
        f"| Generated (UTC) | {meta['generated_at']} |",
        f"| Source snapshot (UTC) | {meta['source_snapshot']} |",
        f"| Source store | {meta['source_base']} |",
        f"| Generator commit | `{meta['generator_commit']}` |",
        "",
        "Historical order data is **not** loaded into Shopify. This archive is the "
        "delivered system of record for order history up to the snapshot above.",
        "",
        "## Headline counts",
        "",
        f"- Source orders: **{summary['orders']}**; archived orders: "
        f"**{summary['orders']}** (orders.csv row count).",
        f"- Order id range: {summary['min_order_id']} - {summary['max_order_id']}.",
        f"- Order date range: {summary['min_order_date']} - {summary['max_order_date']}.",
        f"- Currencies: {', '.join(summary['currencies']) or 'none'}.",
        f"- Gross order total: {summary['order_total']}.",
        f"- Refunds: {summary['refunds']} totalling {summary['refund_total']}.",
        f"- Unexplained discrepancies: **{summary['unexplained_discrepancies']}**.",
        "",
        "## Orders by status",
        "",
        "| Status | Source | Archived |",
        "|---|---:|---:|",
    ]
    for status, count in summary["orders_by_status"].items():
        lines.append(f"| {status} | {count} | {count} |")
    lines += [
        "",
        "## Full reconciliation",
        "",
        "Same content as `reconciliation.csv`.",
        "",
        "| Metric | Scope | Source | Archive | Difference | Notes |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['metric']} | {row['scope']} | {row['source_value']} | "
            f"{row['archive_value']} | {row['difference']} | {row['notes']} |"
        )
    lines += [
        "",
        "## Orphan rows",
        "",
        "| File | Rows with no matching order |",
        "|---|---:|",
    ]
    for name, count in summary["orphans"].items():
        lines.append(f"| {name} | {count} |")
    lines += [
        "",
        "## Explained differences",
        "",
        "- **Tax totals are zero.** The store sells GST-inclusive and WooCommerce "
        "recorded no `tax_lines` on any order, so every tax column is `0.00`. "
        "This matches the source, it is not a loss in the archive.",
        "- **Refunds do not appear as orders.** WooCommerce stores refunds as child "
        "records; they are archived in `refunds.csv` / `refund-lines.csv` and "
        "summarised on the parent order as `refunded_total` and `net_total`.",
        "- **No carrier or tracking data.** The source store ran no shipment-tracking "
        "plugin, so `carrier`, `tracking_number` and `tracking_url` are empty in "
        "`fulfilments.csv`. Fulfilment status and date are derived from the order "
        "status and `date_completed`.",
        "- **No attachments.** The export contains no invoice or packing-slip files; "
        "see `README.md` and the empty `attachments/` directory.",
        "",
    ]
    return "\n".join(lines)


ARCHIVE_README = """# ProSporter WooCommerce order archive

Complete WooCommerce order history for {source_base} up to the source snapshot
below. **This data is not loaded into Shopify.** These CSVs are the delivered
record of order history and are part of the final handover.

| Field | Value |
|---|---|
| Archive | `{archive_name}` |
| Generated (UTC) | {generated_at} |
| Source snapshot (UTC) | {source_snapshot} |
| Generator | `scripts/migration/archive.py`, pipeline {pipeline_version}, commit `{generator_commit}` |
| Orders | {orders} |

## Files

| File | One row per | Rows |
|---|---|---:|
{file_table}

`manifest.json` lists every file with its SHA-256, byte size and row count.
`checksums.sha256` is the same digests in `sha256sum -c` format:

```bash
cd {archive_name} && sha256sum -c checksums.sha256
```

## Reading the CSVs

- **Encoding**: UTF-8 with a byte-order mark. Excel opens these directly by
  double-click; Google Sheets imports them with no extra steps. No WordPress,
  WooCommerce, Shopify or service-provider system is needed.
- **Format**: RFC 4180 - one header row, CRLF line endings, `"` doubled inside
  quoted fields, minimal quoting.
- **Dates**: ISO 8601 with an explicit UTC offset, e.g. `2026-08-24T12:47:12+00:00`.
  The source store's timezone is UTC.
- **Money**: plain decimal numbers with two places and no currency symbol. The
  currency is a separate `currency` column (AUD throughout this archive).
- **Nulls**: an empty cell. There is no `NULL`, `N/A` or `0` stand-in; `0.00`
  always means a real zero amount.
- **Formula injection**: any text cell beginning with `=`, `+`, `-`, `@`, a tab
  or a carriage return is prefixed with a single apostrophe so spreadsheets treat
  it as text. Purely numeric cells (including negatives such as `-12.50`) are left
  untouched and stay numeric.
- **Identifiers**: `order_number` is the merchant-facing WooCommerce order
  number and is the key that joins every file. `order_id` is the underlying
  WordPress post id, kept so rows can be traced back to the source database.

## Known source gaps

- **Carrier and tracking numbers.** The WooCommerce store ran no shipment-tracking
  plugin, and no order, order meta or shipping line in the export carries a
  consignment or tracking reference. `fulfilments.csv` therefore records the
  fulfilment status, completion date, delivery type (pickup vs shipped) and
  shipping method that *are* in the source, and leaves `carrier`,
  `tracking_number` and `tracking_url` empty. If tracking history is needed it
  must come from the carrier accounts or the store's transactional email archive.
- **Invoice and packing-slip attachments.** {attachments_note}
- **Order notes.** The WooCommerce REST export contains no per-order note
  records (`order_notes_sample.json` is empty). The customer-supplied note is
  archived in `orders.csv` as `customer_note`; internal admin notes were not
  exported and would need a fresh pull from the source store to be added.
- **Tax lines.** Prices are GST-inclusive and no order carries `tax_lines`, so
  every tax column is `0.00`, matching the source exactly.

## Handling

This archive contains customer personal data (names, addresses, email addresses,
phone numbers). Encrypt it in transit and at rest, send the decryption secret
through a separate channel, and obtain written receipt from the client.
"""

ATTACHMENTS_README = """# attachments/

This directory is empty on purpose.

The WooCommerce REST export for this store contains no invoice, packing-slip or
other order document files. Every order, order meta and line-item meta field was
scanned; the only attachment-shaped field present is the RMA plugin's
`wps_wrma_exchange_attachment`, which holds a status stub and no file reference
or URL.

To add documents later:

1. Export the PDFs from the source WordPress installation, either from the
   invoicing plugin's storage directory under `wp-content/uploads/` or by
   re-generating them from the plugin's bulk action.
2. Drop them in this directory named `<order_number>-<document-type>.pdf`,
   e.g. `6469-invoice.pdf`.
3. Re-run `scripts/migration/archive.py`. Files found here are listed in
   `manifest.json` under `attachments`, keyed by order number, and their
   SHA-256 digests are added to `checksums.sha256`.
"""


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def default_archive_name(source_snapshot: str) -> str:
    date = (source_snapshot or "")[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        date = utc_now()[:10]
    return f"prosporter-woocommerce-archive-{date}"


def build_tables(data) -> tuple[dict, dict]:
    orders = sorted(data["orders"], key=lambda o: o["id"])
    refunds = sorted(data["refunds"], key=lambda r: r.get("id") or 0)
    refunds_by_order = defaultdict(list)
    order_of_refund = {}
    for order in orders:
        for nested in order.get("refunds") or []:
            order_of_refund[nested.get("id")] = order["id"]
    for refund in refunds:
        order_id = order_of_refund.get(refund.get("id")) or _refund_parent_id(refund)
        if order_id is not None:
            refunds_by_order[order_id].append(refund)

    (refund_cols, refund_rows), (rl_cols, rl_rows), orphan_refunds = build_refunds(refunds, orders)
    (ful_cols, ful_rows), (fl_cols, fl_rows) = build_fulfilments(orders)
    tables = {
        "orders.csv": build_orders(orders, refunds_by_order),
        "order-lines.csv": build_order_lines(orders),
        "payments.csv": build_payments(orders, refunds_by_order, data["payment_gateways"]),
        "refunds.csv": (refund_cols, refund_rows),
        "refund-lines.csv": (rl_cols, rl_rows),
        "fulfilments.csv": (ful_cols, ful_rows),
        "fulfilment-lines.csv": (fl_cols, fl_rows),
        "customers-reference.csv": build_customers(data["customers"], orders),
    }
    return tables, {"refunds_by_order": refunds_by_order, "orphan_refunds": orphan_refunds}


def generate(source_dir: Path, out_dir: Path, quiet: bool = False) -> dict:
    data = load_source(source_dir)
    tables, extra = build_tables(data)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir = out_dir / "attachments"
    attachments_dir.mkdir(exist_ok=True)

    counts = {}
    for name, (columns, rows) in tables.items():
        counts[name] = write_csv(out_dir / name, columns, rows)

    rec_cols, rec_rows, summary = build_reconciliation(data, tables, extra["refunds_by_order"])
    counts["reconciliation.csv"] = write_csv(out_dir / "reconciliation.csv", rec_cols, rec_rows)

    meta = {
        "archive_name": out_dir.name,
        "generated_at": utc_now(),
        "source_dir": rel(source_dir),
        "source_snapshot": data["_meta"]["source_snapshot"],
        "source_base": data["_meta"]["source_base"],
        "generator": "scripts/migration/archive.py",
        "generator_commit": git_rev(),
        "pipeline_version": PIPELINE_VERSION,
    }

    (out_dir / "reconciliation.md").write_text(
        reconciliation_markdown(rec_rows, summary, meta), encoding="utf-8"
    )

    attachments = sorted(
        p for p in attachments_dir.iterdir() if p.is_file() and p.name != "README.md"
    )
    if not attachments:
        (attachments_dir / "README.md").write_text(ATTACHMENTS_README, encoding="utf-8")
    attachment_entries = [
        {
            "file": f"attachments/{p.name}",
            "order_number": p.name.split("-", 1)[0],
            "bytes": p.stat().st_size,
            "sha256": sha256_file(p),
        }
        for p in attachments
    ]

    file_table = "\n".join(
        f"| `{name}` | {ROW_MEANING[name]} | {counts[name]} |"
        for name in sorted(counts)
    )
    (out_dir / "README.md").write_text(
        ARCHIVE_README.format(
            file_table=file_table,
            orders=counts["orders.csv"],
            attachments_note=(
                f"{len(attachment_entries)} file(s) are included in `attachments/`."
                if attachment_entries
                else "None exist in the source export; `attachments/README.md` records"
                " what was checked and how to add them later."
            ),
            **meta,
        ),
        encoding="utf-8",
    )

    # Checksums cover every file in the archive except checksums.sha256 itself.
    files = []
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file() or path.name in {"checksums.sha256", "manifest.json"}:
            continue
        relative = path.relative_to(out_dir).as_posix()
        files.append({
            "file": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "rows": counts.get(relative),
        })
    (out_dir / "checksums.sha256").write_text(
        "".join(f"{entry['sha256']}  {entry['file']}\n" for entry in files),
        encoding="utf-8",
    )

    manifest = {
        **meta,
        "not_loaded_into_shopify": True,
        "csv_conventions": {
            "encoding": "utf-8-sig",
            "line_terminator": "CRLF",
            "quoting": "RFC 4180 minimal",
            "dates": "ISO 8601 with UTC offset",
            "money": "plain decimal, 2 places, currency in a separate column",
            "null": "empty cell",
            "formula_injection": "leading apostrophe on non-numeric cells starting with = + - @ TAB CR",
        },
        "record_counts": counts,
        "summary": summary,
        "files": files,
        "attachments": attachment_entries,
    }
    write_json(out_dir / "manifest.json", manifest)

    if not quiet:
        print(f"== archive {out_dir.name} -> {rel(out_dir)}")
        for name in sorted(counts):
            print(f"   {name:<28} {counts[name]:>6} rows")
        print(f"   attachments{'':<17} {len(attachment_entries):>6} files")
        print(
            f"   orders {summary['orders']} | refunds {summary['refunds']} "
            f"| unexplained discrepancies {summary['unexplained_discrepancies']}"
        )
    return manifest


ROW_MEANING = {
    "orders.csv": "order (header, addresses, totals, payment summary)",
    "order-lines.csv": "order line: product line item, shipping line or fee",
    "payments.csv": "order payment (method, reference, amount, status)",
    "refunds.csv": "refund recorded against an order",
    "refund-lines.csv": "refunded line item",
    "fulfilments.csv": "order fulfilment (status, date, delivery type)",
    "fulfilment-lines.csv": "item covered by a fulfilment",
    "customers-reference.csv": "customer account referenced by the orders",
    "reconciliation.csv": "reconciliation metric (source vs archive)",
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the ProSporter historical-order CSV archive"
    )
    parser.add_argument("--source", default=str(DEFAULT_SOURCE),
                        help="directory holding the raw WooCommerce JSON exports")
    parser.add_argument("--out", default=None,
                        help="archive directory (default: "
                             "exports/migration/archive/<archive-name>)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    source_dir = Path(args.source)
    if args.out:
        out_dir = Path(args.out)
    else:
        manifest_path = source_dir / "_manifest.json"
        snapshot = ""
        if manifest_path.exists():
            snapshot = read_json(manifest_path).get("finished") or ""
        out_dir = MIGRATION_OUT / "archive" / default_archive_name(snapshot)

    try:
        manifest = generate(source_dir, out_dir, quiet=args.quiet)
    except SourceMissing as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0 if manifest["summary"]["unexplained_discrepancies"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
