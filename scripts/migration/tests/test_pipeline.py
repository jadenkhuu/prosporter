#!/usr/bin/env python3
"""Unit and end-to-end tests for the migration pipeline.

    python3 -m unittest discover -s scripts/migration/tests

Everything runs against scripts/migration/fixtures (synthetic data), so CI never
needs the git-ignored exports/ directory.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

import delta as delta_mod  # noqa: E402
import extract as extract_mod  # noqa: E402
import normalize as N  # noqa: E402
import run as run_mod  # noqa: E402
import transform as transform_mod  # noqa: E402
from errors import ExceptionCollector  # noqa: E402

FIXTURES = PACKAGE / "fixtures"


def build_records():
    data = extract_mod.load_source(FIXTURES)
    exc = ExceptionCollector()
    records = transform_mod.transform(data, exc)
    return data, records, exc


class NormalizationRules(unittest.TestCase):
    """Execution plan section 7."""

    def test_colour_synonyms(self):
        self.assertEqual(N.normalize_colour("Navy Blue"), "Navy")
        self.assertEqual(N.normalize_colour("Gray"), "Grey")
        self.assertEqual(N.normalize_colour("Light Gray"), "Grey")
        self.assertEqual(N.normalize_colour("black"), "Black")
        self.assertEqual(N.normalize_colour("Black / Gray"), "Black / Grey")

    def test_size_synonyms(self):
        self.assertEqual(N.normalize_size("XXL"), "2XL")
        self.assertEqual(N.normalize_size("3X"), "3XL")
        self.assertEqual(N.normalize_size("SM"), "S/M")
        self.assertEqual(N.normalize_size("ML"), "M/L")
        self.assertEqual(N.normalize_size("l"), "L")

    def test_gender_synonyms(self):
        self.assertEqual(N.normalize_gender("Male"), "Men")
        self.assertEqual(N.normalize_gender("Man"), "Men")
        self.assertEqual(N.normalize_gender("Female"), "Women")
        self.assertEqual(N.normalize_gender("women"), "Women")

    def test_numeric_sock_sizes_stay_separate(self):
        self.assertTrue(N.is_numeric_size("36-41"))
        self.assertTrue(N.is_numeric_size("42"))
        self.assertFalse(N.is_numeric_size("2XL"))
        self.assertEqual(N.size_option_name(["36-41", "42-46"]), "Sock Size")
        self.assertEqual(N.size_option_name(["S", "M"]), "Size")
        # Mixed systems cannot be decided automatically.
        self.assertIsNone(N.size_option_name(["S", "36-41"]))

    def test_apparel_sizes_sort_in_wearing_order(self):
        self.assertEqual(
            N.sort_option_values("Size", ["2XL", "S", "M/L", "XS"]),
            ["XS", "S", "M/L", "2XL"],
        )

    def test_product_type_mapping_folds_protective_and_coaching(self):
        self.assertEqual(N.assign_product_type(["Kneepads"], "Knee Pad")[0], "accessories")
        self.assertEqual(N.assign_product_type(["Coaching"], "Coach Board")[0], "accessories")
        self.assertEqual(N.assign_product_type(["T-Shirts"], "Tee"), ("tops", "category"))
        self.assertEqual(N.assign_product_type([], "Beach Shorts")[1], "name-inferred")
        self.assertEqual(N.assign_product_type([], "Zzz")[1], "fallback")

    def test_surface_and_club_axes(self):
        self.assertEqual(N.assign_surface(["Beach Volleyball"], "x"), "beach")
        self.assertEqual(N.assign_surface(["Jerseys"], "x"), "indoor")
        self.assertIsNone(N.assign_surface(["Hoodies"], "x"))
        self.assertEqual(N.assign_clubs(["ProVolley Academy"], "x"), ["provolley-academy"])
        self.assertEqual(N.assign_clubs(["Teamwear"], "x"), ["teamwear"])

    def test_generated_sku_pattern(self):
        self.assertEqual(N.generate_sku(6855, 6858), "PS-6855-6858")


class TransformBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.records, cls.exc = build_records()
        cls.products = {p["handle"]: p for p in cls.records["products"]}
        cls.variants = cls.records["variants"]
        cls.codes = cls.exc.by_code()

    def test_blank_skus_are_generated_and_flagged(self):
        generated = [v for v in self.variants if v["sku_generated"]]
        self.assertEqual({v["sku"] for v in generated}, {"PS-102-1021", "PS-102-1022"})
        self.assertEqual(self.codes["sku_generated"], 2)

    def test_duplicate_sku_is_reported_not_rewritten(self):
        duplicated = [v for v in self.variants if v["sku"] == "FIX-DUP"]
        self.assertEqual(len(duplicated), 2)
        self.assertEqual(self.codes["duplicate_sku"], 1)

    def test_option_limit_routes_to_exception_and_holds_the_product(self):
        jersey = self.products["fixture-provolley-jersey"]
        self.assertTrue(jersey["held"])
        self.assertIn("attribute_needs_decision", " ".join(jersey["held_reasons"]))
        self.assertEqual(self.codes["attribute_needs_decision"], 2)  # Condition and Number
        self.assertLessEqual(len(jersey["options"]), N.SHOPIFY_MAX_OPTIONS)

    def test_colour_and_size_normalisation_on_a_real_product(self):
        tee = self.products["fixture-team-tee"]
        options = {o["name"]: o["values"] for o in tee["options"]}
        self.assertEqual(sorted(options["Colour"]), ["Black", "Navy"])
        self.assertEqual(options["Size"], ["S/M", "2XL"])

    def test_collision_keeps_raw_values(self):
        shorts = self.products["fixture-beach-shorts"]
        values = shorts["options"][0]["values"]
        self.assertEqual(sorted(values), ["Gray", "Light Gray"])
        self.assertEqual(self.codes["option_value_collision"], 1)

    def test_label_attribute_is_demoted_and_product_becomes_single_variant(self):
        hats = self.products["fixture-unisex-hats"]
        self.assertEqual(hats["options"], [])
        variant = [v for v in self.variants if v["product_handle"] == "fixture-unisex-hats"][0]
        self.assertEqual(variant["option_values"], [{"name": "Title", "value": "Default Title"}])
        self.assertEqual(self.codes["attribute_demoted_to_tag"], 1)

    def test_parent_price_fallback(self):
        variant = [v for v in self.variants if v["sku"] == "FIX-HAT"][0]
        self.assertEqual(variant["price"], "25.00")
        self.assertFalse(variant["held"])

    def test_sale_price_becomes_compare_at(self):
        variant = [v for v in self.variants if v["sku"] == "FIX-TEE-NVY-XXL"][0]
        self.assertEqual(variant["price"], "32.00")
        self.assertEqual(variant["compare_at_price"], "40.00")

    def test_products_default_to_draft_and_keep_legacy_tags(self):
        for product in self.records["products"]:
            self.assertEqual(product["status"], "DRAFT")
        self.assertIn("legacy:t-shirts", self.products["fixture-team-tee"]["tags"])

    def test_metafields_use_the_storefront_identifiers(self):
        keys = {(m["namespace"], m["key"]) for m in self.records["metafields"]}
        self.assertIn(("prosporter", "surface"), keys)
        self.assertIn(("prosporter", "club"), keys)
        self.assertIn(("prosporter", "gender"), keys)
        self.assertIn(("migration", "woo_id"), keys)

    def test_administrator_accounts_are_excluded_and_no_consent_is_invented(self):
        self.assertEqual(len(self.records["customers"]), 2)
        for customer in self.records["customers"]:
            self.assertEqual(
                customer["email_marketing_consent"]["state"], "NOT_SUBSCRIBED"
            )

    def test_media_reachability_is_carried_through(self):
        socks = [m for m in self.records["media"] if m["product_handle"] == "fixture-court-socks"][0]
        self.assertFalse(socks["reachable"])
        self.assertEqual(socks["http_status"], 404)
        self.assertTrue(socks["checksum"]["value"])

    def test_functional_pages_are_held(self):
        cart = [p for p in self.records["pages"] if p["handle"] == "cart"][0]
        self.assertTrue(cart["held"])

    def test_advanced_coupon_rules_are_flagged(self):
        discount = self.records["discounts"][0]
        self.assertEqual(discount["value"]["type"], "percentage")
        self.assertTrue(discount["unsupported_rules"])


class EndToEnd(unittest.TestCase):
    """Idempotency and the controlled delta, both on fixtures."""

    @staticmethod
    def _run(args, run_id, run_dir):
        """Run the pipeline without the per-stage console output."""
        with contextlib.redirect_stdout(io.StringIO()):
            return run_mod.run_all(args, run_id, run_dir, print_header=False)

    def _args(self, source, store):
        return argparse.Namespace(
            stage="all", run_id=None, source=str(source), target="fake",
            store=str(store), no_docs=True, reset_store=False, fail_on_critical=False,
            live=False, skip_types="", only_products="", only_types="",
        )

    def test_rerun_creates_nothing_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            args = self._args(FIXTURES, tmp / "store")
            first = self._run(args, "t1", tmp / "t1")
            before = first["target"].snapshot()
            second = self._run(args, "t2", tmp / "t2")
            after = second["target"].snapshot()

            self.assertGreater(second["load"]["stats"]["unchanged"], 0)
            self.assertEqual(second["load"]["stats"]["created"], 0)
            self.assertEqual(second["load"]["stats"]["updated"], 0)
            diff = run_mod.diff_snapshots(before, after)
            self.assertEqual(diff["created"], 0)
            self.assertEqual(diff["changed"], 0)
            self.assertEqual(diff["removed"], 0)

    def test_delta_updates_only_the_changed_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            store = tmp / "store"
            base = self._run(self._args(FIXTURES, store), "d1", tmp / "d1")
            before = base["target"].snapshot()

            info = delta_mod.build_delta_source(FIXTURES, tmp / "delta-source")
            changed = self._run(self._args(tmp / "delta-source", store), "d2", tmp / "d2")
            diff = run_mod.diff_snapshots(before, changed["target"].snapshot())

            # One new variation -> one variant plus its inventory item, and the
            # page that gained a body image -> one new File (CLNT-323).
            self.assertEqual(diff["created"], 3)
            self.assertEqual({r["resource"] for r in diff["created_records"]},
                             {"ProductVariant", "InventoryItem", "File"})
            self.assertEqual(diff["removed"], 0)

            changed_keys = {(r["resource"], r["key"]) for r in diff["changed_records"]}
            product_slug = info["changes"]["product_title"]["slug"]
            price_id = info["changes"]["variant_price"]["woo_id"]
            stock_id = info["changes"]["variant_stock"]["woo_id"]
            page_slug = info["changes"]["page_body_image"]["slug"]
            self.assertIn(("Product", product_slug), changed_keys)
            self.assertIn(("ProductVariant", f"woo:{price_id}"), changed_keys)
            self.assertIn(("ProductVariant", f"woo:{stock_id}"), changed_keys)
            self.assertIn(("InventoryItem", f"woo:{stock_id}"), changed_keys)
            # A rewritten body is a real change: the Page is updated in place.
            self.assertIn(("Page", page_slug), changed_keys)
            # Nothing else moved.
            self.assertEqual(len(changed_keys), 5)

    def test_live_target_needs_credentials_and_never_runs_by_default(self):
        """The live target must refuse to build without Admin credentials and
        must never be selected by a dry run (target defaults to fake)."""
        import loader
        import shopify_admin
        import shopify_target
        args = run_mod.parse_args(["all"])
        self.assertEqual(args.target, "fake")
        self.assertFalse(args.live)
        with tempfile.TemporaryDirectory() as tmp:
            empty_env = {"SHOPIFY_STORE_DOMAIN": "example.myshopify.com"}
            with self.assertRaises(shopify_admin.ShopifyAdminError):
                shopify_target.ShopifyAdminTarget(
                    Path(tmp) / "ledger", client=shopify_admin.AdminClient(env=empty_env)
                ).client.graphql("{ shop { name } }")
            # The ledger refuses to mix stores.
            target = shopify_target.ShopifyAdminTarget(
                Path(tmp) / "ledger", client=shopify_admin.AdminClient(env=empty_env)
            )
            target._flush()
            other = shopify_admin.AdminClient(env={"SHOPIFY_STORE_DOMAIN": "other.myshopify.com"})
            with self.assertRaises(shopify_admin.ShopifyAdminError):
                shopify_target.ShopifyAdminTarget(Path(tmp) / "ledger", client=other)

    def test_only_products_filter_scopes_product_records(self):
        import loader
        with tempfile.TemporaryDirectory() as tmp:
            args = self._args(FIXTURES, Path(tmp) / "store")
            run_id = "filter"
            run_dir = Path(tmp) / run_id
            run_dir.mkdir()
            result = self._run(args, run_id, run_dir)
            handles = sorted(p["handle"] for p in result["records"]["products"] if not p.get("held"))
            keep = handles[:1]
            exc = ExceptionCollector()
            target = loader.FakeShopifyTarget(Path(tmp) / "filtered")
            out = loader.load(result["records"], target, exc, skip_types=["customers", "discounts"],
                              only_products=keep)
            products = [r for r in out["results"] if r["resource"] == "Product"]
            self.assertEqual([r["key"] for r in products], keep)
            self.assertFalse([r for r in out["results"] if r["resource"] in ("Customer", "DiscountCodeNode")])
            for r in out["results"]:
                if r["resource"] in ("ProductVariant", "MediaImage", "InventoryItem"):
                    self.assertIn(r["key"], {r2["key"] for r2 in out["results"]})
            variant_products = {v["product_handle"] for v in result["records"]["variants"]
                                if f"woo:{v['source']['woo_id']}" in {r["key"] for r in out["results"] if r["resource"] == "ProductVariant"}}
            self.assertEqual(variant_products, set(keep))


PUBLICATION_GID = "gid://shopify/Publication/327884112237"


def json_load(path):
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


class PublishStubClient:
    """Minimal stand-in for shopify_admin.AdminClient for the publish stage.

    Answers the publication lookup and the batched ``nodes(ids:)`` state query
    from a dict, and records the aliased mutations the target sends.
    """

    def __init__(self, nodes: dict, domain: str = "stub.myshopify.com"):
        self.domain = domain
        self.nodes = nodes  # gid -> node dict, or None for "gone from the store"
        self.calls = 0
        self.published: list[str] = []
        self.activated: list[str] = []
        self.documents: list[str] = []

    def graphql(self, query, variables=None):
        self.calls += 1
        self.documents.append(query)
        variables = variables or {}
        if query.lstrip().startswith("mutation"):
            result = {}
            for alias, value in variables.items():
                if alias == "pub":
                    continue
                if "publishablePublish" in query:
                    self.published.append(value)
                else:
                    self.activated.append(value["id"])
                    node = self.nodes.get(value["id"])
                    if node:
                        node["status"] = "ACTIVE"
                result[alias] = {"userErrors": []}
            return result
        if "publications(first:" in query:
            return {"publications": {"nodes": [
                {"id": "gid://shopify/Publication/1", "name": "Online Store"},
                {"id": PUBLICATION_GID, "name": "ProSporter Dev"},
            ]}}
        if "nodes(ids:" in query:
            return {"nodes": [self.nodes.get(gid) for gid in variables["ids"]]}
        raise AssertionError(f"unexpected query: {query[:80]}")

    def mutate(self, query, variables, result_key):  # pragma: no cover - unused here
        raise AssertionError("the publish stage batches through graphql()")


def _publishable(gid, typename, handle, status=None, publications=()):
    node = {"id": gid, "__typename": typename, "handle": handle,
            "resourcePublicationsV2": {"nodes": [
                {"isPublished": True, "publication": {"id": p}} for p in publications
            ]}}
    if status:
        node["status"] = status
    return node


class PublishPlanning(unittest.TestCase):
    """The publish stage plans from live state and never activates source drafts."""

    # handle -> (gid, source status, live status or None if gone, already published?)
    PRODUCTS = {
        "live-active": ("gid://shopify/Product/1", "publish", "ACTIVE", True),
        "needs-both": ("gid://shopify/Product/2", "publish", "DRAFT", False),
        "source-draft": ("gid://shopify/Product/3", "draft", "DRAFT", False),
        "gone": ("gid://shopify/Product/4", "publish", None, False),
    }
    COLLECTION_GID = "gid://shopify/Collection/9"

    def _target(self, tmp):
        import shopify_target
        nodes = {}
        for handle, (gid, _src, live_status, published) in self.PRODUCTS.items():
            nodes[gid] = None if live_status is None else _publishable(
                gid, "Product", handle, live_status, (PUBLICATION_GID,) if published else ()
            )
        nodes[self.COLLECTION_GID] = _publishable(self.COLLECTION_GID, "Collection", "tops")
        client = PublishStubClient(nodes)
        target = shopify_target.ShopifyAdminTarget(Path(tmp) / "ledger", client=client)
        objects = target.state["objects"]
        objects["Product"] = {
            handle: {"id": gid, "checksum": "x",
                     "payload": {"handle": handle, "title": handle.title(),
                                 "status": "DRAFT", "source_status": src}}
            for handle, (gid, src, _live, _pub) in self.PRODUCTS.items()
        }
        objects["Collection"] = {
            "tops": {"id": self.COLLECTION_GID, "checksum": "x",
                     "payload": {"handle": "tops", "title": "Tops"}}
        }
        return target, client

    def test_plan_skips_what_is_already_right_and_never_activates_source_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, _client = self._target(tmp)
            plan = target.plan_publish("ProSporter Dev", activate_published=True)
            actions = {i["key"]: i["actions"] for i in plan["items"]}
            self.assertEqual(actions["live-active"], [])            # published and ACTIVE already
            self.assertEqual(actions["needs-both"], ["publish", "activate"])
            self.assertEqual(actions["source-draft"], ["publish"])  # stays DRAFT
            self.assertEqual(actions["tops"], ["publish"])          # collections never activate
            self.assertEqual(actions["gone"], [])                   # missing on the store
            self.assertEqual(plan["counts"],
                             {"total": 5, "publish": 3, "activate": 1, "unchanged": 1, "missing": 1})
            self.assertEqual(plan["publication"]["id"], PUBLICATION_GID)

    def test_without_activate_no_product_status_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, _client = self._target(tmp)
            plan = target.plan_publish("ProSporter Dev", activate_published=False)
            self.assertEqual(plan["counts"]["activate"], 0)
            self.assertFalse([i for i in plan["items"] if "activate" in i["actions"]])

    def test_only_products_narrows_the_plan_and_drops_collections(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, _client = self._target(tmp)
            plan = target.plan_publish("ProSporter Dev", only_products=["needs-both"])
            self.assertEqual([i["key"] for i in plan["items"]], ["needs-both"])

    def test_apply_publishes_and_activates_then_a_rerun_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, client = self._target(tmp)
            result = target.publish("ProSporter Dev", activate_published=True, live=True)
            self.assertEqual(sorted(client.published),
                             sorted([self.COLLECTION_GID, "gid://shopify/Product/2",
                                     "gid://shopify/Product/3"]))
            self.assertEqual(client.activated, ["gid://shopify/Product/2"])
            self.assertEqual(result["outcomes"],
                             {"published": 3, "activated": 1, "unchanged": 1, "failed": 1})
            self.assertFalse(result["dry_run"])
            self.assertTrue((Path(tmp) / "ledger" / "publish-result.json").exists())

            # The store now reflects those writes; a rerun must plan nothing.
            for gid in client.published:
                client.nodes[gid]["resourcePublicationsV2"]["nodes"].append(
                    {"isPublished": True, "publication": {"id": PUBLICATION_GID}})
            rerun = target.plan_publish("ProSporter Dev", activate_published=True)
            self.assertEqual(rerun["counts"]["publish"], 0)
            self.assertEqual(rerun["counts"]["activate"], 0)
            self.assertEqual(rerun["counts"]["unchanged"], 4)

    def test_dry_run_sends_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, client = self._target(tmp)
            result = target.publish("ProSporter Dev", activate_published=True, live=False)
            self.assertTrue(result["dry_run"])
            self.assertEqual(client.published, [])
            self.assertEqual(client.activated, [])
            self.assertFalse([d for d in client.documents if d.lstrip().startswith("mutation")])

    def test_run_py_publish_defaults_to_a_dry_run(self):
        args = run_mod.parse_args(["publish", "--store", "exports/migration/live-store"])
        self.assertEqual(args.stage, "publish")
        self.assertFalse(args.live)
        self.assertFalse(args.activate_published)
        self.assertEqual(args.publication, "ProSporter Dev")


class CollectionStubClient:
    """Stub client for the collection upsert path; fails once per named handle."""

    def __init__(self, fail_handles=(), domain="stub.myshopify.com"):
        self.domain = domain
        self.calls = 0
        self.fail_handles = set(fail_handles)
        self.created: list[str] = []
        self.counter = 0

    def graphql(self, query, variables=None):
        self.calls += 1
        if "collectionByIdentifier" in query:
            return {"collectionByIdentifier": None}
        raise AssertionError(f"unexpected query: {query[:80]}")

    def mutate(self, query, variables, result_key):
        import shopify_admin
        self.calls += 1
        handle = variables["c"]["handle"]
        if handle in self.fail_handles:
            self.fail_handles.discard(handle)
            raise shopify_admin.ShopifyAdminError(
                f"collectionCreate userErrors: handle: simulated Admin API failure for {handle}"
            )
        self.counter += 1
        self.created.append(handle)
        return {"collection": {"id": f"gid://shopify/Collection/{self.counter:03d}"}}


class FailureRecovery(unittest.TestCase):
    """A per-record Admin failure keeps the record out of the ledger, so the next
    run creates exactly that record and nothing else. See
    docs/migration/error-recovery.md."""

    HANDLES = ["collection-a", "collection-b", "collection-c"]
    SKIP = ["metafield_definitions", "products", "variants", "media",
            "variants_inventory", "collection_membership", "metafields",
            "pages", "articles", "customers", "discounts"]

    def _records(self):
        return {"collections": [
            {"handle": handle, "title": handle.replace("-", " ").title(),
             "body_html": "", "seo": {"title": None, "description": None},
             "product_handles": [],
             "source": {"woo_id": None, "woo_type": "collection", "source_snapshot": "t"}}
            for handle in self.HANDLES
        ]}

    def _load(self, store_dir, client):
        import loader
        import shopify_target
        target = shopify_target.ShopifyAdminTarget(store_dir, client=client)
        exc = ExceptionCollector()
        result = loader.load(self._records(), target, exc, skip_types=self.SKIP)
        return target, result, exc

    def test_failed_record_is_retried_on_the_next_run_and_nothing_else_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_dir = Path(tmp) / "ledger"

            first_client = CollectionStubClient(fail_handles=["collection-b"])
            first, run1, exc1 = self._load(store_dir, first_client)
            self.assertEqual(run1["stats"]["created"], 2)
            self.assertEqual(run1["stats"]["failed"], 1)
            self.assertEqual(first_client.created, ["collection-a", "collection-c"])
            # The failed record never entered the ledger.
            self.assertEqual(sorted(first.state["objects"]["Collection"]),
                             ["collection-a", "collection-c"])
            failed = [r for r in exc1.rows if r["code"] == "load_failed"]
            self.assertEqual([r["record"]["ref"] for r in failed], ["collection-b"])
            self.assertEqual(json_load(store_dir / "failures.json")["count"], 1)
            # The ledger is flushed during the run, not only at the end.
            self.assertEqual(sorted(json_load(store_dir / "store.json")["objects"]["Collection"]),
                             ["collection-a", "collection-c"])

            second_client = CollectionStubClient()
            second, run2, exc2 = self._load(store_dir, second_client)
            self.assertEqual(second_client.created, ["collection-b"])  # exactly the failed one
            self.assertEqual(run2["stats"]["created"], 1)
            self.assertEqual(run2["stats"]["unchanged"], 2)
            self.assertEqual(run2["stats"]["updated"], 0)
            self.assertEqual(run2["stats"]["failed"], 0)
            self.assertEqual(sorted(second.state["objects"]["Collection"]), sorted(self.HANDLES))
            self.assertFalse([r for r in exc2.rows if r["code"] == "load_failed"])
            self.assertEqual(json_load(store_dir / "failures.json")["count"], 0)
            # The two already-loaded collections kept their destination ids.
            for handle in ("collection-a", "collection-c"):
                self.assertEqual(second.state["objects"]["Collection"][handle]["id"],
                                 first.state["objects"]["Collection"][handle]["id"])


class DefinitionStubClient:
    """Stub client for the metafield-definition upsert path.

    Records every definition input the target sends and answers the "does this
    definition already exist?" lookup from a set of pre-existing keys.
    """

    def __init__(self, existing=(), domain="stub.myshopify.com"):
        self.domain = domain
        self.calls = 0
        self.existing = set(existing)  # "<namespace>.<key>"
        self.created: list[dict] = []
        self.updated: list[dict] = []
        self.counter = 0

    def graphql(self, query, variables=None):
        self.calls += 1
        if "metafieldDefinitions(" in query:
            key = f"{variables['ns']}.{variables['key']}"
            node = [{"id": f"gid://shopify/MetafieldDefinition/{key}"}] if key in self.existing else []
            return {"metafieldDefinitions": {"nodes": node}}
        raise AssertionError(f"unexpected query: {query[:80]}")

    def mutate(self, query, variables=None, field=None):
        self.calls += 1
        definition = variables["d"]
        if field == "metafieldDefinitionUpdate":
            self.updated.append(definition)
            return {"updatedDefinition": {"id": "gid://shopify/MetafieldDefinition/x"}}
        self.created.append(definition)
        self.counter += 1
        return {"createdDefinition": {"id": f"gid://shopify/MetafieldDefinition/{self.counter:03d}"}}


def definitions_by_key(records):
    return {f"{d['namespace']}.{d['key']}": d for d in records["metafield_definitions"]}


class MetafieldDefinitionShape(unittest.TestCase):
    """The definitions must be pleasant in the admin: pinned, described, and
    rendering as dropdowns via a `choices` validation."""

    def setUp(self):
        _data, self.records, _exc = build_records()
        self.definitions = definitions_by_key(self.records)

    def test_prosporter_definitions_are_pinned_and_migration_is_not(self):
        for key, definition in self.definitions.items():
            with self.subTest(key=key):
                self.assertEqual(definition["pin"], definition["namespace"] == "prosporter")

    def test_every_definition_has_a_merchant_facing_description(self):
        for key, definition in self.definitions.items():
            with self.subTest(key=key):
                self.assertTrue(definition["description"])
        self.assertIn("Do not edit", self.definitions["migration.woo_id"]["description"])

    def test_choices_validation_carries_a_json_array_of_the_ia_values(self):
        import json
        expected = {
            "prosporter.surface": ["beach", "indoor"],
            "prosporter.club": ["inner-west-volley", "provolley-academy", "teamwear"],
            "prosporter.gender": ["Men", "Unisex", "Women"],
        }
        for key, choices in expected.items():
            with self.subTest(key=key):
                validations = self.definitions[key]["validations"]
                self.assertEqual([v["name"] for v in validations], ["choices"])
                self.assertEqual(json.loads(validations[0]["value"]), choices)

    def test_free_form_definitions_carry_no_choices(self):
        for key in ("prosporter.size_guide", "prosporter.personalisation", "migration.woo_id"):
            with self.subTest(key=key):
                self.assertEqual(self.definitions[key]["validations"], [])

    def test_storefront_visible_types_are_unchanged(self):
        """src/lib/shopify/fragments.ts reads these keys; the value shapes must not move."""
        expected = {
            "prosporter.surface": "single_line_text_field",
            "prosporter.club": "list.single_line_text_field",
            "prosporter.gender": "list.single_line_text_field",
            "prosporter.size_guide": "single_line_text_field",
            "prosporter.personalisation": "json",
            "migration.woo_id": "single_line_text_field",
        }
        self.assertEqual({k: d["type"] for k, d in self.definitions.items()}, expected)


class MetafieldChoices(unittest.TestCase):
    """Every value the transform emits must already be a valid choice, or the
    394 values on the live store would be rejected by the updated definitions."""

    def setUp(self):
        _data, self.records, self.exc = build_records()
        self.definitions = definitions_by_key(self.records)

    def _choices(self, namespace, key):
        import json
        validations = self.definitions[f"{namespace}.{key}"]["validations"]
        return json.loads(validations[0]["value"]) if validations else None

    def test_every_emitted_value_is_inside_its_choice_list(self):
        checked = 0
        for row in self.records["metafields"]:
            choices = self._choices(row["namespace"], row["key"])
            if choices is None:
                continue
            values = row["value"] if isinstance(row["value"], list) else [row["value"]]
            for value in values:
                with self.subTest(key=f"{row['namespace']}.{row['key']}", value=value):
                    self.assertIn(value, choices)
                checked += 1
        self.assertGreater(checked, 0)
        self.assertFalse([r for r in self.exc.rows
                          if r["code"] == "metafield_value_outside_choices"])

    def test_choice_lists_come_from_the_ia_mapping(self):
        self.assertEqual(transform_mod.SURFACE_CHOICES,
                         sorted(h for h, _ in N.SURFACE_COLLECTIONS))
        self.assertEqual(transform_mod.CLUB_CHOICES,
                         sorted(h for h, _ in N.CLUB_COLLECTIONS))
        for value in N.GENDER_SYNONYMS.values():
            self.assertIn(value, transform_mod.GENDER_CHOICES)

    def test_a_value_outside_the_choices_raises_rather_than_loading(self):
        exc = ExceptionCollector()
        ctx = argparse.Namespace(exc=exc)
        kept = transform_mod._choice_checked(
            ctx, "some-handle", 101, "club", ["provolley-academy", "not-a-club"])
        self.assertEqual(kept, ["provolley-academy"])
        codes = [r["code"] for r in exc.rows]
        self.assertEqual(codes, ["metafield_value_outside_choices"])
        self.assertEqual(exc.rows[0]["detail"]["rejected"], ["not-a-club"])

    def test_a_scalar_outside_the_choices_is_dropped(self):
        exc = ExceptionCollector()
        ctx = argparse.Namespace(exc=exc)
        self.assertIsNone(
            transform_mod._choice_checked(ctx, "some-handle", 101, "surface", "grass"))
        self.assertEqual([r["code"] for r in exc.rows], ["metafield_value_outside_choices"])


class LiveDefinitionUpsert(unittest.TestCase):
    """The live target sends pin/description/validations on both the create and
    the update path, and a rerun with no change costs no API call."""

    SKIP = ["collections", "products", "variants", "media", "variants_inventory",
            "collection_membership", "metafields", "body_media", "pages", "articles",
            "customers", "discounts"]

    def _load(self, store_dir, client, records):
        import loader
        import shopify_target
        target = shopify_target.ShopifyAdminTarget(store_dir, client=client)
        result = loader.load(records, target, ExceptionCollector(), skip_types=self.SKIP)
        return target, result

    def test_create_update_and_unchanged(self):
        import json
        _data, records, _exc = build_records()
        definitions_only = {"metafield_definitions": records["metafield_definitions"]}
        with tempfile.TemporaryDirectory() as tmp:
            store_dir = Path(tmp) / "ledger"

            client = DefinitionStubClient()
            _target, run1 = self._load(store_dir, client, definitions_only)
            self.assertEqual(run1["stats"]["created"], 6)
            self.assertEqual(len(client.created), 6)
            created = {f"{d['namespace']}.{d['key']}": d for d in client.created}
            surface = created["prosporter.surface"]
            self.assertTrue(surface["pin"])
            self.assertEqual(surface["type"], "single_line_text_field")
            self.assertEqual(surface["access"], {"storefront": "PUBLIC_READ"})
            self.assertEqual(json.loads(surface["validations"][0]["value"]), ["beach", "indoor"])
            self.assertTrue(surface["description"])
            self.assertFalse(created["migration.woo_id"]["pin"])
            self.assertEqual(created["migration.woo_id"]["access"], {"storefront": "NONE"})

            # Rerun with identical records: no mutation at all.
            rerun_client = DefinitionStubClient()
            _target, run2 = self._load(store_dir, rerun_client, definitions_only)
            self.assertEqual(run2["stats"]["unchanged"], 6)
            self.assertEqual(rerun_client.created, [])
            self.assertEqual(rerun_client.updated, [])
            self.assertEqual(rerun_client.calls, 0)

            # A changed definition goes through metafieldDefinitionUpdate, which
            # carries pin and validations (2026-07 MetafieldDefinitionUpdateInput)
            # and never a `type`.
            changed = json.loads(json.dumps(definitions_only))
            for row in changed["metafield_definitions"]:
                row["description"] = row["description"] + " (revised)"
            update_client = DefinitionStubClient()
            _target, run3 = self._load(store_dir, update_client, changed)
            self.assertEqual(run3["stats"]["updated"], 6)
            self.assertEqual(update_client.created, [])
            self.assertEqual(len(update_client.updated), 6)
            updated = {f"{d['namespace']}.{d['key']}": d for d in update_client.updated}
            self.assertNotIn("type", updated["prosporter.gender"])
            self.assertTrue(updated["prosporter.gender"]["pin"])
            self.assertEqual(json.loads(updated["prosporter.gender"]["validations"][0]["value"]),
                             ["Men", "Unisex", "Women"])
            self.assertTrue(updated["prosporter.gender"]["description"].endswith("(revised)"))

    def test_skip_types_can_restrict_a_live_run_to_definitions_only(self):
        """The flag combination the orchestrator uses to apply this change."""
        import loader
        _data, records, _exc = build_records()
        with tempfile.TemporaryDirectory() as tmp:
            client = DefinitionStubClient()
            import shopify_target
            target = shopify_target.ShopifyAdminTarget(Path(tmp) / "ledger", client=client)
            result = loader.load(records, target, ExceptionCollector(), skip_types=self.SKIP)
            self.assertEqual({r["record_type"] for r in result["results"]},
                             {"metafield_definitions"})
            self.assertEqual(sorted(self.SKIP + ["metafield_definitions"]),
                             sorted(rt for rt, _resource, _key in loader.LOAD_ORDER))


class VariantImagePropagation(unittest.TestCase):
    """A colour's photo reaches every size of that colour, own photos win."""

    def test_colour_image_spreads_to_sizes_without_their_own(self):
        class Ctx:
            variations_by_parent = {
                7: [
                    {"id": 1, "sku": "S-BLK-S", "attributes": [{"name": "Colour", "option": "Black"}, {"name": "Size", "option": "S"}],
                     "image": {"src": "https://x/black.png"}},
                    {"id": 2, "sku": "S-BLK-M", "attributes": [{"name": "Colour", "option": "Black"}, {"name": "Size", "option": "M"}]},
                    {"id": 3, "sku": "S-NVY-S", "attributes": [{"name": "Colour", "option": "Navy"}, {"name": "Size", "option": "S"}],
                     "image": {"src": "https://x/navy.png"}},
                    {"id": 4, "sku": "S-NVY-M", "attributes": [{"name": "Colour", "option": "Navy"}, {"name": "Size", "option": "M"}],
                     "image": {"src": "https://x/navy-m.png"}},
                    {"id": 5, "sku": "S-RED-S", "attributes": [{"name": "Colour", "option": "Red"}, {"name": "Size", "option": "S"}]},
                ]
            }
        by_src = transform_mod._variant_images(Ctx(), 7)
        self.assertEqual([r["sku"] for r in by_src["https://x/black.png"]], ["S-BLK-S", "S-BLK-M"])
        self.assertEqual([r["woo_id"] for r in by_src["https://x/black.png"]], [1, 2])
        self.assertEqual([r["sku"] for r in by_src["https://x/navy.png"]], ["S-NVY-S"])
        self.assertEqual([r["sku"] for r in by_src["https://x/navy-m.png"]], ["S-NVY-M"])
        self.assertNotIn("S-RED-S", [r["sku"] for refs in by_src.values() for r in refs])

    def test_products_without_a_colour_option_only_use_own_images(self):
        class Ctx:
            variations_by_parent = {
                8: [
                    {"id": 1, "sku": "K-36", "attributes": [{"name": "Sock Size", "option": "36-41"}],
                     "image": {"src": "https://x/sock.png"}},
                    {"id": 2, "sku": "K-42", "attributes": [{"name": "Sock Size", "option": "42-46"}]},
                ]
            }
        self.assertEqual(transform_mod._variant_images(Ctx(), 8), {"https://x/sock.png": [{"woo_id": 1, "sku": "K-36"}]})


# --------------------------------------------------------------------------
# CLNT-323 - WordPress body images
# --------------------------------------------------------------------------
WP = "https://wp.invalid/wp-content/uploads/2026/01/"
HOSTS = frozenset({"wp.invalid"})
KNOWN = {
    ("wp.invalid", "/wp-content/uploads/2026/01/hero.jpg"): WP + "hero.jpg",
    ("wp.invalid", "/wp-content/uploads/2026/01/size guide.pdf"): WP + "size%20guide.pdf",
}


class BodyImageExtraction(unittest.TestCase):
    """scan() finds every reference; resolve() collapses resized variants."""

    def test_src_srcset_and_href_are_all_found(self):
        import body_media as BM
        html = (
            f'<img src="{WP}hero-300x200.jpg" '
            f'srcset="{WP}hero-300x200.jpg 300w, {WP}hero-768x512.jpg 768w, {WP}hero.jpg 1024w">'
            f'<a href="{WP}size guide.pdf">guide</a>'
            '<a href="https://wp.invalid/about/">not an upload</a>'
            '<img src="https://elsewhere.invalid/wp-content/uploads/x.jpg">'
        )
        found = BM.scan(html, HOSTS)
        self.assertEqual([f["attr"] for f in found],
                         ["src", "srcset", "srcset", "srcset", "href"])
        self.assertEqual(len(found), 5)

    def test_protocol_relative_and_www_and_root_relative_forms(self):
        import body_media as BM
        html = (
            f'<img src="//www.wp.invalid/wp-content/uploads/2026/01/hero.jpg">'
            '<img src="/wp-content/uploads/2026/01/hero.jpg">'
            f'<img src="{WP.replace("https", "http")}hero.jpg">'
        )
        found = BM.scan(html, HOSTS, origin="wp.invalid")
        self.assertEqual(len(found), 3)
        self.assertEqual({BM.canon(f["url"]) for f in found},
                         {("wp.invalid", "/wp-content/uploads/2026/01/hero.jpg")})

    def test_resized_variants_collapse_onto_the_original(self):
        import body_media as BM
        for variant in ("hero-300x200.jpg", "hero-1536x1024.jpg", "hero.jpg"):
            url, resolved = BM.resolve(WP + variant, KNOWN)
            self.assertTrue(resolved, variant)
            self.assertEqual(url, WP + "hero.jpg")

    def test_a_resized_variant_with_no_original_stays_as_written(self):
        import body_media as BM
        url, resolved = BM.resolve(WP + "orphan-1024x512.png", KNOWN)
        self.assertFalse(resolved)
        self.assertEqual(url, WP + "orphan-1024x512.png")

    def test_a_dimension_like_filename_is_not_mistaken_for_a_thumbnail(self):
        import body_media as BM
        # No original in the library, so the URL is left exactly as written.
        url, resolved = BM.resolve(WP + "size-chart-10x10.png", KNOWN)
        self.assertFalse(resolved)
        self.assertEqual(url, WP + "size-chart-10x10.png")

    def test_content_type_splits_images_from_documents(self):
        import body_media as BM
        self.assertEqual(BM.content_type(WP + "hero.jpg"), "IMAGE")
        self.assertEqual(BM.content_type(WP + "guide.pdf"), "FILE")
        self.assertEqual(BM.content_type(WP + "no-extension", "image/png"), "IMAGE")


class BodyImageRewrite(unittest.TestCase):
    CDN = "https://cdn.shopify.com/s/files/1/1/files/hero.jpg?v=1"

    def _map(self):
        import body_media as BM
        return {
            BM.canon(WP + name): self.CDN
            for name in ("hero.jpg", "hero-300x200.jpg", "hero-768x512.jpg")
        }

    def test_src_and_srcset_are_rewritten_and_the_dead_srcset_is_dropped(self):
        import body_media as BM
        html = (
            f'<img src="{WP}hero-300x200.jpg" '
            f'srcset="{WP}hero-300x200.jpg 300w, {WP}hero-768x512.jpg 768w" '
            'sizes="(max-width: 300px) 100vw, 300px" alt="Hero">'
        )
        out, stats = BM.rewrite(html, self._map(), HOSTS)
        self.assertIn(self.CDN, out)
        self.assertNotIn("wp.invalid", out)
        self.assertNotIn("srcset", out)
        self.assertNotIn("sizes=", out)
        self.assertIn('alt="Hero"', out)
        self.assertEqual(stats, {"references": 3, "rewritten": 3, "unrewritten": 0})

    def test_href_links_to_uploads_are_rewritten_too(self):
        import body_media as BM
        cdn = "https://cdn.shopify.com/s/files/1/1/files/guide.pdf?v=2"
        html = f'<a href="{WP}guide.pdf">Size guide</a>'
        out, stats = BM.rewrite(html, {BM.canon(WP + "guide.pdf"): cdn}, HOSTS)
        self.assertEqual(out, f'<a href="{cdn}">Size guide</a>')
        self.assertEqual(stats["rewritten"], 1)

    def test_unmapped_references_are_left_alone_and_counted(self):
        import body_media as BM
        html = f'<img src="{WP}orphan-1024x512.png"><img src="{WP}hero.jpg">'
        out, stats = BM.rewrite(html, self._map(), HOSTS)
        self.assertIn(f"{WP}orphan-1024x512.png", out)
        self.assertEqual(stats, {"references": 2, "rewritten": 1, "unrewritten": 1})

    def test_nothing_else_on_the_page_is_touched(self):
        import body_media as BM
        html = ('<p>Visit <a href="https://wp.invalid/about/">about</a></p>'
                '<img src="https://elsewhere.invalid/photo.jpg">')
        out, stats = BM.rewrite(html, self._map(), HOSTS)
        self.assertEqual(out, html)
        self.assertEqual(stats["references"], 0)

    def test_rewrite_is_stable_when_applied_twice(self):
        import body_media as BM
        html = f'<img src="{WP}hero-300x200.jpg" srcset="{WP}hero.jpg 1024w">'
        once, _ = BM.rewrite(html, self._map(), HOSTS)
        twice, stats = BM.rewrite(once, self._map(), HOSTS)
        self.assertEqual(once, twice)
        self.assertEqual(stats["references"], 0)


class BodyImagePipeline(unittest.TestCase):
    """Transform, load and rerun on the fixture snapshot."""

    def setUp(self):
        self.data, self.records, self.exc = build_records()
        self.files = self.records["body_media"]

    def test_one_file_record_per_unique_original(self):
        names = sorted(f["filename"] for f in self.files)
        self.assertEqual(names, ["orphan-banner-1024x512.png", "size-guide.pdf",
                                 "team-tee-front.jpg"])
        tee = [f for f in self.files if f["filename"] == "team-tee-front.jpg"][0]
        # src + three srcset candidates, collapsed onto one upload.
        self.assertEqual(tee["reference_count"], 4)
        self.assertEqual(len(tee["variants"]), 2)
        self.assertTrue(tee["resolved"])
        self.assertEqual(tee["content_type"], "IMAGE")

    def test_a_pdf_link_is_a_generic_file_not_an_image(self):
        pdf = [f for f in self.files if f["filename"] == "size-guide.pdf"][0]
        self.assertEqual(pdf["content_type"], "FILE")

    def test_an_image_with_no_original_is_reported_but_still_uploaded(self):
        orphan = [f for f in self.files if f["filename"].startswith("orphan")][0]
        self.assertFalse(orphan["resolved"])
        self.assertFalse(orphan["held"])
        self.assertIn("body_image_not_in_media_export",
                      {row["code"] for row in self.exc.rows})

    def test_held_pages_contribute_no_uploads(self):
        cart = [p for p in self.records["pages"] if p["handle"] == "cart"][0]
        self.assertTrue(cart["held"])
        self.assertEqual(cart["body_image_sources"], [])

    def test_load_rewrites_the_body_and_a_rerun_reuses_the_files(self):
        import loader
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"
            target = loader.FakeShopifyTarget(store)
            first = loader.load(self.records, target, ExceptionCollector())
            self.assertEqual(first["body_images"]["records_rewritten"], 1)
            self.assertEqual(first["body_images"]["references"], 6)
            self.assertEqual(first["body_images"]["rewritten"], 6)
            self.assertEqual(len(target.objects("File")), 3)

            body = target.objects("Page")["about-fixture"]["payload"]["body_html"]
            self.assertNotIn("wp-content/uploads", body)
            self.assertIn("cdn.shopify.com", body)
            # The page link that is not an upload survives untouched.
            self.assertIn("https://fixtures.invalid/about-fixture/", body)

            # Rerun against the same ledger: no new files, no page update.
            again = loader.FakeShopifyTarget(store)
            second = loader.load(self.records, again, ExceptionCollector())
            self.assertEqual(second["stats"]["created"], 0)
            self.assertEqual(second["stats"]["updated"], 0)
            self.assertEqual(len(again.objects("File")), 3)
            self.assertEqual(again.objects("Page")["about-fixture"]["payload"]["body_html"], body)

    def test_usage_metadata_stays_out_of_the_ledger_payload(self):
        """Where a file is used must not restamp the file's checksum."""
        import loader
        with tempfile.TemporaryDirectory() as tmp:
            target = loader.FakeShopifyTarget(Path(tmp) / "store")
            loader.load(self.records, target, ExceptionCollector())
            payload = next(iter(target.objects("File").values()))["payload"]
            for field in ("variants", "references", "reference_count"):
                self.assertNotIn(field, payload)
            page = target.objects("Page")["about-fixture"]["payload"]
            for field in ("body_image_refs", "body_image_sources"):
                self.assertNotIn(field, page)

    def test_reconciliation_reports_the_body_image_counts(self):
        import loader
        import reconcile as reconcile_mod
        with tempfile.TemporaryDirectory() as tmp:
            target = loader.FakeShopifyTarget(Path(tmp) / "store")
            loader.load(self.records, target, ExceptionCollector())
            report = reconcile_mod.reconcile(
                self.data, self.records, target, self.exc,
                {"run_id": "t", "generated_at": "now", "source_snapshot": "s",
                 "source_dir": ".", "target": "fake", "shopify_api_version": "2026-07",
                 "script_commit": "x"},
            )
            checks = {c["check"]: c for c in report["checks"]}
            self.assertEqual(checks["body_image_unique_files"]["source"], 3)
            self.assertEqual(checks["body_image_files_uploaded"]["target"], 3)
            self.assertEqual(checks["body_image_unresolvable_sources"]["target"], 1)
            self.assertEqual(
                checks["wordpress_image_references_left_in_loaded_bodies"]["target"], 0)
            self.assertEqual(
                checks["wordpress_image_references_left_in_loaded_bodies"]["status"], "match")


class StaleLedgerStubClient:
    """Answers the read-only ``nodes(ids:)`` liveness lookup and the per-product
    variant read. Any mutation is a test failure: pruning stale ledger rows must
    never write to the store."""

    def __init__(self, live_ids, product_variants=()):
        self.domain = "stub.myshopify.com"
        self.calls = 0
        self.live_ids = set(live_ids)
        self.product_variants = list(product_variants)
        self.mutations: list[str] = []

    def graphql(self, query, variables=None):
        self.calls += 1
        if "nodes(ids:" in query:
            return {"nodes": [{"id": gid, "__typename": "ProductVariant"}
                              if gid in self.live_ids else None
                              for gid in variables["ids"]]}
        if "variants(first:250)" in query:
            return {"product": {"variants": {"nodes": self.product_variants}}}
        raise AssertionError(f"unexpected query: {query[:80]}")

    def mutate(self, query, variables, result_key):
        self.calls += 1
        self.mutations.append(result_key)
        raise AssertionError(f"the prune must not mutate the store ({result_key})")


class StaleLedgerPrune(unittest.TestCase):
    """A ledger row for a variant the transform now holds is dropped only when
    the store proves the row owns nothing: the variant is gone, or its gid still
    belongs to a ledger row that is still loaded (two source variations that
    collapsed onto one Shopify variant). A held row that is the sole owner of a
    live variant is reported, never dropped. See docs/migration/error-recovery.md.
    """

    LEDGER = {
        "api_version": "2026-07",
        "store": "stub.myshopify.com",
        "counters": {},
        "objects": {
            "Product": {"p1": {"id": "gid://shopify/Product/1", "checksum": "c",
                               "payload": {"handle": "p1"}}},
            "ProductVariant": {
                # loaded, live
                "woo:1": {"id": "gid://shopify/ProductVariant/1", "checksum": "c",
                          "payload": {"product_handle": "p1", "sku": "A-1"}},
                # held; collapsed onto woo:1 (same option combination)
                "woo:2": {"id": "gid://shopify/ProductVariant/1", "checksum": "c",
                          "payload": {"product_handle": "p1", "sku": "A-2"}},
                # held; nothing on the store answers for it
                "woo:3": {"id": "gid://shopify/ProductVariant/3", "checksum": "c",
                          "payload": {"product_handle": "p1", "sku": "A-3"}},
                # held; sole owner of a variant that is still live
                "woo:4": {"id": "gid://shopify/ProductVariant/4", "checksum": "c",
                          "payload": {"product_handle": "p1", "sku": "A-4"}},
            },
            "InventoryItem": {
                "woo:1": {"id": "gid://shopify/InventoryItem/1", "checksum": "c",
                          "payload": {"product_handle": "p1"}},
                "woo:2": {"id": "gid://shopify/InventoryItem/1", "checksum": "c",
                          "payload": {"product_handle": "p1"}},
                "woo:3": {"id": "gid://shopify/InventoryItem/3", "checksum": "c",
                          "payload": {"product_handle": "p1"}},
            },
        },
        "aux": {}, "file_urls": {},
    }
    LIVE = {"gid://shopify/ProductVariant/1", "gid://shopify/ProductVariant/4",
            "gid://shopify/InventoryItem/1"}

    def _target(self, tmp, live=None):
        import json as _json
        import shopify_target
        store_dir = Path(tmp) / "ledger"
        store_dir.mkdir(parents=True)
        (store_dir / "store.json").write_text(_json.dumps(self.LEDGER), encoding="utf-8")
        client = StaleLedgerStubClient(self.LIVE if live is None else live)
        return shopify_target.ShopifyAdminTarget(store_dir, client=client), client, store_dir

    def test_stale_rows_are_dropped_and_a_live_held_variant_is_only_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, client, store_dir = self._target(tmp)
            plan = target.stale_variant_plan({"woo:1"})

            dropped = {(r["resource"], r["key"]): r["reason"] for r in plan["drop"]}
            self.assertEqual(dropped, {
                ("ProductVariant", "woo:2"): "collapsed_onto_loaded_variant",
                ("InventoryItem", "woo:2"): "collapsed_onto_loaded_variant",
                ("ProductVariant", "woo:3"): "not_on_store",
                ("InventoryItem", "woo:3"): "not_on_store",
            })
            self.assertEqual([r["key"] for r in plan["variant_live_but_held"]], ["woo:4"])
            self.assertEqual(plan["summary"],
                             {"variants_dropped": 2, "inventory_items_dropped": 2,
                              "live_but_held": 1})
            self.assertFalse(plan["applied"])
            self.assertFalse(client.mutations)
            # A dry plan changes nothing on disk.
            self.assertEqual(len(json_load(store_dir / "store.json")["objects"]["ProductVariant"]), 4)

            target.apply_stale_variant_plan(plan)
            self.assertEqual(sorted(target.state["objects"]["ProductVariant"]),
                             ["woo:1", "woo:4"])
            self.assertEqual(sorted(target.state["objects"]["InventoryItem"]), ["woo:1"])
            # The live-but-held variant keeps its ledger row and its id.
            self.assertEqual(target.state["objects"]["ProductVariant"]["woo:4"]["id"],
                             "gid://shopify/ProductVariant/4")
            self.assertEqual(sorted(json_load(store_dir / "store.json")["objects"]["ProductVariant"]),
                             ["woo:1", "woo:4"])
            self.assertFalse(client.mutations)

    def test_a_loaded_row_is_never_a_candidate_even_when_it_is_missing_on_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, _client, _dir = self._target(tmp, live=set())
            plan = target.stale_variant_plan({"woo:1", "woo:2", "woo:3", "woo:4"})
            self.assertEqual(plan["drop"], [])
            self.assertEqual(plan["candidates"], 0)

    def test_the_scope_leaves_products_this_run_did_not_touch_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, _client, _dir = self._target(tmp)
            plan = target.stale_variant_plan({"woo:1"}, product_keys={"other-product"})
            self.assertEqual(plan["candidates"], 0)
            self.assertEqual(plan["drop"], [])

    def test_finish_prunes_the_ledger_and_reports_the_live_held_variant(self):
        """The self-healing path: a delta run whose transform no longer produces
        the held variants leaves the ledger in step with the store."""
        import loader
        import shopify_target
        from common import checksum
        with tempfile.TemporaryDirectory() as tmp:
            target, client, store_dir = self._target(tmp)
            # The ledger already holds exactly what this run loads, so the
            # upsert is `unchanged` and costs no API call: only the prune talks
            # to the store.
            payload = {"product_handle": "p1", "sku": "A-1",
                       "source": {"woo_id": 1, "woo_type": "product_variation"}}
            row = target.state["objects"]["ProductVariant"]["woo:1"]
            row["payload"], row["checksum"] = payload, checksum(payload)
            records = {"variants": [dict(payload, held=False)]}
            self.assertIsInstance(target, shopify_target.ShopifyAdminTarget)
            exc = ExceptionCollector()
            loader.load(records, target, exc, only_types=["variants"])

            self.assertEqual(sorted(target.state["objects"]["ProductVariant"]),
                             ["woo:1", "woo:4"])
            self.assertEqual(sorted(target.state["objects"]["InventoryItem"]), ["woo:1"])
            self.assertFalse(client.mutations)
            held = [r for r in exc.rows if r["code"] == "variant_live_but_held"]
            self.assertEqual([r["record"]["ref"] for r in held], ["woo:4"])
            self.assertEqual(held[0]["retry_status"], "needs-decision")
            notices = json_load(store_dir / "failures.json")["notices"]
            self.assertEqual([n["key"] for n in notices], ["woo:4"])



if __name__ == "__main__":
    unittest.main()
