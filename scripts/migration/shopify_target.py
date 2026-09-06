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
  * ``publishablePublish`` takes a single publishable id, so the publish stage
    batches with aliased mutation fields instead of a list argument.

Beyond the loader this module owns two post-load operations:

  * ``publish`` (driven by ``run.py publish``) exposes loaded products and
    collections to a named publication and, with ``activate_published``, sets
    ACTIVE only the products whose source status was ``publish``.
  * ``verify`` (CLI, read-only) compares the ledger with the live store.

CLI::

    python3 scripts/migration/shopify_target.py status --store <ledger>
    python3 scripts/migration/shopify_target.py verify --store <ledger>
    python3 scripts/migration/shopify_target.py purge  --store <ledger> [--yes]
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import uuid
from pathlib import Path

from common import SHOPIFY_API_VERSION, checksum, read_json, utc_now, write_json
from loader import FakeShopifyTarget
from shopify_admin import AdminClient, ShopifyAdminError

# Source timestamps have no zone; the WordPress site runs on Australian Eastern
# time. Offsets are only cosmetic for publish dates.
SOURCE_TZ_OFFSET = "+10:00"
MEDIA_READY_WAIT_SECONDS = 90
# ``nodes(ids:)`` accepts up to 250 ids; 50 keeps a single request's query cost
# well inside the store's bucket even with the fattest fragment.
NODE_BATCH = 50
# Aliased mutations per document for the publish stage.
PUBLISH_BATCH = 10


def _chunks(items, size):
    items = list(items)
    for start in range(0, len(items), max(1, size)):
        yield items[start:start + size]


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
        self.state.setdefault("file_urls", {})               # source url -> cdn url (CLNT-323)
        self._pending_files: dict[str, str] = {}             # file gid -> source url
        self.stats["failed"] = 0
        self.failures: list[dict] = []
        self.warnings: list[dict] = []  # record loaded, but with a caveat worth surfacing
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

    def _warn(self, resource, key, message):
        self.warnings.append({"resource": resource, "key": key, "message": message[:500]})

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
            "warnings": self.warnings,
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
            "File": self._file,
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
        # 2026-07: MetafieldDefinitionInput and MetafieldDefinitionUpdateInput both
        # carry `description`, `pin: Boolean` and `validations: [MetafieldDefinitionValidationInput!]`
        # ({name, value} pairs; `choices` takes a JSON array string), so pinning
        # needs no separate metafieldDefinitionPin call on either path. `type` is
        # create-only - the update input has no type field.
        definition = {
            "namespace": p["namespace"],
            "key": p["key"],
            "ownerType": p["owner_type"],
            "name": p["name"],
            "description": p.get("description") or "",
            "pin": bool(p.get("pin")),
            "validations": list(p.get("validations") or []),
            "access": {"storefront": storefront},
        }
        if existing:
            self.client.mutate(
                "mutation($d:MetafieldDefinitionUpdateInput!){ metafieldDefinitionUpdate(definition:$d){"
                " updatedDefinition{ id } userErrors{ field message } } }",
                {"d": definition},
                "metafieldDefinitionUpdate",
            )
            return existing
        result = self.client.mutate(
            "mutation($d:MetafieldDefinitionInput!){ metafieldDefinitionCreate(definition:$d){"
            " createdDefinition{ id } userErrors{ field message code } } }",
            {"d": dict(definition, type=p["type"])},
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
            # Keep the per-product cache truthful: the auto-created variant had
            # no SKU until this update, and the media stage looks variants up by SKU.
            match.update(node)
            match["metafield"] = {"value": woo_id}
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

    @staticmethod
    def _source_url(url: str) -> str:
        """Percent-encode anything Shopify's fetcher rejects (e.g. U+202F in
        macOS screenshot names) while leaving existing escapes alone."""
        return urllib.parse.quote(url, safe=":/?=&%+@")

    @staticmethod
    def _stem(url_or_name: str) -> str:
        name = urllib.parse.unquote(url_or_name.split("?", 1)[0].rsplit("/", 1)[-1])
        name = name.rsplit(".", 1)[0]
        return re.sub(r"[^a-z0-9]", "", name.lower())

    def _live_media(self, product_gid: str) -> list[dict]:
        """[{id, status, stem}] for the product; cached per run."""
        cache = self._media_cache.setdefault("__live__", {})
        if product_gid not in cache:
            data = self.client.graphql(
                "query($id:ID!){ product(id:$id){ media(first:250){ nodes{ id status"
                " ... on MediaImage { image{ url } } } } } }", {"id": product_gid}
            )
            nodes = ((data.get("product") or {}).get("media") or {}).get("nodes", [])
            cache[product_gid] = [
                {"id": n["id"], "status": n["status"],
                 "stem": self._stem(((n.get("image") or {}).get("url")) or "")}
                for n in nodes
            ]
            self._media_cache[product_gid] = {n["id"] for n in nodes}
        return cache[product_gid]

    def _claimed_media_ids(self) -> set[str]:
        return {e["id"] for e in self.state["objects"].get("MediaImage", {}).values()}

    def _find_uploaded_media(self, product_gid: str, source_url: str):
        """An image that reached the product on an earlier run but never made it
        into the ledger (e.g. the run failed after the upload). Shopify keeps the
        source filename in the CDN URL, so match on the normalised stem among
        media no ledger entry claims yet."""
        stem = self._stem(source_url)
        if not stem:
            return None
        claimed = self._claimed_media_ids()
        for node in self._live_media(product_gid):
            if node["id"] in claimed:
                continue
            # Exact stem, or Shopify's duplicate-filename suffix ("name_<n>").
            if node["stem"] == stem or re.fullmatch(re.escape(stem) + r"_?[0-9a-f]{1,32}", node["stem"]):
                return node["id"]
        return None

    def _media(self, key, p, existing):
        if p.get("reachable") is False:
            raise ShopifyAdminError(f"source image unreachable (HTTP {p.get('http_status')})")
        product_gid = self.gid("Product", p["product_handle"])
        if not product_gid:
            raise ShopifyAdminError(f"product {p['product_handle']} was not loaded; media skipped")
        # Match variants by Woo variation id (unique) via the migration.woo_id
        # metafield; fall back to SKU only for records without ids.
        wanted = []
        woo_ids = p.get("variant_woo_ids") or []
        skus = list(p.get("variant_skus") or ([p["variant_sku"]] if p.get("variant_sku") else []))
        for i, sku in enumerate(skus):
            wanted.append({"woo_id": str(woo_ids[i]) if i < len(woo_ids) else None, "sku": sku})
        resolved = {}  # variant gid -> ref (dedupes variants referenced twice)
        unresolved = []
        if wanted:
            live = self._variants(product_gid)
            by_woo = {(v.get("metafield") or {}).get("value"): v for v in live}
            by_sku = {}
            for v in live:
                by_sku.setdefault(v.get("sku"), v)
            for ref in wanted:
                v = by_woo.get(ref["woo_id"]) if ref["woo_id"] else None
                if v is None:
                    v = by_sku.get(ref["sku"])
                if v is None:
                    unresolved.append(ref)
                else:
                    resolved.setdefault(v["id"], ref)
        if existing:
            # Alt text is the only mutable attribute we own; update it in place.
            if p.get("alt"):
                self.client.mutate(
                    "mutation($f:[FileUpdateInput!]!){ fileUpdate(files:$f){ files{ id } userErrors{ field message } } }",
                    {"f": [{"id": existing, "alt": p["alt"]}]}, "fileUpdate",
                )
            media_gid = existing
        else:
            media_gid = self._find_uploaded_media(product_gid, p["original_url"])
            if media_gid:
                self._warn("MediaImage", key, "reused an image already on the product (uploaded by an earlier run)")
            else:
                before = set(self._media_ids(product_gid))
                media = {"originalSource": self._source_url(p["original_url"]), "mediaContentType": "IMAGE"}
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
                self._media_cache.get("__live__", {}).pop(product_gid, None)
                if len(new) != 1:
                    raise ShopifyAdminError(f"expected one new media object, saw {len(new)}")
                media_gid = new.pop()
        for ref in unresolved:
            # The variant is held (not loaded) or its SKU changed: keep the image
            # in the product gallery and surface the missing attachment.
            self._warn("MediaImage", key,
                       f"variant woo:{ref['woo_id']} sku {ref['sku']} not loaded; image kept in gallery, not attached")
        for variant_gid in resolved:
            # Runs on update too, so a payload that gained variants re-attaches.
            self.deferred_variant_media.append((product_gid, variant_gid, media_gid, key))
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
                # One media per variant per batch: Shopify rejects duplicate variant ids.
                first_by_variant = {}
                for item in items:
                    first_by_variant.setdefault(item[1], item)
                items = list(first_by_variant.values())
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

    # ----------------------------------------------------- body images (files)
    def _file(self, key, p, existing):
        """Upload one page/article body image to Shopify Files.

        Deliberately *not* product media: these images belong to page content,
        not to a product gallery, so they go through ``fileCreate`` and land in
        Content -> Files. The destination CDN URL is what the body HTML is
        rewritten to, so it is recorded in the ledger against the source URL and
        a rerun reuses it without uploading anything.
        """
        if p.get("reachable") is False:
            raise ShopifyAdminError(f"source image unreachable (HTTP {p.get('http_status')})")
        if existing:
            if p.get("alt"):
                self.client.mutate(
                    "mutation($f:[FileUpdateInput!]!){ fileUpdate(files:$f){ files{ id }"
                    " userErrors{ field message } } }",
                    {"f": [{"id": existing, "alt": p["alt"]}]}, "fileUpdate",
                )
            if key not in self.state["file_urls"]:
                self._pending_files[existing] = key
            return existing
        found = self._find_uploaded_file(p["filename"])
        if found:
            gid, url = found
            self._warn("File", key, "reused a file uploaded by an earlier run")
            if url:
                self.state["file_urls"][key] = url
            else:
                self._pending_files[gid] = key
            return gid
        create = {
            "originalSource": self._source_url(p["source_url"]),
            "contentType": p.get("content_type") or "IMAGE",
            "filename": p["filename"],
        }
        if p.get("alt"):
            create["alt"] = p["alt"]
        result = self.client.mutate(
            "mutation($f:[FileCreateInput!]!){ fileCreate(files:$f){ files{ id fileStatus"
            " ... on MediaImage { image{ url } }"
            " ... on GenericFile { url } } userErrors{ field message code } } }",
            {"f": [create]}, "fileCreate",
        )
        files = result.get("files") or []
        if not files:
            raise ShopifyAdminError("fileCreate returned no file")
        gid = files[0]["id"]
        url = files[0].get("url") or (files[0].get("image") or {}).get("url")
        if url:
            self.state["file_urls"][key] = url
        else:
            # Shopify processes the fetch asynchronously; the CDN URL arrives
            # once fileStatus is READY. Collected and polled in one batch by
            # file_urls(), which the loader calls before it writes any page.
            self._pending_files[gid] = key
        return gid

    def _find_uploaded_file(self, name: str):
        """(gid, url) for a file an earlier interrupted run already uploaded."""
        stem = self._stem(name)
        if not stem:
            return None
        try:
            data = self.client.graphql(
                "query($q:String!){ files(first:20, query:$q){ nodes{ id fileStatus"
                " ... on MediaImage { image{ url } }"
                " ... on GenericFile { url } } } }",
                {"q": f"filename:{_quote(name)}"},
            )
        except ShopifyAdminError:
            return None
        claimed = {e["id"] for e in self.state["objects"].get("File", {}).values()}
        for node in (data.get("files") or {}).get("nodes", []):
            if node["id"] in claimed or node.get("fileStatus") == "FAILED":
                continue
            url = node.get("url") or (node.get("image") or {}).get("url")
            if url and self._stem(url) not in (stem, ""):
                continue
            return node["id"], url
        return None

    def file_urls(self) -> dict:
        """source URL -> CDN URL, polling anything Shopify is still processing.

        Called by the loader immediately before the first page is written, so
        every body image has a destination URL by the time a body is rewritten.
        """
        deadline = time.time() + MEDIA_READY_WAIT_SECONDS
        while self._pending_files:
            resolved = []
            for batch in _chunks(sorted(self._pending_files), NODE_BATCH):
                data = self.client.graphql(
                    "query($ids:[ID!]!){ nodes(ids:$ids){ id"
                    " ... on MediaImage { fileStatus image{ url } }"
                    " ... on GenericFile { fileStatus url } } }",
                    {"ids": list(batch)},
                )
                for node in data.get("nodes") or []:
                    if not node:
                        continue
                    key = self._pending_files.get(node["id"])
                    url = node.get("url") or (node.get("image") or {}).get("url")
                    if url:
                        self.state["file_urls"][key] = url
                        resolved.append(node["id"])
                    elif node.get("fileStatus") == "FAILED":
                        self._fail("File", key, "Shopify could not process the uploaded file")
                        resolved.append(node["id"])
            for gid in resolved:
                self._pending_files.pop(gid, None)
            if self._pending_files:
                if time.time() > deadline:
                    for gid, key in self._pending_files.items():
                        self._warn("File", key,
                                   "still processing after the wait; the body keeps the "
                                   "WordPress URL until the next run")
                    self._pending_files = {}
                    break
                time.sleep(3)
        self._flush()
        return self.state["file_urls"]

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

    # ----------------------------------------------------------------- publish
    # Step 10 of the execution plan: expose the loaded catalog to a sales
    # channel. The load itself never publishes, so this is a separate, explicit
    # stage run after QA (``run.py publish``).
    #
    # Schema note (introspected on the client store, Admin API 2026-07):
    # ``publishablePublish(id: ID!, input: [PublicationInput!]!)`` takes exactly
    # one publishable id -- there is no multi-id publish mutation, and
    # ``PublicationInput`` only carries ``publicationId`` / ``publishDate``. So
    # "batching" means several aliased ``publishablePublish`` fields in one
    # GraphQL document, which is what ``_batch_mutate`` does.

    def publication(self, name: str) -> dict:
        """Resolve a publication by name. Read-only."""
        data = self.client.graphql(
            "query($n:Int!){ publications(first:$n){ nodes{ id name } } }", {"n": 50}
        )
        nodes = (data.get("publications") or {}).get("nodes") or []
        found = next((n for n in nodes if n["name"] == name), None)
        if not found:
            raise ShopifyAdminError(
                f"no publication named {name!r}; have {[n['name'] for n in nodes]}"
            )
        return {"id": found["id"], "name": found["name"]}

    def publish_targets(self, only_products=None) -> list[dict]:
        """Every publishable object in the ledger, in publish order. No network.

        ``only_products`` narrows the run to those product handles and drops
        collections, so a QA publish stays as small as the smoke load did.
        """
        only = set(only_products) if only_products else None
        items = []
        for key, entry in sorted(self.state["objects"].get("Product", {}).items()):
            if only is not None and key not in only:
                continue
            items.append({
                "resource": "Product",
                "key": key,
                "id": entry["id"],
                "source_status": (entry.get("payload") or {}).get("source_status"),
            })
        if only is None:
            for key, entry in sorted(self.state["objects"].get("Collection", {}).items()):
                items.append({"resource": "Collection", "key": key, "id": entry["id"],
                              "source_status": None})
        return items

    PUBLISH_STATE_QUERY = (
        "query($ids:[ID!]!){ nodes(ids:$ids){ id __typename"
        " ... on Product { handle status resourcePublicationsV2(first:25){"
        " nodes{ isPublished publication{ id } } } }"
        " ... on Collection { handle resourcePublicationsV2(first:25){"
        " nodes{ isPublished publication{ id } } } } } }"
    )

    def publication_state(self, gids, publication_gid: str, batch_size: int = NODE_BATCH) -> dict:
        """{gid: {"exists", "status", "published"}} read with batched ``nodes(ids:)``."""
        state: dict[str, dict] = {}
        for chunk in _chunks(list(gids), batch_size):
            data = self.client.graphql(self.PUBLISH_STATE_QUERY, {"ids": chunk})
            for gid, node in zip(chunk, data.get("nodes") or []):
                if node is None:
                    state[gid] = {"exists": False, "status": None, "published": False}
                    continue
                published = any(
                    n.get("isPublished") and (n.get("publication") or {}).get("id") == publication_gid
                    for n in ((node.get("resourcePublicationsV2") or {}).get("nodes") or [])
                )
                state[node["id"]] = {"exists": True, "status": node.get("status"),
                                     "published": published}
        return state

    def plan_publish(self, publication_name: str, activate_published: bool = False,
                     only_products=None) -> dict:
        """Read the live publication/status state and decide what has to change.

        Pure planning on top of two read-only queries, so it is unit-testable
        with a stub client. Objects already published (and already ACTIVE when
        ``activate_published`` is set) are reported ``unchanged``; drafts in the
        source stay DRAFT whatever the flag says.
        """
        publication = self.publication(publication_name)
        targets = self.publish_targets(only_products)
        state = self.publication_state([t["id"] for t in targets], publication["id"])
        items, counts = [], {"total": len(targets), "publish": 0, "activate": 0,
                             "unchanged": 0, "missing": 0}
        for target in targets:
            live = state.get(target["id"], {"exists": False, "status": None, "published": False})
            item = dict(target)
            item["live_status"] = live.get("status")
            item["published"] = bool(live.get("published"))
            actions = []
            if not live.get("exists"):
                item["actions"] = []
                item["reason"] = "object in the ledger no longer exists on the store"
                counts["missing"] += 1
                items.append(item)
                continue
            if not live["published"]:
                actions.append("publish")
            wants_active = (
                activate_published
                and target["resource"] == "Product"
                and target.get("source_status") == "publish"
            )
            if wants_active and live.get("status") != "ACTIVE":
                actions.append("activate")
            item["actions"] = actions
            if not actions:
                item["reason"] = "already published" + (" and ACTIVE" if wants_active else "")
                counts["unchanged"] += 1
            else:
                if "publish" in actions:
                    counts["publish"] += 1
                if "activate" in actions:
                    counts["activate"] += 1
            items.append(item)
        return {
            "store": self.store_domain,
            "api_version": SHOPIFY_API_VERSION,
            "publication": publication,
            "activate_published": bool(activate_published),
            "only_products": sorted(only_products) if only_products else None,
            "counts": counts,
            "items": items,
        }

    def _batch_mutate(self, field: str, arguments: str, alias_values: dict, alias_type: str,
                      shared: dict | None = None, shared_types: dict | None = None) -> dict:
        """Run several aliased copies of one mutation field in a single document.

        ``arguments`` is a format string using ``{alias}`` for the per-object
        variable name. Returns {alias: error message or None}. A whole-document
        failure retries one alias per request, so a single bad id cannot fail
        the whole batch.
        """
        shared = shared or {}
        shared_types = shared_types or {}
        aliases = sorted(alias_values)
        decl = ", ".join([f"${a}: {alias_type}" for a in aliases]
                         + [f"${k}: {shared_types[k]}" for k in sorted(shared)])
        body = " ".join(
            f"{a}: {field}({arguments.format(alias=a)}) {{ userErrors {{ field message }} }}"
            for a in aliases
        )
        variables = dict(shared)
        variables.update(alias_values)
        try:
            data = self.client.graphql(f"mutation({decl}) {{ {body} }}", variables)
        except ShopifyAdminError as exc:
            if len(aliases) == 1:
                return {aliases[0]: str(exc)[:300]}
            out = {}
            for alias in aliases:
                out.update(self._batch_mutate(field, arguments, {alias: alias_values[alias]},
                                              alias_type, shared, shared_types))
            return out
        results = {}
        for alias in aliases:
            errors = ((data.get(alias) or {}).get("userErrors")) or []
            results[alias] = "; ".join(
                f"{'.'.join(map(str, e.get('field') or []))}: {e.get('message')}" for e in errors
            )[:300] or None
        return results

    def apply_publish(self, plan: dict, batch_size: int = PUBLISH_BATCH) -> dict:
        """Execute a plan from ``plan_publish``. Returns the plan with outcomes."""
        publication_gid = plan["publication"]["id"]
        by_id = {item["id"]: item for item in plan["items"]}
        for item in plan["items"]:
            item.setdefault("outcome", "unchanged" if not item["actions"] else "pending")
            if item["actions"] == [] and item.get("reason", "").startswith("object in the ledger"):
                item["outcome"] = "failed"

        to_publish = [i for i in plan["items"] if "publish" in i["actions"]]
        for chunk in _chunks(to_publish, batch_size):
            errors = self._batch_mutate(
                "publishablePublish", "id: ${alias}, input: [{{publicationId: $pub}}]",
                {f"i{n}": item["id"] for n, item in enumerate(chunk)}, "ID!",
                {"pub": publication_gid}, {"pub": "ID!"},
            )
            for n, item in enumerate(chunk):
                message = errors.get(f"i{n}")
                if message:
                    item["outcome"] = "failed"
                    item["error"] = message
                else:
                    item["outcome"] = "published"
                    item["published_now"] = True

        to_activate = [i for i in plan["items"]
                       if "activate" in i["actions"] and by_id[i["id"]].get("outcome") != "failed"]
        for chunk in _chunks(to_activate, batch_size):
            errors = self._batch_mutate(
                "productUpdate", "product: ${alias}",
                {f"i{n}": {"id": item["id"], "status": "ACTIVE"} for n, item in enumerate(chunk)},
                "ProductUpdateInput!",
            )
            for n, item in enumerate(chunk):
                message = errors.get(f"i{n}")
                if message:
                    item["outcome"] = "failed"
                    item["error"] = message
                else:
                    item["outcome"] = "activated"
                    item["activated_now"] = True
                    item["live_status"] = "ACTIVE"

        # An object can be both published and activated in one run, so count
        # each action on its own rather than one label per object.
        outcomes = {
            "published": sum(1 for i in plan["items"] if i.get("published_now")),
            "activated": sum(1 for i in plan["items"] if i.get("activated_now")),
            "unchanged": sum(1 for i in plan["items"] if i.get("outcome", "unchanged") == "unchanged"),
            "failed": sum(1 for i in plan["items"] if i.get("outcome") == "failed"),
        }
        plan["outcomes"] = outcomes
        return plan

    def publish(self, publication_name: str, activate_published: bool = False,
                only_products=None, live: bool = False, batch_size: int = PUBLISH_BATCH) -> dict:
        """Plan (always) then apply (only when ``live``). Idempotent either way."""
        plan = self.plan_publish(publication_name, activate_published, only_products)
        plan["dry_run"] = not live
        plan["generated_at"] = utc_now()
        if live:
            self.apply_publish(plan, batch_size=batch_size)
        else:
            plan["outcomes"] = {
                "published": plan["counts"]["publish"],
                "activated": plan["counts"]["activate"],
                "unchanged": plan["counts"]["unchanged"],
                "failed": plan["counts"]["missing"],
            }
        write_json(self.store_dir / "publish-result.json", plan)
        return plan

    # ------------------------------------------------------------------ verify
    VERIFY_QUERY = (
        "query($ids:[ID!]!){ nodes(ids:$ids){ id __typename"
        " ... on Product { handle title status variantsCount{ count } }"
        " ... on Collection { handle title }"
        " ... on Page { handle title }"
        " ... on Article { handle title }"
        " ... on ProductVariant { sku }"
        " ... on MediaImage { status }"
        " ... on MetafieldDefinition { namespace key }"
        " } }"
    )
    # Customer, InventoryItem, Metafield and DiscountCodeNode are presence-only:
    # nothing about them is fetched, so no personal data can enter a report.

    def verify(self, checksums: bool = True, batch_size: int = NODE_BATCH) -> dict:
        """Read-only ledger-vs-store comparison. Writes reports, never the store.

        Reports: objects in the ledger that no longer exist on the store,
        products whose live variant count differs from the ledger's, media that
        Shopify left in a non-READY state, and (with ``checksums``) products
        whose handle/title/status drifted away from the loaded payload.
        """
        objects = self.state["objects"]
        # CollectionMembership entries reuse their collection's gid, so one gid
        # can stand for more than one ledger row: index by gid -> [rows].
        index: dict[str, list[dict]] = {}
        ledger_rows = 0
        for resource, entries in sorted(objects.items()):
            for key, entry in sorted(entries.items()):
                ledger_rows += 1
                index.setdefault(entry["id"], []).append(
                    {"resource": resource, "key": key, "payload": entry.get("payload") or {}}
                )
        gids = sorted(index)
        live: dict[str, dict] = {}
        missing = []
        for chunk in _chunks(gids, batch_size):
            data = self.client.graphql(self.VERIFY_QUERY, {"ids": chunk})
            for gid, node in zip(chunk, data.get("nodes") or []):
                if node is None:
                    missing.extend({"resource": row["resource"], "key": row["key"], "id": gid}
                                   for row in index[gid])
                else:
                    live[node["id"]] = node

        ledger_variants: dict[str, int] = {}
        for entry in objects.get("ProductVariant", {}).values():
            handle = (entry.get("payload") or {}).get("product_handle")
            if handle:
                ledger_variants[handle] = ledger_variants.get(handle, 0) + 1

        variant_mismatches, drift, media_not_ready = [], [], []
        for gid, node in sorted(live.items()):
            meta = next((row for row in index[gid] if row["resource"] == node.get("__typename")),
                        index[gid][0])
            payload = meta["payload"]
            if node.get("__typename") == "Product":
                expected = ledger_variants.get(meta["key"], 0)
                actual = (node.get("variantsCount") or {}).get("count")
                if expected and actual is not None and actual != expected:
                    variant_mismatches.append({"handle": meta["key"], "id": gid,
                                               "ledger_variants": expected, "live_variants": actual})
                if checksums:
                    fields = {}
                    for field, ledger_value in (("handle", payload.get("handle")),
                                                ("title", payload.get("title")),
                                                ("status", payload.get("status"))):
                        live_value = node.get(field)
                        if ledger_value is not None and live_value != ledger_value:
                            fields[field] = {"ledger": ledger_value, "live": live_value}
                    if fields:
                        note = None
                        if set(fields) == {"status"} and fields["status"]["live"] == "ACTIVE":
                            note = "status raised to ACTIVE outside the load (publish stage or QA helper)"
                        drift.append({"handle": meta["key"], "id": gid, "fields": fields, "note": note})
            elif node.get("__typename") == "MediaImage" and node.get("status") not in (None, "READY"):
                media_not_ready.append({"key": meta["key"], "id": gid, "status": node.get("status")})

        report = {
            "generated_at": utc_now(),
            "store": self.store_domain,
            "api_version": SHOPIFY_API_VERSION,
            "store_dir": str(self.store_dir),
            "ledger_rows": ledger_rows,
            "checked": len(gids),
            "ledger_counts": self.counts(),
            "live_found": len(live),
            "summary": {
                "missing": len(missing),
                "variant_count_mismatch": len(variant_mismatches),
                "field_drift": len(drift),
                "media_not_ready": len(media_not_ready),
                "api_calls": self.client.calls,
            },
            "missing": missing,
            "variant_count_mismatch": variant_mismatches,
            "field_drift": drift,
            "media_not_ready": media_not_ready,
        }
        write_json(self.store_dir / "verify-result.json", report)
        (self.store_dir / "verify-report.md").write_text(_verify_markdown(report), encoding="utf-8")
        return report

    # ------------------------------------------------------------------- purge
    def purge(self, dry_run: bool = True, only: set[str] | None = None) -> dict:
        """Delete every object this ledger created on the store (staging resets only).

        ``only`` restricts the purge to the named resources (e.g. ``{"Customer",
        "DiscountCodeNode"}``). A scoped purge removes just those entries from
        the ledger and keeps the ledger files, so the rest of the store stays
        tracked. It exists for exactly one situation: a pre-cutover run that
        forgot ``--skip-types customers,discounts`` (see the cutover runbook).
        """
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
        # Body images (CLNT-323) live in Content -> Files; fileDelete takes a list.
        for key, entry in sorted(self.state["objects"].get("File", {}).items()):
            plan.append(("File", key, entry["id"],
                         "mutation($ids:[ID!]!){ fileDelete(fileIds:$ids){ deletedFileIds"
                         " userErrors{ field message } } }", "fileDelete",
                         {"ids": [entry["id"]]}))
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
        if only is not None:
            plan = [item for item in plan if item[0] in only]
        summary = {"store": self.store_domain, "dry_run": dry_run, "planned": len(plan), "deleted": 0,
                   "errors": [], "only": sorted(only) if only is not None else None}
        if dry_run:
            summary["by_resource"] = {}
            for item in plan:
                summary["by_resource"][item[0]] = summary["by_resource"].get(item[0], 0) + 1
            return summary
        deleted_keys: list[tuple[str, str]] = []
        for item in plan:
            resource, key, gid, mutation, result_key = item[:5]
            variables = item[5] if len(item) > 5 else {"id": gid}
            try:
                self.client.mutate(mutation, variables, result_key)
                summary["deleted"] += 1
                deleted_keys.append((resource, key))
            except ShopifyAdminError as exc:
                if "not found" in str(exc).lower() or "does not exist" in str(exc).lower():
                    summary["deleted"] += 1
                    deleted_keys.append((resource, key))
                else:
                    summary["errors"].append({"resource": resource, "key": key, "message": str(exc)[:300]})
        if only is not None:
            # Scoped purge: forget only what was deleted; the ledger stays authoritative
            # for everything else, and a later run re-creates these from scratch.
            for resource, key in deleted_keys:
                self.state["objects"].get(resource, {}).pop(key, None)
            self._flush()
            return summary
        if not summary["errors"]:
            for path in (self.store_path, self.mapping_path, self.store_dir / "failures.json"):
                if path.exists():
                    path.unlink()
        return summary


def _verify_markdown(report: dict) -> str:
    """Short, PII-free markdown summary of a verify run."""
    summary = report["summary"]
    lines = [
        "# Live store verification",
        "",
        "Read-only comparison of the load ledger with the Shopify store. Written by",
        "`python3 scripts/migration/shopify_target.py verify --store <ledger>`.",
        "This file lives beside the ledger under `exports/` and is never committed.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Generated | {report['generated_at']} |",
        f"| Store | `{report['store']}` |",
        f"| Admin API version | `{report['api_version']}` |",
        f"| Ledger rows | {report['ledger_rows']} |",
        f"| Distinct ids checked | {report['checked']} |",
        f"| Found on the store | {report['live_found']} |",
        f"| Admin API calls | {summary['api_calls']} |",
        "",
        "| Check | Count |",
        "|---|---:|",
        f"| Missing on the store | **{summary['missing']}** |",
        f"| Products with a different variant count | **{summary['variant_count_mismatch']}** |",
        f"| Products with handle/title/status drift | {summary['field_drift']} |",
        f"| Media not in READY state | {summary['media_not_ready']} |",
        "",
        "## Ledger objects by resource",
        "",
        "| Resource | Count |",
        "|---|---:|",
    ]
    for resource, count in sorted(report["ledger_counts"].items()):
        lines.append(f"| {resource} | {count} |")
    if report["missing"]:
        lines += ["", "## Missing on the store", "", "| Resource | Key |", "|---|---|"]
        lines += [f"| {row['resource']} | `{row['key']}` |" for row in report["missing"]]
    if report["variant_count_mismatch"]:
        lines += ["", "## Variant count mismatches", "",
                  "| Product | Ledger | Live |", "|---|---:|---:|"]
        lines += [f"| `{row['handle']}` | {row['ledger_variants']} | {row['live_variants']} |"
                  for row in report["variant_count_mismatch"]]
    if report["field_drift"]:
        lines += ["", "## Field drift", "", "| Product | Field | Ledger | Live | Note |",
                  "|---|---|---|---|---|"]
        for row in report["field_drift"]:
            for field, values in sorted(row["fields"].items()):
                lines.append(f"| `{row['handle']}` | {field} | {values['ledger']} | "
                             f"{values['live']} | {row.get('note') or ''} |")
    if report["media_not_ready"]:
        lines += ["", "## Media not READY", "", "| Key | Status |", "|---|---|"]
        lines += [f"| `{row['key']}` | {row['status']} |" for row in report["media_not_ready"]]
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI: staging resets and read-only verification
# ---------------------------------------------------------------------------

def main(argv):
    import argparse
    parser = argparse.ArgumentParser(description="Live Shopify target maintenance")
    parser.add_argument("command", choices=["purge", "status", "verify"])
    parser.add_argument("--store", required=True, help="ledger directory used by the live load")
    parser.add_argument("--yes", action="store_true", help="actually delete (purge defaults to a dry run)")
    parser.add_argument("--no-checksums", action="store_true",
                        help="verify: skip the handle/title/status drift comparison")
    parser.add_argument("--batch", type=int, default=NODE_BATCH,
                        help=f"verify: ids per nodes() query (default {NODE_BATCH})")
    parser.add_argument("--only-types", default=None,
                        help="purge: comma-separated subset to delete and forget, keeping the rest of "
                             "the ledger. Names: customers, discounts, pages, articles, files, "
                             "products, collections")
    args = parser.parse_args(argv[1:])
    target = ShopifyAdminTarget(Path(args.store))
    if args.command == "status":
        print(json.dumps({"store": target.store_domain, "objects": target.counts()}, indent=2))
        return 0
    if args.command == "verify":
        report = target.verify(checksums=not args.no_checksums, batch_size=args.batch)
        print(json.dumps({k: v for k, v in report.items()
                          if k not in ("missing", "variant_count_mismatch", "field_drift",
                                       "media_not_ready")}, indent=2))
        for name in ("missing", "variant_count_mismatch", "field_drift", "media_not_ready"):
            if report[name]:
                print(f"{name}: {json.dumps(report[name], indent=2)}")
        print(f"reports: {target.store_dir / 'verify-result.json'}, "
              f"{target.store_dir / 'verify-report.md'}")
        return 1 if (report["summary"]["missing"] or report["summary"]["variant_count_mismatch"]) else 0
    only = None
    if args.only_types:
        names = {"customers": "Customer", "discounts": "DiscountCodeNode", "pages": "Page",
                 "articles": "Article", "files": "File", "products": "Product",
                 "collections": "Collection"}
        unknown = [n for n in args.only_types.split(",") if n.strip() not in names]
        if unknown:
            parser.error(f"--only-types: unknown {unknown}; choose from {sorted(names)}")
        only = {names[n.strip()] for n in args.only_types.split(",")}
    summary = target.purge(dry_run=not args.yes, only=only)
    print(json.dumps(summary, indent=2))
    return 1 if summary.get("errors") else 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
