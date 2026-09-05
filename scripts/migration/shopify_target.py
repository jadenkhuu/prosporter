#!/usr/bin/env python3
"""Real Shopify Admin GraphQL load target (Admin API 2026-07).

``ShopifyAdminTarget`` implements ``loader.Target`` against the client store
using ``shopify_admin.AdminClient``. It keeps the same file-backed ledger as the
fake target (``store.json`` + ``mapping.json`` under the store directory) so a
rerun with an unchanged payload makes **no API call** and reports ``unchanged``,
and a changed payload updates the existing Shopify object instead of creating a
second one.

When the ledger does not know a key (first run, or a fresh checkout against a
store that already holds migrated objects) every resource is first looked up by
its natural key on the store (handle, code, email, ``migration.woo_id``
metafield, option values) before anything is created.

Failures are per record: an Admin API error is recorded and the upsert returns
``(None, "failed")`` so the load continues and the reconcile stage names the
gap. Nothing here publishes anything: products are created as DRAFT and are not
added to any sales channel.

2026-07 specifics that differ from older Admin API versions:
  * there is no ``collectionAddProducts``; membership is set from the product
    side with ``productUpdate(collectionsToJoin / collectionsToLeave)``.
  * ``CustomerInput`` has no ``addresses``; use ``customerAddressCreate``.
  * ``DiscountCodeBasicInput`` uses ``context: {all: ALL}`` instead of
    ``customerSelection``.
  * product media is added with ``productUpdate(media: [...])`` and variant
    images with ``productVariantsBulkUpdate(variants: [{id, mediaId}])``.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from common import SHOPIFY_API_VERSION, checksum, read_json, write_json
from loader import FakeShopifyTarget
from shopify_admin import AdminClient, ShopifyAdminError

# Source timestamps have no zone; the WordPress site runs on Australian Eastern
# time. Offsets are only cosmetic for publish dates.
SOURCE_TZ_OFFSET = "+10:00"
MEDIA_READY_WAIT_SECONDS = 90


def _dt(value):
    if not value:
        return None
    value = str(value)
    if value.endswith("Z") or "+" in value[10:] or "-" in value[10:]:
        return value
    return value + SOURCE_TZ_OFFSET


def _seo_metafields(seo: dict | None) -> list[dict]:
    """Pages/articles carry SEO through the legacy ``global`` metafields."""
    out = []
    if seo and seo.get("title"):
        out.append({"namespace": "global", "key": "title_tag",
                    "type": "single_line_text_field", "value": seo["title"]})
    if seo and seo.get("description"):
        out.append({"namespace": "global", "key": "description_tag",
                    "type": "multi_line_text_field", "value": seo["description"]})
    return out


def _metafield_value(mtype: str, value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _quote(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


class ShopifyAdminTarget(FakeShopifyTarget):
    """Live Admin API target with the fake target's ledger semantics."""

    name = "shopify-admin"

    def __init__(self, store_dir: Path, client: AdminClient | None = None):
        super().__init__(store_dir)
        self.client = client or AdminClient()
        self.state.setdefault("aux", {})
        self.aux = self.state["aux"]
        self.aux.setdefault("variant_inventory_item", {})  # variant gid -> inventory item gid
        self.aux.setdefault("created_blogs", {})            # handle -> gid (only blogs we created)
        self.stats["failed"] = 0
        self.failures: list[dict] = []
        self.deferred_variant_media: list[tuple[str, str, str, str]] = []  # (product, variant, media, key)
        self._variant_cache: dict[str, list[dict]] = {}
        self._touched_products: set[str] = set()  # products whose variants this run wrote
        self._media_cache: dict[str, set[str]] = {}
        self._location_id: str | None = None
        self.store_domain = self.client.domain
        if self.state.get("store") not in (None, self.store_domain):
            raise ShopifyAdminError(
                f"ledger {self.store_path} belongs to {self.state['store']}, not {self.store_domain}"
            )
        self.state["store"] = self.store_domain

    # ------------------------------------------------------------------ ledger
    def upsert(self, resource: str, key: str, payload: dict):
        objects = self.state["objects"].setdefault(resource, {})
        digest = checksum(payload)
        existing = objects.get(key)
        if existing is not None and existing["checksum"] == digest:
            outcome = "unchanged"
            gid = existing["id"]
        else:
            try:
                gid = self._apply(resource, key, payload, existing["id"] if existing else None)
            except ShopifyAdminError as exc:
                self._fail(resource, key, str(exc))
                return None, "failed"
            if gid is None:
                self._fail(resource, key, "no destination id returned")
                return None, "failed"
            outcome = "created" if existing is None else "updated"
            objects[key] = {"id": gid, "checksum": digest, "payload": payload}
            # Persist after every write so an interrupted run never repeats a create.
            self._flush()
        self.stats[outcome] += 1
        bucket = self.per_resource.setdefault(
            resource, {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
        )
        bucket[outcome] += 1
        self.mapping.setdefault(resource, {})[key] = gid
        return gid, outcome

    def _fail(self, resource, key, message):
        self.stats["failed"] += 1
        bucket = self.per_resource.setdefault(
            resource, {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
        )
        bucket["failed"] += 1
        self.failures.append({"resource": resource, "key": key, "message": message[:500]})

    def _flush(self):
        self.store_dir.mkdir(parents=True, exist_ok=True)
        write_json(self.store_path, self.state)

    def finish(self) -> None:
        self._prune_placeholder_variants()
        self._attach_deferred_variant_media()
        super().finish()
        write_json(self.store_dir / "failures.json", {
            "store": self.store_domain,
            "api_version": SHOPIFY_API_VERSION,
            "count": len(self.failures),
            "failures": self.failures,
        })

    def gid(self, resource: str, key: str):
        entry = self.state["objects"].get(resource, {}).get(key)
        return entry["id"] if entry else None

    # ---------------------------------------------------------------- dispatch
    def _apply(self, resource, key, payload, existing_gid):
        handler = {
            "MetafieldDefinition": self._metafield_definition,
            "Collection": self._collection,
            "Product": self._product,
            "ProductVariant": self._variant,
            "MediaImage": self._media,
            "InventoryItem": self._inventory,
            "CollectionMembership": self._membership,
            "Metafield": self._metafield,
            "Page": self._page,
            "Article": self._article,
            "Customer": self._customer,
            "DiscountCodeNode": self._discount,
        }.get(resource)
        if handler is None:
            raise ShopifyAdminError(f"no live handler for resource {resource}")
        return handler(key, payload, existing_gid)

    # ------------------------------------------------------------ definitions
    def _metafield_definition(self, key, p, existing):
        if existing is None:
            data = self.client.graphql(
                "query($ns:String,$key:String,$owner:MetafieldOwnerType!){"
                " metafieldDefinitions(first:1, ownerType:$owner, namespace:$ns, key:$key){ nodes{ id } } }",
                {"ns": p["namespace"], "key": p["key"], "owner": p["owner_type"]},
            )
            nodes = data["metafieldDefinitions"]["nodes"]
            existing = nodes[0]["id"] if nodes else None
        storefront = "PUBLIC_READ" if p["namespace"] == "prosporter" else "NONE"
        if existing:
            self.client.mutate(
                "mutation($d:MetafieldDefinitionUpdateInput!){ metafieldDefinitionUpdate(definition:$d){"
                " updatedDefinition{ id } userErrors{ field message } } }",
                {"d": {"namespace": p["namespace"], "key": p["key"], "ownerType": p["owner_type"],
                       "name": p["name"], "access": {"storefront": storefront}}},
                "metafieldDefinitionUpdate",
            )
            return existing
        result = self.client.mutate(
            "mutation($d:MetafieldDefinitionInput!){ metafieldDefinitionCreate(definition:$d){"
            " createdDefinition{ id } userErrors{ field message code } } }",
            {"d": {"namespace": p["namespace"], "key": p["key"], "ownerType": p["owner_type"],
                   "name": p["name"], "type": p["type"], "access": {"storefront": storefront}}},
            "metafieldDefinitionCreate",
        )
        return result["createdDefinition"]["id"]

    # ------------------------------------------------------------- collections
    def _collection(self, key, p, existing):
        if existing is None:
            data = self.client.graphql(
                "query($h:String!){ collectionByIdentifier(identifier:{handle:$h}){ id } }", {"h": p["handle"]}
            )
            existing = (data.get("collectionByIdentifier") or {}).get("id")
        fields = {
            "handle": p["handle"],
            "title": p["title"],
            "descriptionHtml": p.get("body_html") or "",
            "seo": {"title": (p.get("seo") or {}).get("title") or None,
                    "description": (p.get("seo") or {}).get("description") or None},
        }
        if existing:
            fields["id"] = existing
            self.client.mutate(
                "mutation($c:CollectionUpdateInput!){ collectionUpdate(collection:$c){"
                " collection{ id } userErrors{ field message } } }",
                {"c": fields}, "collectionUpdate",
            )
            return existing
        result = self.client.mutate(
            "mutation($c:CollectionCreateInput!){ collectionCreate(collection:$c){"
            " collection{ id } userErrors{ field message } } }",
            {"c": fields}, "collectionCreate",
        )
        return result["collection"]["id"]

    # ---------------------------------------------------------------- products
    def _product_fields(self, p):
        return {
            "handle": p["handle"],
            "title": p["title"],
            "descriptionHtml": p.get("body_html") or "",
            "vendor": p.get("vendor") or "ProSporter",
            "productType": p.get("product_type") or "",
            "tags": p.get("tags") or [],
            "status": "DRAFT",  # never publish from the pipeline
            "seo": {"title": (p.get("seo") or {}).get("title") or None,
                    "description": (p.get("seo") or {}).get("description") or None},
            "metafields": [{"namespace": "migration", "key": "woo_id",
                            "type": "single_line_text_field",
                            "value": str((p.get("source") or {}).get("woo_id"))}],
        }

    def _collection_gids(self, handles):
        gids = []
        for handle in handles or []:
            gid = self.gid("Collection", handle)
            if gid:
                gids.append(gid)
        return gids

    def _product(self, key, p, existing):
        if existing is None:
            data = self.client.graphql(
                "query($h:String!){ productByIdentifier(identifier:{handle:$h}){ id options{ name } } }",
                {"h": p["handle"]},
            )
            found = data.get("productByIdentifier")
            existing = found["id"] if found else None
            if found:
                self._check_options(found["options"], p)
        fields = self._product_fields(p)
        joins = self._collection_gids(p.get("collections"))
        if joins:
            fields["collectionsToJoin"] = joins
        if existing:
            fields["id"] = existing
            self.client.mutate(
                "mutation($p:ProductUpdateInput!){ productUpdate(product:$p){"
                " product{ id } userErrors{ field message } } }",
                {"p": fields}, "productUpdate",
            )
            self._variant_cache.pop(existing, None)
            return existing
        options = [
            {"name": o["name"], "position": o.get("position") or i + 1,
             "values": [{"name": v} for v in o["values"]]}
            for i, o in enumerate(p.get("options") or [])
        ]
        if options:
            fields["productOptions"] = options
        result = self.client.mutate(
            "mutation($p:ProductCreateInput!){ productCreate(product:$p){"
            " product{ id } userErrors{ field message } } }",
            {"p": fields}, "productCreate",
        )
        return result["product"]["id"]

    def _check_options(self, live_options, p):
        live = [o["name"] for o in live_options]
        wanted = [o["name"] for o in (p.get("options") or [])] or ["Title"]
        if live != wanted:
            raise ShopifyAdminError(
                f"product {p['handle']} exists with options {live}, source has {wanted}; "
                "option changes need a decision (productOptionsCreate/Update)"
            )

    # ---------------------------------------------------------------- variants
    def _location(self) -> str:
        if self._location_id is None:
            data = self.client.graphql(
                "{ locations(first:10, query:\"active:true\"){ nodes{ id name fulfillsOnlineOrders } } }"
            )
            nodes = data["locations"]["nodes"]
            if not nodes:
                raise ShopifyAdminError("store has no active location")
            online = [n for n in nodes if n["fulfillsOnlineOrders"]] or nodes
            self._location_id = online[0]["id"]
        return self._location_id

    def _variants(self, product_gid: str) -> list[dict]:
        if product_gid not in self._variant_cache:
            data = self.client.graphql(
                "query($id:ID!){ product(id:$id){ variants(first:250){ nodes{ id sku"
                " selectedOptions{ name value } inventoryItem{ id }"
                " metafield(namespace:\"migration\", key:\"woo_id\"){ value } } } } }",
                {"id": product_gid},
            )
            product = data.get("product")
            if product is None:
                raise ShopifyAdminError(f"product {product_gid} no longer exists on the store")
            self._variant_cache[product_gid] = product["variants"]["nodes"]
        return self._variant_cache[product_gid]

    @staticmethod
    def _option_set(option_values):
        return frozenset((o["name"], o["value"]) for o in option_values or [])

    def _variant_input(self, p, create: bool) -> dict:
        tracked = p.get("inventory_management") == "SHOPIFY"
        inventory_item = {
            "sku": p.get("sku") or None,
            "tracked": tracked,
            "requiresShipping": bool(p.get("requires_shipping", True)),
        }
        if p.get("weight_grams") is not None:
            inventory_item["measurement"] = {
                "weight": {"value": float(p["weight_grams"]), "unit": "GRAMS"}
            }
        variant = {
            "price": p.get("price"),
            "compareAtPrice": p.get("compare_at_price"),
            "barcode": p.get("barcode") or None,
            "taxable": bool(p.get("taxable", True)),
            "inventoryPolicy": p.get("inventory_policy") or "DENY",
            "inventoryItem": inventory_item,
            "metafields": [{"namespace": "migration", "key": "woo_id",
                            "type": "single_line_text_field",
                            "value": str((p.get("source") or {}).get("woo_id"))}],
        }
        if create:
            variant["optionValues"] = [
                {"optionName": o["name"], "name": o["value"]} for o in p.get("option_values") or []
            ]
            if tracked and p.get("inventory_quantity") is not None:
                variant["inventoryQuantities"] = [
                    {"locationId": self._location(), "availableQuantity": int(p["inventory_quantity"])}
                ]
        return variant

    def _variant(self, key, p, existing):
        product_gid = self.gid("Product", p["product_handle"])
        if not product_gid:
            raise ShopifyAdminError(f"product {p['product_handle']} was not loaded; variant skipped")
        live = self._variants(product_gid)
        woo_id = str((p.get("source") or {}).get("woo_id"))
        match = None
        if existing:
            match = next((v for v in live if v["id"] == existing), None)
        if match is None:
            match = next((v for v in live if (v.get("metafield") or {}).get("value") == woo_id), None)
        if match is None:
            wanted = self._option_set(p.get("option_values"))
            match = next((v for v in live if self._option_set(v["selectedOptions"]) == wanted), None)
        if match:
            variant = self._variant_input(p, create=False)
            variant["id"] = match["id"]
            result = self.client.mutate(
                "mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){"
                " productVariantsBulkUpdate(productId:$pid, variants:$v){"
                " productVariants{ id sku inventoryItem{ id } selectedOptions{ name value } }"
                " userErrors{ field message code } } }",
                {"pid": product_gid, "v": [variant]}, "productVariantsBulkUpdate",
            )
            node = result["productVariants"][0]
        else:
            variant = self._variant_input(p, create=True)
            result = self.client.mutate(
                "mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){"
                " productVariantsBulkCreate(productId:$pid, variants:$v, strategy:DEFAULT){"
                " productVariants{ id sku inventoryItem{ id } selectedOptions{ name value } }"
                " userErrors{ field message code } } }",
                {"pid": product_gid, "v": [variant]}, "productVariantsBulkCreate",
            )
            node = result["productVariants"][0]
            node["metafield"] = {"value": woo_id}
            live.append(node)
        self.aux["variant_inventory_item"][node["id"]] = node["inventoryItem"]["id"]
        self._touched_products.add(product_gid)
        return node["id"]

    def _prune_placeholder_variants(self):
        """Drop the variant Shopify auto-creates with a product when no source
        variant claimed it (it carries no ``migration.woo_id``). A product must
        keep at least one variant, so a lone placeholder is left alone."""
        ours = {e["id"] for e in self.state["objects"].get("ProductVariant", {}).values()}
        for product_gid in sorted(self._touched_products):
            self._variant_cache.pop(product_gid, None)
            try:
                live = self._variants(product_gid)
            except ShopifyAdminError as exc:
                self._fail("ProductVariant", product_gid, f"prune check failed: {exc}")
                continue
            orphans = [v["id"] for v in live
                       if v["id"] not in ours and not (v.get("metafield") or {}).get("value")]
            if not orphans or len(orphans) == len(live):
                continue
            try:
                self.client.mutate(
                    "mutation($pid:ID!,$ids:[ID!]!){ productVariantsBulkDelete(productId:$pid, variantsIds:$ids){"
                    " product{ id } userErrors{ field message code } } }",
                    {"pid": product_gid, "ids": orphans}, "productVariantsBulkDelete",
                )
            except ShopifyAdminError as exc:
                self._fail("ProductVariant", product_gid, f"placeholder variant delete failed: {exc}")
            self._variant_cache.pop(product_gid, None)

    # ------------------------------------------------------------------- media
    def _media_ids(self, product_gid: str) -> set[str]:
        if product_gid not in self._media_cache:
            data = self.client.graphql(
                "query($id:ID!){ product(id:$id){ media(first:250){ nodes{ id } } } }", {"id": product_gid}
            )
            product = data.get("product") or {"media": {"nodes": []}}
            self._media_cache[product_gid] = {n["id"] for n in product["media"]["nodes"]}
        return self._media_cache[product_gid]

    def _media(self, key, p, existing):
        if p.get("reachable") is False:
            raise ShopifyAdminError(f"source image unreachable (HTTP {p.get('http_status')})")
        product_gid = self.gid("Product", p["product_handle"])
        if not product_gid:
            raise ShopifyAdminError(f"product {p['product_handle']} was not loaded; media skipped")
        if existing:
            # Alt text is the only mutable attribute we own; update it in place.
            if p.get("alt"):
                self.client.mutate(
                    "mutation($f:[FileUpdateInput!]!){ fileUpdate(files:$f){ files{ id } userErrors{ field message } } }",
                    {"f": [{"id": existing, "alt": p["alt"]}]}, "fileUpdate",
                )
            media_gid = existing
        else:
            before = set(self._media_ids(product_gid))
            media = {"originalSource": p["original_url"], "mediaContentType": "IMAGE"}
            if p.get("alt"):
                media["alt"] = p["alt"]
            result = self.client.mutate(
                "mutation($p:ProductUpdateInput!,$m:[CreateMediaInput!]){ productUpdate(product:$p, media:$m){"
                " product{ media(first:250){ nodes{ id } } } userErrors{ field message } } }",
                {"p": {"id": product_gid}, "m": [media]}, "productUpdate",
            )
            after = {n["id"] for n in result["product"]["media"]["nodes"]}
            new = after - before
            self._media_cache[product_gid] = after
            if len(new) != 1:
                raise ShopifyAdminError(f"expected one new media object, saw {len(new)}")
            media_gid = new.pop()
        if p.get("variant_sku"):
            variant = next(
                (v for v in self._variants(product_gid) if v.get("sku") == p["variant_sku"]), None
            )
            if variant is None:
                raise ShopifyAdminError(f"variant with sku {p['variant_sku']} not found for image")
            self.deferred_variant_media.append((product_gid, variant["id"], media_gid, key))
        return media_gid

    def _attach_deferred_variant_media(self):
        """Variant images need READY media; attach once processing has finished."""
        pending = list(self.deferred_variant_media)
        self.deferred_variant_media = []
        deadline = time.time() + MEDIA_READY_WAIT_SECONDS
        while pending:
            by_product: dict[str, list] = {}
            for item in pending:
                by_product.setdefault(item[0], []).append(item)
            still = []
            for product_gid, items in by_product.items():
                data = self.client.graphql(
                    "query($id:ID!){ product(id:$id){ media(first:250){ nodes{ id status } } } }",
                    {"id": product_gid},
                )
                status = {n["id"]: n["status"] for n in (data.get("product") or {"media": {"nodes": []}})["media"]["nodes"]}
                ready, waiting = [], []
                for item in items:
                    state = status.get(item[2])
                    if state == "READY":
                        ready.append(item)
                    elif state == "FAILED" or state is None:
                        self._fail("MediaImage", item[3], f"media {item[2]} status {state}; variant image not attached")
                    else:
                        waiting.append(item)
                if ready:
                    try:
                        self.client.mutate(
                            "mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){"
                            " productVariantsBulkUpdate(productId:$pid, variants:$v, allowPartialUpdates:true){"
                            " productVariants{ id } userErrors{ field message code } } }",
                            {"pid": product_gid,
                             "v": [{"id": vid, "mediaId": mid} for _, vid, mid, _ in ready]},
                            "productVariantsBulkUpdate",
                        )
                    except ShopifyAdminError as exc:
                        for item in ready:
                            self._fail("MediaImage", item[3], f"variant image attach failed: {exc}")
                still.extend(waiting)
            pending = still
            if pending:
                if time.time() > deadline:
                    for item in pending:
                        self._fail("MediaImage", item[3], "media still processing after wait; rerun to attach")
                    break
                time.sleep(5)

    # --------------------------------------------------------------- inventory
    def _inventory(self, key, p, existing):
        variant_gid = self.gid("ProductVariant", key)
        if not variant_gid:
            raise ShopifyAdminError(f"variant {key} was not loaded; inventory skipped")
        item_gid = self.aux["variant_inventory_item"].get(variant_gid)
        if not item_gid:
            data = self.client.graphql(
                "query($id:ID!){ productVariant(id:$id){ inventoryItem{ id } } }", {"id": variant_gid}
            )
            item_gid = ((data.get("productVariant") or {}).get("inventoryItem") or {}).get("id")
            if not item_gid:
                raise ShopifyAdminError(f"variant {variant_gid} has no inventory item")
            self.aux["variant_inventory_item"][variant_gid] = item_gid
        self.client.mutate(
            "mutation($id:ID!,$i:InventoryItemInput!){ inventoryItemUpdate(id:$id, input:$i){"
            " inventoryItem{ id } userErrors{ field message } } }",
            {"id": item_gid, "i": {"tracked": bool(p.get("tracked")),
                                   "requiresShipping": bool(p.get("requires_shipping", True))}},
            "inventoryItemUpdate",
        )
        if p.get("tracked") and p.get("quantity") is not None:
            location = self._location()
            data = self.client.graphql(
                "query($id:ID!,$loc:ID!){ inventoryItem(id:$id){ inventoryLevel(locationId:$loc){"
                " quantities(names:[\"available\"]){ quantity } } } }",
                {"id": item_gid, "loc": location},
            )
            level = (data.get("inventoryItem") or {}).get("inventoryLevel") or {}
            quantities = level.get("quantities") or [{"quantity": 0}]
            current = int(quantities[0]["quantity"])
            wanted = int(p["quantity"])
            if current != wanted:
                # 2026-07 requires the compare quantity; it makes the set safe against
                # a merchant edit between our read and write.
                # 2026-07 also demands an idempotency key on inventory writes. Derive it
                # from the exact change so a retried request can never double-apply.
                idem = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                      f"{self.store_domain}/{item_gid}/{location}/{current}->{wanted}"))
                self.client.mutate(
                    "mutation($i:InventorySetQuantitiesInput!,$k:String!){"
                    " inventorySetQuantities(input:$i) @idempotent(key:$k){"
                    " inventoryAdjustmentGroup{ id } userErrors{ field message code } } }",
                    {"i": {"name": "available", "reason": "correction",
                           "referenceDocumentUri": "gid://purpl/Migration/woocommerce",
                           "quantities": [{"inventoryItemId": item_gid, "locationId": location,
                                           "quantity": wanted, "changeFromQuantity": current}]},
                     "k": idem},
                    "inventorySetQuantities",
                )
        return item_gid

    # -------------------------------------------------------------- membership
    def _membership(self, key, p, existing):
        collection_gid = self.gid("Collection", p["handle"])
        if not collection_gid:
            raise ShopifyAdminError(f"collection {p['handle']} was not loaded")
        wanted = {self.gid("Product", h) for h in p.get("product_handles") or []}
        wanted.discard(None)
        data = self.client.graphql(
            "query($id:ID!){ collection(id:$id){ products(first:250){ nodes{ id } } } }", {"id": collection_gid}
        )
        current = {n["id"] for n in (data.get("collection") or {"products": {"nodes": []}})["products"]["nodes"]}
        for product_gid in sorted(wanted - current):
            self.client.mutate(
                "mutation($p:ProductUpdateInput!){ productUpdate(product:$p){ product{ id } userErrors{ field message } } }",
                {"p": {"id": product_gid, "collectionsToJoin": [collection_gid]}}, "productUpdate",
            )
        # Only remove products the pipeline itself placed there (never touch merchant edits).
        ours = {e["id"] for e in self.state["objects"].get("Product", {}).values()}
        for product_gid in sorted((current - wanted) & ours):
            self.client.mutate(
                "mutation($p:ProductUpdateInput!){ productUpdate(product:$p){ product{ id } userErrors{ field message } } }",
                {"p": {"id": product_gid, "collectionsToLeave": [collection_gid]}}, "productUpdate",
            )
        return collection_gid

    # -------------------------------------------------------------- metafields
    _OWNER_RESOURCE = {"PRODUCT": "Product", "COLLECTION": "Collection", "PAGE": "Page",
                       "ARTICLE": "Article", "CUSTOMER": "Customer"}

    def _metafield(self, key, p, existing):
        resource = self._OWNER_RESOURCE.get(p["owner_type"])
        owner_gid = self.gid(resource, p["owner_handle"]) if resource else None
        if not owner_gid:
            raise ShopifyAdminError(f"owner {p['owner_type']} {p['owner_handle']} was not loaded")
        result = self.client.mutate(
            "mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){"
            " metafields{ id } userErrors{ field message code } } }",
            {"m": [{"ownerId": owner_gid, "namespace": p["namespace"], "key": p["key"],
                    "type": p["type"], "value": _metafield_value(p["type"], p["value"])}]},
            "metafieldsSet",
        )
        return result["metafields"][0]["id"]

    # ------------------------------------------------------------------- pages
    def _page(self, key, p, existing):
        if existing is None:
            data = self.client.graphql(
                "query($q:String!){ pages(first:5, query:$q){ nodes{ id handle } } }",
                {"q": f"handle:{_quote(p['handle'])}"},
            )
            existing = next((n["id"] for n in data["pages"]["nodes"] if n["handle"] == p["handle"]), None)
        fields = {
            "title": p["title"],
            "handle": p["handle"],
            "body": p.get("body_html") or "",
            "isPublished": bool(p.get("published")),
            "metafields": _seo_metafields(p.get("seo")),
        }
        if p.get("published") and p.get("published_at"):
            fields["publishDate"] = _dt(p["published_at"])
        if not fields["metafields"]:
            fields.pop("metafields")
        if existing:
            self.client.mutate(
                "mutation($id:ID!,$p:PageUpdateInput!){ pageUpdate(id:$id, page:$p){ page{ id } userErrors{ field message code } } }",
                {"id": existing, "p": fields}, "pageUpdate",
            )
            return existing
        result = self.client.mutate(
            "mutation($p:PageCreateInput!){ pageCreate(page:$p){ page{ id } userErrors{ field message code } } }",
            {"p": fields}, "pageCreate",
        )
        return result["page"]["id"]

    # ---------------------------------------------------------------- articles
    def _blog(self, handle: str) -> str:
        cached = self.aux.setdefault("blogs", {}).get(handle)
        if cached:
            return cached
        data = self.client.graphql(
            "query($q:String!){ blogs(first:5, query:$q){ nodes{ id handle } } }", {"q": f"handle:{_quote(handle)}"}
        )
        gid = next((n["id"] for n in data["blogs"]["nodes"] if n["handle"] == handle), None)
        if not gid:
            result = self.client.mutate(
                "mutation($b:BlogCreateInput!){ blogCreate(blog:$b){ blog{ id } userErrors{ field message code } } }",
                {"b": {"title": handle.replace("-", " ").title(), "handle": handle}}, "blogCreate",
            )
            gid = result["blog"]["id"]
            self.aux["created_blogs"][handle] = gid
        self.aux["blogs"][handle] = gid
        return gid

    def _article(self, key, p, existing):
        blog_gid = self._blog(p.get("blog_handle") or "news")
        if existing is None:
            data = self.client.graphql(
                "query($q:String!){ articles(first:5, query:$q){ nodes{ id handle } } }",
                {"q": f"handle:{_quote(p['handle'])}"},
            )
            existing = next((n["id"] for n in data["articles"]["nodes"] if n["handle"] == p["handle"]), None)
        fields = {
            "blogId": blog_gid,
            "title": p["title"],
            "handle": p["handle"],
            "body": p.get("body_html") or "",
            "summary": p.get("excerpt") or None,
            "author": {"name": p.get("author") or "ProSporter"},
            "isPublished": bool(p.get("published")),
            "tags": p.get("tags") or [],
            "metafields": _seo_metafields(p.get("seo")),
        }
        if p.get("published") and p.get("published_at"):
            fields["publishDate"] = _dt(p["published_at"])
        if not fields["metafields"]:
            fields.pop("metafields")
        if existing:
            self.client.mutate(
                "mutation($id:ID!,$a:ArticleUpdateInput!){ articleUpdate(id:$id, article:$a){ article{ id } userErrors{ field message code } } }",
                {"id": existing, "a": fields}, "articleUpdate",
            )
            return existing
        result = self.client.mutate(
            "mutation($a:ArticleCreateInput!){ articleCreate(article:$a){ article{ id } userErrors{ field message code } } }",
            {"a": fields}, "articleCreate",
        )
        return result["article"]["id"]

    # --------------------------------------------------------------- customers
    def _customer(self, key, p, existing):
        woo_tag = f"woo:{(p.get('source') or {}).get('woo_id')}"
        if existing is None:
            data = self.client.graphql(
                "query($e:String!,$q:String!){ byEmail: customerByIdentifier(identifier:{emailAddress:$e}){ id }"
                " byTag: customers(first:1, query:$q){ nodes{ id } } }",
                {"e": p["email"], "q": f"tag:{_quote(woo_tag)}"},
            )
            existing = (data.get("byEmail") or {}).get("id") or next(
                (n["id"] for n in data["byTag"]["nodes"]), None
            )
        consent = p.get("email_marketing_consent") or {}
        fields = {
            "email": p["email"],
            "firstName": p.get("first_name") or None,
            "lastName": p.get("last_name") or None,
            "phone": p.get("phone") or None,
            "note": p.get("note") or None,
            "tags": p.get("tags") or [],
            "taxExempt": bool(p.get("tax_exempt")),
            "emailMarketingConsent": {
                "marketingState": consent.get("state") or "NOT_SUBSCRIBED",
                **({"marketingOptInLevel": consent["opt_in_level"]} if consent.get("opt_in_level") else {}),
                **({"consentUpdatedAt": _dt(consent["consent_updated_at"])} if consent.get("consent_updated_at") else {}),
            },
        }

        def run(mutation_fields):
            if existing:
                mutation_fields["id"] = existing
                self.client.mutate(
                    "mutation($i:CustomerInput!){ customerUpdate(input:$i){ customer{ id } userErrors{ field message } } }",
                    {"i": mutation_fields}, "customerUpdate",
                )
                return existing
            result = self.client.mutate(
                "mutation($i:CustomerInput!){ customerCreate(input:$i){ customer{ id } userErrors{ field message } } }",
                {"i": mutation_fields}, "customerCreate",
            )
            return result["customer"]["id"]

        try:
            gid = run(dict(fields))
        except ShopifyAdminError as exc:
            if fields.get("phone") and "phone" in str(exc).lower():
                fields["phone"] = None
                fields["note"] = ((fields.get("note") or "") + f"\nSource phone rejected by Shopify: {p.get('phone')}").strip()
                gid = run(dict(fields))
            else:
                raise
        address = p.get("default_address") or {}
        if address and any(address.get(k) for k in ("address1", "city", "zip")):
            self._customer_address(gid, address)
        return gid

    def _customer_address(self, customer_gid: str, a: dict):
        payload = {
            "address1": a.get("address1") or None, "address2": a.get("address2") or None,
            "city": a.get("city") or None, "company": a.get("company") or None,
            "countryCode": a.get("country_code") or None, "firstName": a.get("first_name") or None,
            "lastName": a.get("last_name") or None, "phone": a.get("phone") or None,
            "provinceCode": a.get("province_code") or None, "zip": a.get("zip") or None,
        }
        data = self.client.graphql(
            "query($id:ID!){ customer(id:$id){ defaultAddress{ id } } }", {"id": customer_gid}
        )
        current = ((data.get("customer") or {}).get("defaultAddress") or {}).get("id")

        def run(address_payload):
            if current:
                self.client.mutate(
                    "mutation($c:ID!,$a:ID!,$addr:MailingAddressInput!){ customerAddressUpdate(customerId:$c, addressId:$a, address:$addr, setAsDefault:true){"
                    " address{ id } userErrors{ field message } } }",
                    {"c": customer_gid, "a": current, "addr": address_payload}, "customerAddressUpdate",
                )
            else:
                self.client.mutate(
                    "mutation($c:ID!,$addr:MailingAddressInput!){ customerAddressCreate(customerId:$c, address:$addr, setAsDefault:true){"
                    " address{ id } userErrors{ field message } } }",
                    {"c": customer_gid, "addr": address_payload}, "customerAddressCreate",
                )

        try:
            run(payload)
        except ShopifyAdminError as exc:
            if payload.get("phone") and "phone" in str(exc).lower():
                payload["phone"] = None
                run(payload)
            else:
                raise

    # --------------------------------------------------------------- discounts
    def _discount(self, key, p, existing):
        if existing is None:
            data = self.client.graphql(
                "query($c:String!){ codeDiscountNodeByCode(code:$c){ id codeDiscount{ __typename } } }", {"c": p["code"]}
            )
            node = data.get("codeDiscountNodeByCode")
            existing = node["id"] if node else None
        value = p.get("value") or {}
        if p.get("free_shipping") and (value.get("amount") in (None, "0.00", "0")):
            raise ShopifyAdminError("free-shipping coupon: create with discountCodeFreeShippingCreate after decision")
        if p.get("free_shipping"):
            raise ShopifyAdminError("coupon combines a value discount with free shipping; needs a decision")
        if value.get("type") == "percentage":
            gets_value = {"percentage": round(float(value["amount"]) / 100.0, 4)}
        elif value.get("type") in ("fixed_amount", "fixed_cart"):
            gets_value = {"discountAmount": {"amount": value["amount"],
                                             "appliesOnEachItem": bool(value.get("applies_on_each_item"))}}
        elif value.get("type") == "fixed_product":
            gets_value = {"discountAmount": {"amount": value["amount"], "appliesOnEachItem": True}}
        else:
            raise ShopifyAdminError(f"unsupported coupon value type {value.get('type')!r}")
        items = {"all": True}
        if p.get("entitled_category_ids"):
            raise ShopifyAdminError("coupon restricted to Woo categories; map to collections first")
        if p.get("entitled_product_ids") or p.get("excluded_product_ids"):
            if p.get("excluded_product_ids"):
                raise ShopifyAdminError("coupon with excluded products has no Shopify equivalent; needs a decision")
            index = self.indexes.get("product_woo_id") or self._mapping_index("product_woo_id")
            gids = []
            for woo_id in p["entitled_product_ids"]:
                found = index.get(str(woo_id))
                if not found:
                    raise ShopifyAdminError(f"entitled product woo:{woo_id} was not loaded")
                gids.append(found[0])
            items = {"products": {"productsToAdd": gids}}
        fields = {
            "title": p.get("title") or p["code"],
            "code": p["code"],
            "startsAt": _dt(p.get("starts_at")) or _dt("2020-01-01T00:00:00"),
            "endsAt": _dt(p.get("ends_at")),
            "appliesOncePerCustomer": bool(p.get("applies_once_per_customer")),
            "usageLimit": p.get("usage_limit"),
            "context": {"all": "ALL"},
            "customerGets": {"value": gets_value, "items": items},
            "combinesWith": p.get("combines_with") or {},
        }
        if p.get("minimum_subtotal"):
            fields["minimumRequirement"] = {"subtotal": {"greaterThanOrEqualToSubtotal": p["minimum_subtotal"]}}
        if existing:
            self.client.mutate(
                "mutation($id:ID!,$d:DiscountCodeBasicInput!){ discountCodeBasicUpdate(id:$id, basicCodeDiscount:$d){"
                " codeDiscountNode{ id } userErrors{ field message code } } }",
                {"id": existing, "d": fields}, "discountCodeBasicUpdate",
            )
            return existing
        result = self.client.mutate(
            "mutation($d:DiscountCodeBasicInput!){ discountCodeBasicCreate(basicCodeDiscount:$d){"
            " codeDiscountNode{ id } userErrors{ field message code } } }",
            {"d": fields}, "discountCodeBasicCreate",
        )
        return result["codeDiscountNode"]["id"]

    def _mapping_index(self, name):
        return ((read_json(self.mapping_path) if self.mapping_path.exists() else {}).get("indexes") or {}).get(name, {})

    # ------------------------------------------------------------------- purge
    def purge(self, dry_run: bool = True) -> dict:
        """Delete every object this ledger created on the store (staging resets only)."""
        plan = []
        order = [
            ("DiscountCodeNode", "mutation($id:ID!){ discountCodeDelete(id:$id){ deletedCodeDiscountId userErrors{ field message } } }", "discountCodeDelete", "id"),
            ("Customer", "mutation($id:ID!){ customerDelete(input:{id:$id}){ deletedCustomerId userErrors{ field message } } }", "customerDelete", "id"),
            ("Article", "mutation($id:ID!){ articleDelete(id:$id){ deletedArticleId userErrors{ field message } } }", "articleDelete", "id"),
            ("Page", "mutation($id:ID!){ pageDelete(id:$id){ deletedPageId userErrors{ field message } } }", "pageDelete", "id"),
            ("Product", "mutation($id:ID!){ productDelete(input:{id:$id}, synchronous:true){ deletedProductId userErrors{ field message } } }", "productDelete", "id"),
            ("Collection", "mutation($id:ID!){ collectionDelete(input:{id:$id}){ deletedCollectionId userErrors{ field message } } }", "collectionDelete", "id"),
        ]
        for resource, mutation, result_key, _ in order:
            for key, entry in sorted(self.state["objects"].get(resource, {}).items()):
                plan.append((resource, key, entry["id"], mutation, result_key))
        for handle, gid in sorted(self.aux.get("created_blogs", {}).items()):
            plan.append(("Blog", handle, gid,
                         "mutation($id:ID!){ blogDelete(id:$id){ deletedBlogId userErrors{ field message } } }", "blogDelete"))
        for key, entry in sorted(self.state["objects"].get("MetafieldDefinition", {}).items()):
            owner, rest = key.split(":", 1)
            namespace, mkey = rest.split(".", 1)
            plan.append(("MetafieldDefinition", key, entry["id"],
                         "mutation($o:MetafieldOwnerType!,$ns:String!,$k:String!){ metafieldDefinitionDelete("
                         "identifier:{ownerType:$o, namespace:$ns, key:$k}, deleteAllAssociatedMetafields:true){"
                         " deletedDefinitionId userErrors{ field message } } }", "metafieldDefinitionDelete",
                         {"o": owner, "ns": namespace, "k": mkey}))
        summary = {"store": self.store_domain, "dry_run": dry_run, "planned": len(plan), "deleted": 0, "errors": []}
        if dry_run:
            summary["by_resource"] = {}
            for item in plan:
                summary["by_resource"][item[0]] = summary["by_resource"].get(item[0], 0) + 1
            return summary
        for item in plan:
            resource, key, gid, mutation, result_key = item[:5]
            variables = item[5] if len(item) > 5 else {"id": gid}
            try:
                self.client.mutate(mutation, variables, result_key)
                summary["deleted"] += 1
            except ShopifyAdminError as exc:
                if "not found" in str(exc).lower() or "does not exist" in str(exc).lower():
                    summary["deleted"] += 1
                else:
                    summary["errors"].append({"resource": resource, "key": key, "message": str(exc)[:300]})
        if not summary["errors"]:
            for path in (self.store_path, self.mapping_path, self.store_dir / "failures.json"):
                if path.exists():
                    path.unlink()
        return summary


# ---------------------------------------------------------------------------
# CLI: staging resets
# ---------------------------------------------------------------------------

def main(argv):
    import argparse
    parser = argparse.ArgumentParser(description="Live Shopify target maintenance")
    parser.add_argument("command", choices=["purge", "status"])
    parser.add_argument("--store", required=True, help="ledger directory used by the live load")
    parser.add_argument("--yes", action="store_true", help="actually delete (purge defaults to a dry run)")
    args = parser.parse_args(argv[1:])
    target = ShopifyAdminTarget(Path(args.store))
    if args.command == "status":
        print(json.dumps({"store": target.store_domain, "objects": target.counts()}, indent=2))
        return 0
    summary = target.purge(dry_run=not args.yes)
    print(json.dumps(summary, indent=2))
    return 1 if summary.get("errors") else 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
