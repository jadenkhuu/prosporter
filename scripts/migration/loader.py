#!/usr/bin/env python3
"""Stage 3 - load.

Two targets share one interface:

  * ``FakeShopifyTarget``   - file-backed dry-run store under exports/migration/fake-store/.
    It assigns stable ``gid://shopify/...`` ids, persists ``mapping.json`` keyed by
    source id / SKU / handle, and on rerun UPDATES existing records rather than
    creating duplicates.
  * ``ShopifyAdminTarget``  - deliberate stub. There is no Shopify store yet, so
    every method raises NotImplementedError and names the Admin API mutation the
    real implementation must call.

The load order follows execution plan, workstream 3, "Load order".
"""
from __future__ import annotations

from pathlib import Path

from common import SHOPIFY_API_VERSION, checksum, read_json, write_json
from errors import OWNER_AGENCY

STAGE = "load"

# (record type, Shopify resource, key field used for identity)
LOAD_ORDER = [
    ("metafield_definitions", "MetafieldDefinition", "definition_key"),
    ("collections", "Collection", "handle"),
    ("products", "Product", "handle"),
    ("variants", "ProductVariant", "woo_variation_id"),
    ("media", "MediaImage", "media_key"),
    ("variants_inventory", "InventoryItem", "woo_variation_id"),
    ("collection_membership", "CollectionMembership", "handle"),
    ("metafields", "Metafield", "metafield_key"),
    ("pages", "Page", "handle"),
    ("articles", "Article", "handle"),
    ("customers", "Customer", "email"),
    ("discounts", "DiscountCodeNode", "code"),
]


def identity_key(record_type: str, record: dict) -> str:
    """Stable, source-derived identity for upserts."""
    if record_type == "metafield_definitions":
        return f"{record['owner_type']}:{record['namespace']}.{record['key']}"
    if record_type == "metafields":
        return f"{record['owner_type']}:{record['owner_handle']}:{record['namespace']}.{record['key']}"
    if record_type == "media":
        return f"{record['product_handle']}:{record['original_url']}"
    if record_type == "variants":
        # SKUs are not unique in the source (6 SKUs are shared by up to 19
        # variations), so identity is the WooCommerce variation id. The SKU is
        # still indexed in mapping.json.
        return f"woo:{record['source']['woo_id']}"
    if record_type == "customers":
        return record["email"]
    if record_type == "discounts":
        return record["code"]
    return record["handle"]


class Target:
    """Interface a real Shopify Admin implementation must satisfy.

    ``upsert(resource, key, payload)`` must be idempotent: the same key with the
    same payload must not create a second object and must report "unchanged".
    """

    name = "abstract"

    def upsert(self, resource: str, key: str, payload: dict) -> tuple[str, str]:
        """Return (destination_id, one of created|updated|unchanged)."""
        raise NotImplementedError

    def finish(self) -> None:
        raise NotImplementedError

    def counts(self) -> dict:
        raise NotImplementedError


class FakeShopifyTarget(Target):
    """File-backed fake Shopify Admin. No network calls anywhere."""

    name = "fake"

    def __init__(self, store_dir: Path):
        self.store_dir = Path(store_dir)
        self.store_path = self.store_dir / "store.json"
        self.mapping_path = self.store_dir / "mapping.json"
        self.state = (
            read_json(self.store_path)
            if self.store_path.exists()
            else {"api_version": SHOPIFY_API_VERSION, "counters": {}, "objects": {}}
        )
        self.state.setdefault("counters", {})
        self.state.setdefault("objects", {})
        self.mapping = read_json(self.mapping_path) if self.mapping_path.exists() else {}
        self.stats = {"created": 0, "updated": 0, "unchanged": 0}
        self.per_resource = {}
        self.indexes: dict[str, dict] = {}

    def index(self, name: str, key, gid: str) -> None:
        """Secondary lookup (e.g. SKU -> gid) recorded in mapping.json."""
        if key not in (None, ""):
            self.indexes.setdefault(name, {}).setdefault(str(key), []).append(gid)

    def _next_gid(self, resource: str) -> str:
        counter = self.state["counters"].get(resource, 0) + 1
        self.state["counters"][resource] = counter
        # Namespaced numeric ids so they look like real Shopify gids but never
        # collide between resources.
        return f"gid://shopify/{resource}/{counter:010d}"

    def upsert(self, resource: str, key: str, payload: dict):
        objects = self.state["objects"].setdefault(resource, {})
        digest = checksum(payload)
        existing = objects.get(key)
        if existing is None:
            gid = self._next_gid(resource)
            objects[key] = {"id": gid, "checksum": digest, "payload": payload}
            outcome = "created"
        elif existing["checksum"] == digest:
            gid = existing["id"]
            outcome = "unchanged"
        else:
            gid = existing["id"]
            objects[key] = {"id": gid, "checksum": digest, "payload": payload}
            outcome = "updated"
        self.stats[outcome] += 1
        bucket = self.per_resource.setdefault(
            resource, {"created": 0, "updated": 0, "unchanged": 0}
        )
        bucket[outcome] += 1
        self.mapping.setdefault(resource, {})[key] = gid
        return gid, outcome

    def finish(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        write_json(self.store_path, self.state)
        write_json(self.mapping_path, {
            "api_version": SHOPIFY_API_VERSION,
            "target": self.name,
            "keys": "resource -> source key (handle | woo:<id> | email | code | composite) -> gid",
            "resources": self.mapping,
            "indexes": {
                name: {k: sorted(set(v)) for k, v in sorted(entries.items())}
                for name, entries in sorted(self.indexes.items())
            },
        })

    def counts(self) -> dict:
        return {
            resource: len(objects)
            for resource, objects in sorted(self.state["objects"].items())
        }

    def objects(self, resource: str) -> dict:
        return self.state["objects"].get(resource, {})

    def snapshot(self) -> dict:
        """{resource: {key: (gid, checksum)}} - the input to the idempotency diff."""
        return {
            resource: {k: [v["id"], v["checksum"]] for k, v in objects.items()}
            for resource, objects in self.state["objects"].items()
        }


class ShopifyAdminTarget(Target):
    """STUB - real Shopify Admin GraphQL target.

    Not implemented yet: CLNT-305's dry run must never touch a live endpoint.
    The store now exists and ``shopify_admin.AdminClient`` provides authenticated
    GraphQL access; implement each method against Admin API 2026-07 using these
    mutations:

      metafield_definitions -> metafieldDefinitionCreate
      collections           -> collectionCreate / collectionUpdate
      products              -> productSet (creates or updates by handle, options included)
      variants              -> productVariantsBulkCreate / productVariantsBulkUpdate
      media                 -> fileCreate, then productCreateMedia / productVariantAppendMedia
      inventory             -> inventorySetQuantities / inventoryItemUpdate
      collection membership -> collectionAddProducts / collectionRemoveProducts
      metafields            -> metafieldsSet
      pages                 -> pageCreate / pageUpdate
      articles              -> articleCreate / articleUpdate
      customers             -> customerCreate / customerUpdate
      discounts             -> discountCodeBasicCreate / discountCodeBasicUpdate
      redirects             -> urlRedirectCreate (owned by the redirects workstream)

    For the products/variants/media stages use bulkOperationRunMutation with a
    JSONL staged upload; keep the per-record upsert semantics of ``upsert`` by
    resolving existing destination ids from mapping.json before the bulk run.
    """

    name = "shopify-admin"

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError(
            "ShopifyAdminTarget is a stub (CLNT-305 is a dry run). Implement against "
            "Admin API 2026-07 via shopify_admin.AdminClient using productSet, "
            "productVariantsBulkCreate/Update, fileCreate, collectionCreate/"
            "collectionAddProducts, metafieldsSet, customerCreate, "
            "discountCodeBasicCreate, pageCreate and articleCreate."
        )


def build_target(name: str, store_dir: Path) -> Target:
    if name == "fake":
        return FakeShopifyTarget(store_dir)
    if name in ("shopify", "shopify-admin"):
        return ShopifyAdminTarget(store_dir)
    raise ValueError(f"unknown target {name!r}")


def load(records: dict, target: Target, exc) -> dict:
    """Apply every record to the target in the plan's load order."""
    results = []
    for record_type, resource, _key in LOAD_ORDER:
        for payload, key in _payloads(record_type, records, exc):
            if payload is None:
                continue
            gid, outcome = target.upsert(resource, key, payload)
            _index(target, record_type, payload, gid)
            results.append({
                "record_type": record_type,
                "resource": resource,
                "key": key,
                "destination_id": gid,
                "outcome": outcome,
            })
    target.finish()
    return {
        "results": results,
        "stats": dict(target.stats) if hasattr(target, "stats") else {},
        "per_resource": getattr(target, "per_resource", {}),
        "object_counts": target.counts(),
    }


def _index(target, record_type, payload, gid):
    """Keep the mapping manifest addressable by SKU and by source id too."""
    if not hasattr(target, "index"):
        return
    source_id = (payload.get("source") or {}).get("woo_id")
    if record_type in ("variants", "variants_inventory"):
        target.index("variant_sku", payload.get("sku"), gid)
        target.index("variant_woo_id", source_id, gid)
    elif record_type == "products":
        target.index("product_woo_id", source_id, gid)
    elif record_type in ("pages", "articles"):
        target.index(f"{record_type[:-1]}_woo_id", source_id, gid)
    elif record_type == "customers":
        # Never index by email: mapping.json lives under exports/ but the source
        # id is enough and keeps the manifest free of personal data.
        target.index("customer_woo_id", source_id, gid)


def _payloads(record_type, records, exc):
    """Yield (payload, identity key) pairs, skipping held records."""
    if record_type == "variants_inventory":
        for variant in records["variants"]:
            if variant.get("held"):
                continue
            yield (
                {
                    "sku": variant["sku"],
                    "tracked": variant["inventory_management"] == "SHOPIFY",
                    "quantity": variant["inventory_quantity"],
                    "policy": variant["inventory_policy"],
                    "requires_shipping": variant["requires_shipping"],
                    "source": variant["source"],
                },
                f"woo:{variant['source']['woo_id']}",
            )
        return
    if record_type == "collection_membership":
        for collection in records["collections"]:
            yield (
                {"handle": collection["handle"], "product_handles": collection["product_handles"]},
                collection["handle"],
            )
        return

    for record in records.get(record_type, []):
        if record.get("held"):
            exc.add(
                record_type=record_type.rstrip("s"),
                record_id=record.get("source", {}).get("woo_id"),
                record_ref=identity_key(record_type, record),
                stage=STAGE, severity="high", code="record_held_from_load",
                message="record has an unresolved blocking exception and was not loaded",
                owner=OWNER_AGENCY, retry_status="needs-decision",
                detail={"reasons": record.get("held_reasons", [])},
            )
            continue
        payload = {k: v for k, v in record.items() if k not in ("held", "held_reasons")}
        yield payload, identity_key(record_type, record)
