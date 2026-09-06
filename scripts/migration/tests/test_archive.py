#!/usr/bin/env python3
"""Tests for the historical-order archive (execution plan, Workstream 5).

    python3 -m unittest discover -s scripts/migration/tests

Runs entirely against scripts/migration/fixtures (synthetic, no real customer
data), so CI never needs the git-ignored exports/ directory.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

import archive as archive_mod  # noqa: E402

FIXTURES = PACKAGE / "fixtures"


def read_csv(path: Path):
    """Read a CSV back the way a spreadsheet would: strip the BOM, keep text."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


class ArchiveOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "prosporter-woocommerce-archive-2026-01-05"
        cls.manifest = archive_mod.generate(FIXTURES, cls.out, quiet=True)
        cls.source = archive_mod.load_source(FIXTURES)
        cls.tables = {
            name: read_csv(cls.out / name)
            for name in cls.manifest["record_counts"]
        }

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # --- structure --------------------------------------------------------
    def test_required_files_exist(self):
        for name in [
            "README.md", "manifest.json", "reconciliation.csv", "reconciliation.md",
            "orders.csv", "order-lines.csv", "payments.csv", "refunds.csv",
            "refund-lines.csv", "fulfilments.csv", "fulfilment-lines.csv",
            "customers-reference.csv", "checksums.sha256",
        ]:
            self.assertTrue((self.out / name).is_file(), f"missing {name}")
        self.assertTrue((self.out / "attachments").is_dir())

    def test_csv_files_start_with_a_bom_and_use_crlf(self):
        raw = (self.out / "orders.csv").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "Excel needs the UTF-8 BOM")
        self.assertIn(b"\r\n", raw)

    def test_stable_column_order_with_one_header_row(self):
        with open(self.out / "orders.csv", encoding="utf-8-sig", newline="") as fh:
            header = next(csv.reader(fh))
        self.assertEqual(header, archive_mod.ORDER_COLUMNS)
        self.assertEqual(len(set(header)), len(header), "duplicate column name")

    # --- row counts equal source counts -----------------------------------
    def test_row_counts_match_the_source(self):
        orders = self.source["orders"]
        refunds = self.source["refunds"]
        self.assertEqual(len(self.tables["orders.csv"]), len(orders))
        self.assertEqual(len(self.tables["payments.csv"]), len(orders))
        self.assertEqual(len(self.tables["fulfilments.csv"]), len(orders))
        self.assertEqual(len(self.tables["refunds.csv"]), len(refunds))
        self.assertEqual(
            len(self.tables["refund-lines.csv"]),
            sum(len(r["line_items"]) for r in refunds),
        )
        self.assertEqual(
            len(self.tables["fulfilment-lines.csv"]),
            sum(len(o["line_items"]) for o in orders),
        )
        self.assertEqual(
            len(self.tables["order-lines.csv"]),
            sum(
                len(o["line_items"]) + len(o["shipping_lines"]) + len(o["fee_lines"])
                for o in orders
            ),
        )
        self.assertEqual(
            len(self.tables["customers-reference.csv"]), len(self.source["customers"])
        )

    def test_manifest_counts_match_the_files(self):
        for name, count in self.manifest["record_counts"].items():
            self.assertEqual(count, len(self.tables[name]), name)

    # --- checksums --------------------------------------------------------
    def test_manifest_checksums_match_the_written_bytes(self):
        self.assertTrue(self.manifest["files"])
        for entry in self.manifest["files"]:
            path = self.out / entry["file"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, entry["sha256"], entry["file"])
            self.assertEqual(path.stat().st_size, entry["bytes"], entry["file"])

    def test_checksums_file_covers_every_archive_file(self):
        listed = {}
        for line in (self.out / "checksums.sha256").read_text().splitlines():
            digest, name = line.split("  ", 1)
            listed[name] = digest
        on_disk = {
            p.relative_to(self.out).as_posix()
            for p in self.out.rglob("*")
            if p.is_file() and p.name not in {"checksums.sha256", "manifest.json"}
        }
        self.assertEqual(set(listed), on_disk)
        for name, digest in listed.items():
            self.assertEqual(
                hashlib.sha256((self.out / name).read_bytes()).hexdigest(), digest, name
            )

    def test_reruns_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            second = Path(tmp) / self.out.name
            archive_mod.generate(FIXTURES, second, quiet=True)
            for name in self.manifest["record_counts"]:
                self.assertEqual(
                    (self.out / name).read_bytes(), (second / name).read_bytes(), name
                )

    # --- CSV injection ----------------------------------------------------
    def test_formula_cells_are_neutralised(self):
        billing_first_names = [r["billing_first_name"] for r in self.tables["orders.csv"]]
        self.assertIn("'=cmd|' /C calc'!A0", billing_first_names)
        companies = [r["billing_company"] for r in self.tables["orders.csv"]]
        self.assertIn("'@fixture", companies)
        addresses = [r["billing_address_1"] for r in self.tables["orders.csv"]]
        self.assertIn("'-2 Fixture Lane", addresses)
        names = [r["product_name"] for r in self.tables["order-lines.csv"]]
        self.assertIn("'+Fixture Cap", names)

        # Nothing that a spreadsheet would evaluate survives in any file.
        for name, rows in self.tables.items():
            for row in rows:
                for column, value in row.items():
                    if value and value[0] in ("=", "+", "@", "\t", "\r"):
                        self.fail(f"unneutralised cell in {name}.{column}: {value!r}")
                    if value.startswith("-"):
                        self.assertRegex(
                            value, r"^-\d+(\.\d+)?$",
                            f"unneutralised leading dash in {name}.{column}",
                        )

    def test_numeric_cells_stay_numeric(self):
        # Negative money must not be apostrophe-prefixed or it stops being a number.
        totals = [r["line_total"] for r in self.tables["refund-lines.csv"]]
        self.assertIn("-37.50", totals)
        quantities = [r["quantity"] for r in self.tables["refund-lines.csv"]]
        self.assertIn("-1", quantities)
        self.assertEqual(archive_mod.neutralise("-12.50"), "-12.50")
        self.assertEqual(archive_mod.neutralise("=1+1"), "'=1+1")
        self.assertEqual(archive_mod.neutralise("-1-1"), "'-1-1")
        self.assertEqual(archive_mod.neutralise(None), "")

    # --- relationships ----------------------------------------------------
    def test_every_child_row_links_to_an_archived_order(self):
        numbers = {r["order_number"] for r in self.tables["orders.csv"]}
        ids = {r["order_id"] for r in self.tables["orders.csv"]}
        for name in [
            "order-lines.csv", "payments.csv", "refunds.csv", "refund-lines.csv",
            "fulfilments.csv", "fulfilment-lines.csv",
        ]:
            for row in self.tables[name]:
                self.assertIn(row["order_number"], numbers, name)
                self.assertIn(row["order_id"], ids, name)

    def test_refunds_link_to_their_source_order(self):
        refund = self.tables["refunds.csv"][0]
        self.assertEqual(refund["refund_id"], "9101")
        self.assertEqual(refund["order_number"], "9001")
        self.assertEqual(refund["order_id"], "9001")
        self.assertEqual(refund["refund_type"], "partial")
        self.assertEqual(refund["currency"], "AUD")
        self.assertEqual(
            {r["refund_id"] for r in self.tables["refund-lines.csv"]},
            {r["refund_id"] for r in self.tables["refunds.csv"]},
        )

    def test_order_number_is_used_even_when_it_differs_from_the_id(self):
        by_id = {r["order_id"]: r for r in self.tables["orders.csv"]}
        self.assertEqual(by_id["9003"]["order_number"], "FIX-9003")

    # --- totals reconcile -------------------------------------------------
    def test_totals_reconcile_to_the_source(self):
        orders = self.source["orders"]
        source_total = sum(Decimal(o["total"]) for o in orders)
        archive_total = sum(Decimal(r["order_total"]) for r in self.tables["orders.csv"])
        self.assertEqual(source_total, archive_total)

        source_refunds = sum(Decimal(r["amount"]) for r in self.source["refunds"])
        archive_refunds = sum(
            abs(Decimal(r["amount"])) for r in self.tables["refunds.csv"]
        )
        self.assertEqual(source_refunds, archive_refunds)
        self.assertEqual(
            sum(Decimal(r["refunded_total"]) for r in self.tables["orders.csv"]),
            source_refunds,
        )
        self.assertEqual(
            sum(Decimal(r["net_total"]) for r in self.tables["orders.csv"]),
            source_total - source_refunds,
        )

    def test_reconciliation_has_no_unexplained_discrepancy(self):
        summary = self.manifest["summary"]
        self.assertEqual(summary["unexplained_discrepancies"], 0)
        self.assertEqual(summary["orders"], len(self.source["orders"]))
        self.assertEqual(set(summary["orphans"].values()), {0})
        for row in self.tables["reconciliation.csv"]:
            if row["source_value"] != row["archive_value"]:
                self.assertTrue(row["notes"], f"undocumented difference: {row}")

    def test_reconciliation_markdown_reports_the_source_count(self):
        body = (self.out / "reconciliation.md").read_text(encoding="utf-8")
        self.assertIn(f"Source orders: **{len(self.source['orders'])}**", body)
        self.assertIn("Unexplained discrepancies: **0**", body)

    # --- data rules -------------------------------------------------------
    def test_dates_are_iso_8601_with_an_offset(self):
        for row in self.tables["orders.csv"]:
            for column in ("date_created", "date_paid", "date_completed"):
                value = row[column]
                if value:
                    self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

    def test_money_is_a_plain_decimal_with_a_separate_currency_column(self):
        for row in self.tables["orders.csv"]:
            self.assertRegex(row["order_total"], r"^-?\d+\.\d{2}$")
            self.assertEqual(row["currency"], "AUD")

    def test_missing_values_are_empty_cells(self):
        by_id = {r["order_id"]: r for r in self.tables["orders.csv"]}
        cancelled = by_id["9003"]
        self.assertEqual(cancelled["date_paid"], "")
        self.assertEqual(cancelled["date_completed"], "")
        self.assertEqual(cancelled["customer_id"], "")

    def test_line_types_and_variant_options(self):
        rows = self.tables["order-lines.csv"]
        self.assertEqual(
            {r["line_type"] for r in rows}, {"line_item", "shipping", "fee"}
        )
        tee = next(r for r in rows if r["sku"] == "FIX-TEE-M")
        self.assertEqual(tee["variant"], "Size: M")  # internal _meta keys dropped
        self.assertEqual(tee["line_discount"], "5.00")
        self.assertEqual(tee["line_subtotal"], "80.00")
        self.assertEqual(tee["line_total"], "75.00")

    def test_payment_status_and_reference(self):
        by_id = {r["order_id"]: r for r in self.tables["payments.csv"]}
        self.assertEqual(by_id["9001"]["payment_status"], "partially-refunded")
        self.assertEqual(by_id["9001"]["transaction_reference"], "pi_fixture_0001")
        self.assertEqual(by_id["9001"]["gateway_method_title"], "Stripe")
        self.assertEqual(by_id["9002"]["payment_status"], "paid")
        self.assertEqual(by_id["9003"]["payment_status"], "cancelled")

    def test_fulfilments_record_what_the_source_has_and_flag_what_it_does_not(self):
        by_id = {r["order_id"]: r for r in self.tables["fulfilments.csv"]}
        self.assertEqual(by_id["9001"]["fulfilment_status"], "fulfilled")
        self.assertEqual(by_id["9001"]["fulfilment_date"], "2026-01-03T02:00:00+00:00")
        self.assertEqual(by_id["9001"]["delivery_type"], "shipped")
        self.assertEqual(by_id["9002"]["delivery_type"], "pickup")
        self.assertEqual(by_id["9003"]["fulfilment_status"], "not-fulfilled (cancelled)")
        # No shipment-tracking data exists in the WooCommerce export.
        for row in self.tables["fulfilments.csv"]:
            self.assertEqual(row["carrier"], "")
            self.assertEqual(row["tracking_number"], "")

    def test_attachments_gap_is_documented(self):
        self.assertEqual(self.manifest["attachments"], [])
        readme = (self.out / "attachments" / "README.md").read_text(encoding="utf-8")
        self.assertIn("no invoice", readme.lower())

    def test_manifest_records_provenance(self):
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["not_loaded_into_shopify"])
        self.assertEqual(manifest["source_snapshot"], "2026-01-05T00:05:00+00:00")
        self.assertTrue(manifest["generated_at"])
        self.assertTrue(manifest["generator_commit"])
        self.assertEqual(manifest["csv_conventions"]["encoding"], "utf-8-sig")


class SourceGuards(unittest.TestCase):
    def test_missing_source_directory_is_reported(self):
        with self.assertRaises(archive_mod.SourceMissing):
            archive_mod.load_source(Path("/nonexistent/source/dir"))

    def test_missing_required_file_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "orders.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(archive_mod.SourceMissing):
                archive_mod.load_source(Path(tmp))


if __name__ == "__main__":
    unittest.main()
