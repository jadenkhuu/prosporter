#!/usr/bin/env python3
"""Shared helpers for the ProSporter WooCommerce -> Shopify migration pipeline.

Python 3 standard library only. Everything here must be deterministic: the same
inputs have to produce byte-identical outputs so that reruns can be diffed.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# Pinned per the execution plan (section 5.2) and AGENTS.md.
SHOPIFY_API_VERSION = "2026-07"
PIPELINE_VERSION = "1.0.0"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "exports"
MIGRATION_OUT = ROOT / "exports" / "migration"
DEFAULT_STORE = MIGRATION_OUT / "fake-store"
DOCS_OUT = ROOT / "docs" / "migration"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The record types the transform stage emits, in load order.
RECORD_TYPES = [
    "metafield_definitions",
    "collections",
    "products",
    "variants",
    "media",
    "metafields",
    "pages",
    "articles",
    "customers",
    "discounts",
    "id_map",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_rev() -> str:
    """Current commit, or 'unknown' outside a git checkout."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # pragma: no cover - environment dependent
        return "unknown"


def rel(path) -> str:
    """Repo-relative string for paths inside the checkout (keeps reports portable)."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except (ValueError, OSError):
        return str(path)


def read_json(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")


def write_jsonl(path: Path, rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_jsonl(path: Path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def checksum(obj) -> str:
    """Stable SHA-256 of any JSON-serialisable value."""
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clean_text(value) -> str:
    """Unescape WordPress HTML entities and collapse whitespace."""
    if value is None:
        return ""
    if isinstance(value, dict):  # WP {"rendered": ...} shapes
        value = value.get("rendered") or value.get("raw") or ""
    return html.unescape(str(value)).strip()


def slugify(value: str) -> str:
    value = clean_text(value)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "untitled"


def to_decimal_string(value) -> str | None:
    """Woo money strings -> a plain decimal string, or None when absent."""
    if value in (None, "", False):
        return None
    try:
        text = str(value).strip().replace(",", "")
        number = float(text)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return f"{number:.2f}"


def kilograms_to_grams(value) -> int | None:
    """Woo stores weight in the shop unit (kg for this store); Shopify wants grams."""
    if value in (None, "", False):
        return None
    try:
        return int(round(float(str(value).strip()) * 1000))
    except (TypeError, ValueError):
        return None


def meta_value(meta_data, key):
    for entry in meta_data or []:
        if entry.get("key") == key:
            return entry.get("value")
    return None
