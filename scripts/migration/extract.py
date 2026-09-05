#!/usr/bin/env python3
"""Stage 1 - extract.

Reads the raw WooCommerce/WordPress JSON exports from disk and validates that
every entity the pipeline needs is present. No network access: the exports were
produced once by scripts/audit/woo_audit.py and are treated as an immutable
snapshot. Original files under exports/ are never written to.
"""
from __future__ import annotations

from pathlib import Path

from common import read_json

# name -> required?
SOURCE_FILES = {
    "products": True,
    "variations": True,
    "product_categories": True,
    "product_tags": True,
    "product_brands": False,
    "product_attributes": False,
    "product_attribute_terms": False,
    "customers": True,
    "coupons": True,
    "pages": True,
    "posts": True,
    "media": True,
    "media_head": False,
    "shipping_zones": False,
    "tax_rates": False,
}


class SourceMissing(RuntimeError):
    pass


def load_source(source_dir: Path) -> dict:
    """Return {name: parsed json} plus a `_meta` block describing the snapshot."""
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
            data[name] = [] if name != "product_attribute_terms" else {}
    if missing:
        raise SourceMissing(
            "missing required export files in "
            f"{source_dir}: {', '.join(sorted(missing))}"
        )

    manifest_path = source_dir / "_manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    snapshot = manifest.get("finished") or manifest.get("started") or "unknown"

    data["_meta"] = {
        "source_dir": str(source_dir),
        "source_snapshot": snapshot,
        "source_base": manifest.get("base", "unknown"),
        "counts": {
            name: len(value)
            for name, value in data.items()
            if name != "_meta" and isinstance(value, (list, dict))
        },
    }
    return data


def summarize(data: dict) -> dict:
    """Counts used by the reconciliation stage as the source side of truth."""
    products = data["products"]
    variations = data["variations"]
    return {
        "source_snapshot": data["_meta"]["source_snapshot"],
        "products_total": len(products),
        "products_by_status": _tally(p.get("status") for p in products),
        "products_by_type": _tally(p.get("type") for p in products),
        "variations_total": len(variations),
        "categories": len(data["product_categories"]),
        "tags": len(data["product_tags"]),
        "pages_total": len(data["pages"]),
        "posts_total": len(data["posts"]),
        "media_total": len(data["media"]),
        "coupons_total": len(data["coupons"]),
        "customers_total": len(data["customers"]),
        "customers_by_role": _tally(c.get("role") for c in data["customers"]),
    }


def _tally(values) -> dict:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
