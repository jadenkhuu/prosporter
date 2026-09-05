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
            live=False, skip_types="", only_products="",
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

            # One new variation -> one variant plus its inventory item.
            self.assertEqual(diff["created"], 2)
            self.assertEqual({r["resource"] for r in diff["created_records"]},
                             {"ProductVariant", "InventoryItem"})
            self.assertEqual(diff["removed"], 0)

            changed_keys = {(r["resource"], r["key"]) for r in diff["changed_records"]}
            product_slug = info["changes"]["product_title"]["slug"]
            price_id = info["changes"]["variant_price"]["woo_id"]
            stock_id = info["changes"]["variant_stock"]["woo_id"]
            self.assertIn(("Product", product_slug), changed_keys)
            self.assertIn(("ProductVariant", f"woo:{price_id}"), changed_keys)
            self.assertIn(("ProductVariant", f"woo:{stock_id}"), changed_keys)
            self.assertIn(("InventoryItem", f"woo:{stock_id}"), changed_keys)
            # Nothing else moved.
            self.assertEqual(len(changed_keys), 4)

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


if __name__ == "__main__":
    unittest.main()
