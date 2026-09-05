#!/usr/bin/env python3
"""ProSporter WooCommerce -> Shopify migration pipeline (CLNT-305).

    python3 scripts/migration/run.py all
    python3 scripts/migration/run.py transform --run-id 2026-09-05a
    python3 scripts/migration/run.py all --source scripts/migration/fixtures --target fake
    python3 scripts/migration/run.py prove          # idempotency + controlled delta

Stages: extract, transform, load, reconcile, all, prove, publish.
Every stage is restartable: each writes its output to
exports/migration/<run-id>/ and later stages read it back from there.

`--target fake` (the default) writes to a file-backed fake Admin API under
exports/migration/fake-store/ and makes no network calls. `--target shopify`
loads into the client store through the Admin API and must be paired with
`--live` (and a dedicated `--store` ledger directory). `--skip-types` and
`--only-products` narrow a live load, e.g. a two-product smoke test:

    python3 scripts/migration/run.py all --target shopify --live \
        --store exports/migration/live-store --skip-types customers,discounts \
        --only-products ace-unisex,nago --no-docs

The load never publishes: products are created DRAFT and joined to no sales
channel. Making the catalog visible is the separate `publish` stage, run after
QA. It reads the live publication state first and only writes with `--live`:

    # dry run (default): print the plan, touch nothing
    python3 scripts/migration/run.py publish --store exports/migration/live-store \
        --publication "ProSporter Dev"
    # apply it, and set ACTIVE the products whose WooCommerce status was 'publish'
    python3 scripts/migration/run.py publish --store exports/migration/live-store \
        --publication "ProSporter Dev" --live --activate-published

Read-only verification of a ledger against the store lives in
`shopify_target.py verify --store <ledger>`.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import delta as delta_mod  # noqa: E402
import extract as extract_mod  # noqa: E402
import loader as loader_mod  # noqa: E402
import reconcile as reconcile_mod  # noqa: E402
import transform as transform_mod  # noqa: E402
from common import (  # noqa: E402
    DEFAULT_SOURCE,
    DEFAULT_STORE,
    DOCS_OUT,
    MIGRATION_OUT,
    PIPELINE_VERSION,
    RECORD_TYPES,
    SHOPIFY_API_VERSION,
    git_rev,
    rel,
    read_jsonl,
    utc_now,
    write_json,
    write_jsonl,
)
from errors import ExceptionCollector  # noqa: E402

STAGES = ("extract", "transform", "load", "reconcile", "all", "prove", "publish")


def default_run_id() -> str:
    return "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ProSporter migration pipeline")
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--source", default=str(DEFAULT_SOURCE),
                        help="directory holding the raw WooCommerce JSON exports")
    parser.add_argument("--target", default="fake", choices=["fake", "shopify", "shopify-admin"])
    parser.add_argument("--store", default=None,
                        help="fake-store directory (default exports/migration/fake-store)")
    parser.add_argument("--no-docs", action="store_true",
                        help="skip writing docs/migration/*.md and the exception CSV")
    parser.add_argument("--fail-on-critical", action="store_true",
                        help="exit 2 when the run ends with unresolved critical exceptions")
    parser.add_argument("--reset-store", action="store_true",
                        help="delete the fake store first (a from-scratch load)")
    parser.add_argument("--live", action="store_true",
                        help="required with --target shopify: confirms writes to the real store")
    parser.add_argument("--skip-types", default="",
                        help="comma-separated record types to leave out (e.g. customers,discounts)")
    parser.add_argument("--only-types", default="",
                        help="comma-separated record types to load and nothing else (e.g. metafield_definitions)")
    parser.add_argument("--only-products", default="",
                        help="comma-separated product handles; restricts products and their variants/media/metafields")
    parser.add_argument("--publication", default="ProSporter Dev",
                        help="publish stage: sales channel / publication name")
    parser.add_argument("--activate-published", action="store_true",
                        help="publish stage: also set ACTIVE the products whose source status was 'publish'")
    parser.add_argument("--dry-run", action="store_true",
                        help="publish stage: print the plan and write nothing, even with --live")
    return parser.parse_args(argv)


def run_manifest(run_id, source_dir, source_snapshot, target_name, stages, extra=None):
    manifest = {
        "run_id": run_id,
        "generated_at": utc_now(),
        "pipeline_version": PIPELINE_VERSION,
        "script_commit": git_rev(),
        "source_dir": rel(source_dir),
        "source_snapshot": source_snapshot,
        "shopify_api_version": SHOPIFY_API_VERSION,
        "target": target_name,
        "stages": stages,
    }
    manifest.update(extra or {})
    return manifest


def stage_extract(args, run_dir):
    data = extract_mod.load_source(Path(args.source))
    summary = extract_mod.summarize(data)
    write_json(run_dir / "source-summary.json", summary)
    print(f"[extract] {args.source}: "
          f"{summary['products_total']} products, {summary['variations_total']} variations, "
          f"snapshot {summary['source_snapshot']}")
    return data


def stage_transform(data, exc, run_dir):
    records = transform_mod.transform(data, exc)
    for record_type in RECORD_TYPES:
        count = write_jsonl(run_dir / f"{record_type}.jsonl", records[record_type])
        print(f"[transform] {record_type:<22} {count}")
    return records


def load_records(run_dir):
    return {rt: read_jsonl(run_dir / f"{rt}.jsonl") for rt in RECORD_TYPES}


def stage_load(records, exc, args, run_dir):
    store_dir = Path(args.store) if args.store else DEFAULT_STORE
    if args.reset_store and store_dir.exists():
        shutil.rmtree(store_dir)
    if args.target != "fake":
        if not args.live:
            raise SystemExit("--target shopify writes to the real store; add --live to confirm")
        if args.reset_store:
            raise SystemExit("--reset-store only applies to the fake target; use shopify_target.py purge")
        if store_dir == DEFAULT_STORE:
            raise SystemExit("give the live load its own --store ledger directory (not the fake store)")
    target = loader_mod.build_target(args.target, store_dir)
    skip_types = [t for t in args.skip_types.split(",") if t]
    only_types = [t for t in getattr(args, "only_types", "").split(",") if t] or None
    only_products = [h for h in args.only_products.split(",") if h] or None
    result = loader_mod.load(records, target, exc, skip_types=skip_types, only_products=only_products,
                             only_types=only_types)
    write_json(run_dir / "load-result.json", {
        "store_dir": rel(store_dir),
        "stats": result["stats"],
        "per_resource": result["per_resource"],
        "object_counts": result["object_counts"],
        "results": result["results"],
    })
    stats = result["stats"]
    print(f"[load] created={stats['created']} updated={stats['updated']} "
          f"unchanged={stats['unchanged']} failed={stats.get('failed', 0)} -> {store_dir}")
    return target, result


def stage_reconcile(data, records, target, exc, args, run_dir, run_id):
    meta = run_manifest(run_id, args.source, data["_meta"]["source_snapshot"],
                        args.target, ["reconcile"])
    report = reconcile_mod.reconcile(data, records, target, exc, meta)
    reconcile_mod.write_run_report(run_dir, report)
    if not args.no_docs:
        for path in reconcile_mod.write_docs(report, exc, meta):
            print(f"[reconcile] wrote {path.relative_to(Path.cwd()) if path.is_absolute() else path}")
    summary = report["summary"]
    print(f"[reconcile] {summary['match']} match / {summary['explained']} explained / "
          f"{summary['mismatch']} mismatch of {summary['checks_total']} checks; "
          f"exceptions {summary['exceptions_by_severity']}")
    return report


def stage_publish(args, run_dir, run_id):
    """Step 10: expose the loaded catalog to a sales channel.

    Separate from the load on purpose - the loader never publishes anything, so
    a catalog can be loaded, QA'd and only then made visible. Idempotent: the
    live publication state and product status are read first and anything
    already correct is reported ``unchanged``.
    """
    if not args.store:
        raise SystemExit("publish needs the live load's --store ledger directory")
    store_dir = Path(args.store)
    if store_dir.resolve() == DEFAULT_STORE.resolve():
        raise SystemExit("publish operates on a live ledger, not the fake store")
    if not (store_dir / "store.json").exists():
        raise SystemExit(f"no ledger at {store_dir}/store.json; run the load first")
    live = bool(args.live) and not args.dry_run
    only_products = [h for h in args.only_products.split(",") if h] or None

    from shopify_target import ShopifyAdminTarget  # lazy: keeps dry runs off the network

    target = ShopifyAdminTarget(store_dir)
    result = target.publish(
        args.publication,
        activate_published=bool(args.activate_published),
        only_products=only_products,
        live=live,
    )
    counts, outcomes = result["counts"], result["outcomes"]
    mode = "LIVE" if live else "dry run"
    print(f"[publish] {mode}: publication {result['publication']['name']} on {result['store']}")
    print(f"[publish] plan: {counts['total']} objects, publish={counts['publish']} "
          f"activate={counts['activate']} unchanged={counts['unchanged']} missing={counts['missing']}")
    if not live:
        for item in result["items"]:
            if item["actions"]:
                print(f"[publish]   {item['resource']:<10} {item['key']:<45} "
                      f"{'+'.join(item['actions'])}")
    print(f"[publish] outcomes: published={outcomes['published']} activated={outcomes['activated']} "
          f"unchanged={outcomes['unchanged']} failed={outcomes['failed']} "
          f"-> {store_dir / 'publish-result.json'}")
    write_json(run_dir / "run-manifest.json", run_manifest(
        run_id, args.source, "n/a (publish stage)", "shopify", ["publish"],
        {
            "store_dir": rel(store_dir),
            "publish": {
                "publication": result["publication"],
                "dry_run": result["dry_run"],
                "activate_published": result["activate_published"],
                "only_products": result["only_products"],
                "counts": counts,
                "outcomes": outcomes,
            },
        },
    ))
    return result


def write_exceptions(run_dir, exc):
    write_jsonl(run_dir / "exceptions.jsonl", exc.rows)


def run_all(args, run_id, run_dir, print_header=True):
    exc = ExceptionCollector()
    if print_header:
        print(f"== run {run_id} source={args.source} target={args.target}")
    data = stage_extract(args, run_dir)
    records = stage_transform(data, exc, run_dir)
    target, load_result = stage_load(records, exc, args, run_dir)
    report = stage_reconcile(data, records, target, exc, args, run_dir, run_id)
    write_exceptions(run_dir, exc)
    write_json(run_dir / "run-manifest.json", run_manifest(
        run_id, args.source, data["_meta"]["source_snapshot"], args.target,
        ["extract", "transform", "load", "reconcile"],
        {
            "store_dir": rel(Path(args.store) if args.store else DEFAULT_STORE),
            "record_counts": {rt: len(records[rt]) for rt in RECORD_TYPES},
            "load_stats": load_result["stats"],
            "exceptions_by_severity": exc.by_severity(),
            "reconciliation": report["summary"],
        },
    ))
    return {"data": data, "records": records, "target": target,
            "load": load_result, "report": report, "exceptions": exc}


# --------------------------------------------------------------------------
# Idempotency and delta proof
# --------------------------------------------------------------------------
def stage_prove(args):
    proof_store = MIGRATION_OUT / "proof-store"
    if proof_store.exists():
        shutil.rmtree(proof_store)
    delta_source = MIGRATION_OUT / "delta-source"

    base = argparse.Namespace(**vars(args))
    base.store = str(proof_store)
    base.no_docs = True
    base.reset_store = False
    base.target = "fake"

    print("== proof run 1 (first load)")
    run1_dir = MIGRATION_OUT / "proof-run-1"
    result1 = run_all(base, "proof-run-1", run1_dir, print_header=False)
    snapshot1 = result1["target"].snapshot()

    print("== proof run 2 (identical inputs)")
    run2_dir = MIGRATION_OUT / "proof-run-2"
    result2 = run_all(base, "proof-run-2", run2_dir, print_header=False)
    snapshot2 = result2["target"].snapshot()
    idempotency = diff_snapshots(snapshot1, snapshot2)
    idempotency["load_stats"] = result2["load"]["stats"]

    print("== building controlled delta source")
    delta_info = delta_mod.build_delta_source(Path(args.source), delta_source)
    delta_args = argparse.Namespace(**vars(base))
    delta_args.source = str(delta_source)

    print("== proof run 3 (delta inputs)")
    run3_dir = MIGRATION_OUT / "proof-run-3"
    result3 = run_all(delta_args, "proof-run-3", run3_dir, print_header=False)
    snapshot3 = result3["target"].snapshot()
    delta_diff = diff_snapshots(snapshot2, snapshot3)
    delta_diff["load_stats"] = result3["load"]["stats"]

    proof = {
        "generated_at": utc_now(),
        "script_commit": git_rev(),
        "shopify_api_version": SHOPIFY_API_VERSION,
        "source_dir": rel(args.source),
        "store_dir": rel(proof_store),
        "idempotency": idempotency,
        "delta": {"info": delta_info, "diff": delta_diff},
    }
    write_json(MIGRATION_OUT / "proof.json", proof)
    write_proof_doc(proof)
    print(f"[prove] rerun: {idempotency['created']} new ids, {idempotency['changed']} changed")
    print(f"[prove] delta: {delta_diff['created']} new ids, {delta_diff['changed']} changed")
    return proof


def diff_snapshots(before: dict, after: dict) -> dict:
    created, changed, removed = [], [], []
    for resource, objects in sorted(after.items()):
        previous = before.get(resource, {})
        for key, (gid, digest) in sorted(objects.items()):
            if key not in previous:
                created.append({"resource": resource, "key": key, "id": gid})
            elif previous[key][1] != digest:
                changed.append({"resource": resource, "key": key, "id": gid})
    for resource, objects in sorted(before.items()):
        for key in sorted(objects):
            if key not in after.get(resource, {}):
                removed.append({"resource": resource, "key": key})
    reused = sum(
        1
        for resource, objects in after.items()
        for key, (gid, _digest) in objects.items()
        if before.get(resource, {}).get(key, [None])[0] == gid
    )
    return {
        "created": len(created),
        "changed": len(changed),
        "removed": len(removed),
        "ids_reused": reused,
        "created_records": created,
        "changed_records": changed,
        "removed_records": removed,
    }


def write_proof_doc(proof: dict) -> Path:
    DOCS_OUT.mkdir(parents=True, exist_ok=True)
    path = DOCS_OUT / "idempotency-proof.md"
    idem = proof["idempotency"]
    delta = proof["delta"]["diff"]
    changes = proof["delta"]["info"]["changes"]
    lines = [
        "# Migration dry-run idempotency proof",
        "",
        "Generated by `python3 scripts/migration/run.py prove`. Counts only, no personal data.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Generated | {proof['generated_at']} |",
        f"| Pipeline commit | `{proof['script_commit']}` |",
        f"| Shopify API version | `{proof['shopify_api_version']}` |",
        f"| Source | `{proof['source_dir']}` |",
        f"| Fake store | `{proof['store_dir']}` (git-ignored) |",
        "",
        "## 1. Rerun with identical inputs",
        "",
        "Run 1 loads a fresh fake store. Run 2 replays the same source snapshot into the",
        "same store. A correct pipeline creates nothing and changes nothing.",
        "",
        "| Measure | Value |",
        "|---|---:|",
        f"| Objects created on rerun | **{idem['created']}** |",
        f"| Objects changed on rerun | **{idem['changed']}** |",
        f"| Objects removed on rerun | {idem['removed']} |",
        f"| Destination ids reused | {idem['ids_reused']} |",
        f"| Loader upserts reporting `created` | {idem['load_stats']['created']} |",
        f"| Loader upserts reporting `updated` | {idem['load_stats']['updated']} |",
        f"| Loader upserts reporting `unchanged` | {idem['load_stats']['unchanged']} |",
        "",
        "## 2. Controlled delta",
        "",
        "`exports/migration/delta-source/` is a copy of the source snapshot with exactly",
        "four changes. Only the affected records may move.",
        "",
        "| Change | Source id | From | To |",
        "|---|---|---|---|",
        f"| Product title | {changes['product_title']['woo_id']} | original | original + \" (Delta Test)\" |",
        f"| Variant price | {changes['variant_price']['woo_id']} | {changes['variant_price']['from']} | {changes['variant_price']['to']} |",
        f"| Variant stock | {changes['variant_stock']['woo_id']} | {changes['variant_stock']['from']} | {changes['variant_stock']['to']} |",
        f"| Added variation | {changes['variant_added']['woo_id']} | - | new option value \"Delta\" |",
        "",
        "| Measure | Value |",
        "|---|---:|",
        f"| Objects created | **{delta['created']}** |",
        f"| Objects changed | **{delta['changed']}** |",
        f"| Objects removed | {delta['removed']} |",
        f"| Destination ids reused | {delta['ids_reused']} |",
        "",
        "### Objects created by the delta",
        "",
        "| Resource | Key |",
        "|---|---|",
    ]
    for row in delta["created_records"]:
        lines.append(f"| {row['resource']} | `{row['key']}` |")
    lines += ["", "### Objects changed by the delta", "", "| Resource | Key |", "|---|---|"]
    for row in delta["changed_records"]:
        lines.append(f"| {row['resource']} | `{row['key']}` |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
def main(argv=None):
    args = parse_args(argv)
    if args.stage == "prove":
        stage_prove(args)
        return 0

    run_id = args.run_id or default_run_id()
    run_dir = MIGRATION_OUT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.stage == "publish":
        result = stage_publish(args, run_dir, run_id)
        return 1 if result["outcomes"]["failed"] else 0

    if args.stage == "all":
        result = run_all(args, run_id, run_dir)
        criticals = result["exceptions"].critical_count()
        if args.fail_on_critical and criticals:
            print(f"[gate] {criticals} unresolved critical exceptions", file=sys.stderr)
            return 2
        return 0

    exc = ExceptionCollector()
    exc.extend(read_jsonl(run_dir / "exceptions.jsonl"))

    if args.stage == "extract":
        stage_extract(args, run_dir)
    elif args.stage == "transform":
        data = extract_mod.load_source(Path(args.source))
        exc = ExceptionCollector()  # transform owns its own exception set
        stage_transform(data, exc, run_dir)
        write_exceptions(run_dir, exc)
    elif args.stage == "load":
        records = load_records(run_dir)
        stage_load(records, exc, args, run_dir)
        write_exceptions(run_dir, exc)
    elif args.stage == "reconcile":
        data = extract_mod.load_source(Path(args.source))
        records = load_records(run_dir)
        store_dir = Path(args.store) if args.store else DEFAULT_STORE
        target = loader_mod.build_target(args.target, store_dir)
        stage_reconcile(data, records, target, exc, args, run_dir, run_id)
        write_exceptions(run_dir, exc)

    write_json(run_dir / "run-manifest.json", run_manifest(
        run_id, args.source, "see source-summary.json", args.target, [args.stage],
        {"store_dir": rel(Path(args.store) if args.store else DEFAULT_STORE)},
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
