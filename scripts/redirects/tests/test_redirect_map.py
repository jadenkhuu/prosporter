#!/usr/bin/env python3
"""Tests for the redirect map builder's held-product reconciliation (QA D4).

Everything here is synthetic: three invented products, an invented exception
register and an invented load ledger. No export, no customer data, no network.

    python3 -m unittest discover -s scripts/redirects/tests
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import build_redirect_map as build  # noqa: E402
import verify_redirects as verify  # noqa: E402


REGISTER_HEADER = (
    "severity,code,record_type,record_id,record_ref,stage,owner,retry_status,message\n"
)

# Three synthetic products, one per hold signal, plus one clean control.
PRODUCTS = [
    {
        "slug": "synthetic-club-jersey",
        "name": "Synthetic Club ProVolley Jersey",
        "categories": [{"name": "Teamwear"}],
    },
    {
        "slug": "synthetic-plain-jersey",
        "name": "Synthetic Plain Jersey",
        "categories": [{"name": "Jerseys"}],
    },
    {
        "slug": "synthetic-mystery-item",
        "name": "Synthetic Mystery Item",
        "categories": [{"name": "Beach Volleyball"}],
    },
    {
        "slug": "synthetic-loaded-sock",
        "name": "Synthetic Loaded Sock",
        "categories": [{"name": "Socks"}],
    },
]


def same_url_row(slug: str) -> dict:
    path = f"/product/{slug}"
    return {
        "source_path": path,
        "source_type": "product",
        "source_status": "publish",
        "outcome": "same_url",
        "destination": path,
        "status_code": "",
        "owner": "nextjs",
        "reason": "product handle is clean and preserved 1:1 on /product/<slug>",
        "needs_client_decision": "false",
        "evidence": "synthetic",
    }


def write(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def write_ledger(path: str, handles) -> str:
    payload = {"objects": {"Product": {h: {"id": f"gid://synthetic/{h}"} for h in handles}}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


class ExceptionRegisterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def register(self, body: str) -> str:
        return write(os.path.join(self.tmp.name, "exception-register.csv"),
                     REGISTER_HEADER + body)

    def test_blocking_codes_and_critical_severity_are_holds(self):
        path = self.register(
            "high,record_held_from_load,product,101,synthetic-club-jersey,load,purpl,"
            "needs-decision,record has an unresolved blocking exception\n"
            "critical,attribute_needs_decision,product,102,synthetic-plain-jersey,transform,"
            "client,needs-decision,attribute is not clearly variant-defining\n"
        )
        self.assertEqual(
            build.read_exception_holds(path),
            {
                "synthetic-club-jersey": "record_held_from_load:product:101",
                "synthetic-plain-jersey": "attribute_needs_decision:product:102",
            },
        )

    def test_root_cause_reference_wins_over_the_hold_it_produced(self):
        path = self.register(
            "critical,attribute_needs_decision,product,102,synthetic-plain-jersey,transform,"
            "client,needs-decision,attribute is not clearly variant-defining\n"
            "high,record_held_from_load,product,102,synthetic-plain-jersey,load,purpl,"
            "needs-decision,record has an unresolved blocking exception\n"
        )
        self.assertEqual(
            build.read_exception_holds(path)["synthetic-plain-jersey"],
            "attribute_needs_decision:product:102",
        )

    def test_resolved_rows_and_non_blocking_rows_are_not_holds(self):
        path = self.register(
            "high,record_held_from_load,product,101,synthetic-club-jersey,load,purpl,"
            "resolved,record was reloaded after the fix\n"
            "high,option_value_collision,product,102,synthetic-plain-jersey,transform,purpl,"
            "needs-decision,two option values normalize to the same handle\n"
            "critical,load_failed,page,7,synthetic-page,load,purpl,needs-decision,not a product\n"
        )
        self.assertEqual(build.read_exception_holds(path), {})

    def test_missing_register_is_not_an_error(self):
        self.assertEqual(
            build.read_exception_holds(os.path.join(self.tmp.name, "absent.csv")), {}
        )


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_handles_are_read_from_the_first_available_ledger(self):
        second = write_ledger(os.path.join(self.tmp.name, "b.json"), ["only-in-second"])
        first = write_ledger(os.path.join(self.tmp.name, "a.json"), ["only-in-first"])
        handles, path = build.read_loaded_handles((first, second))
        self.assertEqual(handles, {"only-in-first"})
        self.assertTrue(path.endswith("a.json"))

    def test_no_ledger_reports_none_rather_than_an_empty_set(self):
        # An empty set would mark every product held; None means "no signal".
        handles, path = build.read_loaded_handles((os.path.join(self.tmp.name, "nope.json"),))
        self.assertIsNone(handles)
        self.assertIsNone(path)

    def test_absence_from_the_ledger_is_a_hold_on_its_own(self):
        held = build.held_product_handles({}, {"synthetic-loaded-sock"},
                                          {"synthetic-loaded-sock", "synthetic-plain-jersey"})
        self.assertEqual(list(held), ["synthetic-plain-jersey"])
        self.assertEqual(held["synthetic-plain-jersey"]["ref"], "not in the load ledger")

    def test_both_signals_are_recorded_when_both_fire(self):
        held = build.held_product_handles(
            {"synthetic-plain-jersey": "attribute_needs_decision:product:102"},
            {"synthetic-loaded-sock"},
            {"synthetic-loaded-sock", "synthetic-plain-jersey"},
        )
        self.assertEqual(
            held["synthetic-plain-jersey"]["why"],
            ["absent from the load ledger", "exception register"],
        )

    def test_without_a_ledger_the_register_is_the_only_signal(self):
        held = build.held_product_handles(
            {"synthetic-plain-jersey": "attribute_needs_decision:product:102"},
            None,
            {"synthetic-loaded-sock", "synthetic-plain-jersey"},
        )
        self.assertEqual(list(held), ["synthetic-plain-jersey"])


class PrimaryCollectionTest(unittest.TestCase):
    def by_slug(self, slug):
        return next(p for p in PRODUCTS if p["slug"] == slug)

    def test_club_axis_wins(self):
        dest, why = build.primary_collection(self.by_slug("synthetic-club-jersey"))
        self.assertEqual(dest, "/shop/clubs/provolley-academy")
        self.assertIn("club axis", why)

    def test_product_type_from_a_real_category_beats_surface(self):
        dest, why = build.primary_collection(self.by_slug("synthetic-plain-jersey"))
        self.assertEqual(dest, "/shop/jerseys")
        self.assertIn("from category", why)

    def test_surface_is_used_when_the_type_had_to_be_guessed(self):
        dest, why = build.primary_collection(self.by_slug("synthetic-mystery-item"))
        self.assertEqual(dest, "/shop/beach")
        self.assertIn("surface axis", why)

    def test_every_destination_is_a_real_collection_route(self):
        routes = set(build.TYPE_ROUTES.values()) | set(build.SURFACE_ROUTES.values()) \
            | set(build.CLUB_ROUTES.values()) | {build.SHOP_ALL}
        for product in PRODUCTS:
            self.assertIn(build.primary_collection(product)[0], routes)


class ApplyHeldProductsTest(unittest.TestCase):
    def setUp(self):
        self.products_by_slug = {p["slug"]: p for p in PRODUCTS}

    def rows(self):
        rows = [same_url_row(p["slug"]) for p in PRODUCTS]
        rows.append(
            {
                "source_path": "/product/synthetic-draft",
                "source_type": "product",
                "source_status": "draft",
                "outcome": "client_decision",
                "destination": "",
                "status_code": "",
                "owner": "none",
                "reason": "draft product has no public legacy URL",
                "needs_client_decision": "true",
                "evidence": "synthetic",
            }
        )
        rows.append(
            {
                "source_path": "/about",
                "source_type": "page",
                "source_status": "publish",
                "outcome": "same_url",
                "destination": "/about",
                "status_code": "",
                "owner": "nextjs",
                "reason": "content page, path preserved",
                "needs_client_decision": "false",
                "evidence": "synthetic",
            }
        )
        return rows

    def test_held_row_becomes_a_collection_redirect(self):
        rows = self.rows()
        held = {"synthetic-plain-jersey": {"ref": "attribute_needs_decision:product:102",
                                           "why": ["exception register"]}}
        changed = build.apply_held_products(rows, self.products_by_slug, held)
        self.assertEqual([r["source_path"] for r in changed],
                         ["/product/synthetic-plain-jersey"])
        row = changed[0]
        self.assertEqual(row["outcome"], build.HELD_OUTCOME)
        self.assertEqual(row["destination"], "/shop/jerseys")
        self.assertEqual(row["owner"], "nextjs")
        self.assertEqual(row["needs_client_decision"], "true")
        # The exception id is recorded so the hold is traceable back to the register.
        self.assertIn("attribute_needs_decision:product:102", row["reason"])
        self.assertIn("attribute_needs_decision:product:102", row["evidence"])

    def test_only_same_url_product_rows_are_touched(self):
        rows = self.rows()
        held = {
            "synthetic-draft": {"ref": "record_held_from_load:product:103", "why": ["x"]},
            "about": {"ref": "record_held_from_load:product:104", "why": ["x"]},
        }
        self.assertEqual(build.apply_held_products(rows, self.products_by_slug, held), [])
        self.assertEqual(rows[-2]["outcome"], "client_decision")
        self.assertEqual(rows[-1]["outcome"], "same_url")

    def test_loaded_products_keep_same_url(self):
        rows = self.rows()
        build.apply_held_products(rows, self.products_by_slug, {})
        self.assertTrue(all(r["outcome"] == "same_url" for r in rows[:4]))

    def test_the_row_flips_back_once_the_product_loads(self):
        """The hold is recomputed from source every run, never stored."""
        slugs = {p["slug"] for p in PRODUCTS}
        register = {"synthetic-plain-jersey": "attribute_needs_decision:product:102"}
        ledger = slugs - {"synthetic-plain-jersey"}

        held = build.held_product_handles(register, ledger, slugs)
        rows = self.rows()
        self.assertEqual(len(build.apply_held_products(rows, self.products_by_slug, held)), 1)

        # Client answers, the product loads, the register row is resolved.
        held_after = build.held_product_handles({}, slugs, slugs)
        rows_after = self.rows()
        self.assertEqual(build.apply_held_products(rows_after, self.products_by_slug, held_after), [])
        self.assertEqual(rows_after[1]["outcome"], "same_url")
        self.assertEqual(rows_after[1]["destination"], "/product/synthetic-plain-jersey")

    def test_a_held_product_missing_from_the_exports_falls_back_to_shop_all(self):
        rows = [same_url_row("synthetic-ghost")]
        held = {"synthetic-ghost": {"ref": "not in the load ledger", "why": ["x"]}}
        changed = build.apply_held_products(rows, self.products_by_slug, held)
        self.assertEqual(changed[0]["destination"], build.SHOP_ALL)


class VerifierLedgerCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_same_url_rows_naming_unloaded_handles_are_flagged(self):
        rows = [same_url_row("synthetic-loaded-sock"), same_url_row("synthetic-plain-jersey")]
        unloaded = verify.check_same_url_against_ledger(rows, {"synthetic-loaded-sock"})
        self.assertEqual(unloaded, [("/product/synthetic-plain-jersey", "synthetic-plain-jersey")])

    def test_held_rows_are_not_flagged(self):
        row = same_url_row("synthetic-plain-jersey")
        row["outcome"] = build.HELD_OUTCOME
        row["destination"] = "/shop/jerseys"
        self.assertEqual(verify.check_same_url_against_ledger([row], set()), [])

    def test_no_ledger_means_no_finding(self):
        rows = [same_url_row("synthetic-plain-jersey")]
        self.assertEqual(verify.check_same_url_against_ledger(rows, None), [])

    def test_ledger_is_read_from_the_store_objects(self):
        path = write_ledger(os.path.join(self.tmp.name, "store.json"), ["a", "b"])
        handles, _ = verify.load_ledger_handles(path)
        self.assertEqual(handles, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
