#!/usr/bin/env python3
"""Verify docs/redirects/redirect-map.csv against a running server (CLNT-175).

    python3 scripts/redirects/verify_redirects.py [--base-url http://localhost:3120]

Assertions, one request per row (redirects are never followed automatically, so a
chain shows up as a chain):

  * ``301``       -> the source answers 301/308 with the exact expected Location in
                     ONE hop, and the destination then answers 200.
  * ``same_url``  -> the source answers 200.
  * ``410``       -> the source answers 410. A 404 is reported as "not yet
                     implemented" (gone.json is not wired to a route handler yet).
  * ``client_decision`` -> skipped, counted.

A destination that 404s only because the prototype has not built that route or
does not carry that product in its mock catalog is recorded as
``destination_not_built`` and does not fail the run. Anything else fails.

Results are written to docs/redirects/verification-report.md. Exit code is 1 when
there is at least one real failure. Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MAP_CSV = os.path.join(ROOT, "docs", "redirects", "redirect-map.csv")
REPORT = os.path.join(ROOT, "docs", "redirects", "verification-report.md")
MOCK_CATALOG = os.path.join(ROOT, "mock-data", "catalog.json")

# Routes the approved IA calls for but the prototype has not built yet.
UNBUILT_PREFIXES = (
    "/blog",
    "/about",
    "/contact",
    "/faq",
    "/size-guide",
    "/privacy-policy",
    "/refund-policy",
    "/terms-of-service",
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(url: str):
    """Return (status, location) without following redirects."""
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "prosporter-redirect-verifier"})
    try:
        with OPENER.open(req, timeout=20) as resp:
            return resp.status, resp.headers.get("Location")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location") if exc.headers else None
    except Exception as exc:  # network / server down
        return None, f"error: {exc}"


def strip_base(location: str | None, base: str) -> str | None:
    if location is None:
        return None
    if location.startswith(base):
        location = location[len(base) :] or "/"
    return location


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:3120")
    parser.add_argument("--map", default=MAP_CSV)
    parser.add_argument("--report", default=REPORT)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    with open(args.map, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    mock_slugs: set[str] = set()
    if os.path.exists(MOCK_CATALOG):
        with open(MOCK_CATALOG, encoding="utf-8") as fh:
            mock_slugs = {p["slug"] for p in json.load(fh)}

    def unbuilt(path: str) -> str | None:
        """Why a 404 on `path` is expected in the prototype, or None."""
        for prefix in UNBUILT_PREFIXES:
            if path == prefix or path.startswith(prefix + "/"):
                return f"`{prefix}` route is not built in the prototype yet"
        if path.startswith("/product/"):
            slug = path.rsplit("/", 1)[-1]
            if slug not in mock_slugs:
                return "product is not in the prototype mock catalog (94 of 141 products)"
        return None

    results = []
    dest_cache: "OrderedDict[str, int | None]" = OrderedDict()

    def dest_status(path: str):
        if path not in dest_cache:
            status, _ = fetch(base + path)
            dest_cache[path] = status
        return dest_cache[path]

    for row in rows:
        source = row["source_path"]
        outcome = row["outcome"]
        dest = row["destination"]
        entry = {
            "source": source,
            "outcome": outcome,
            "destination": dest,
            "result": "",
            "detail": "",
        }

        if outcome == "client_decision":
            entry["result"] = "skipped"
            entry["detail"] = "no destination assigned; blocked on the client"
            results.append(entry)
            continue

        if "?" in source:
            entry["result"] = "skipped"
            entry["detail"] = (
                "query-only source; not expressible as a next.config.ts path redirect"
            )
            results.append(entry)
            continue

        status, location = fetch(base + source)
        if status is None:
            entry["result"] = "fail"
            entry["detail"] = f"no response from {base}{source} ({location})"
            results.append(entry)
            continue

        if outcome == "301":
            if status not in (301, 308):
                entry["result"] = "fail"
                entry["detail"] = f"expected 301/308, got {status}"
            else:
                got = strip_base(location, base)
                if got != dest:
                    entry["result"] = "fail"
                    entry["detail"] = f"Location was {got!r}, expected {dest!r}"
                else:
                    ds = dest_status(dest)
                    if ds == 200:
                        entry["result"] = "pass"
                        entry["detail"] = f"{status} -> {dest} (200) in one hop"
                    elif ds in (301, 308, 307, 302):
                        entry["result"] = "fail"
                        entry["detail"] = f"destination {dest} itself redirects ({ds}): chain"
                    elif ds == 404 and unbuilt(dest):
                        entry["result"] = "destination_not_built"
                        entry["detail"] = f"{status} -> {dest} (404): {unbuilt(dest)}"
                    else:
                        entry["result"] = "fail"
                        entry["detail"] = f"destination {dest} returned {ds}"

        elif outcome == "same_url":
            if status == 200:
                entry["result"] = "pass"
                entry["detail"] = "200"
            elif status == 404 and unbuilt(source):
                entry["result"] = "destination_not_built"
                entry["detail"] = f"404: {unbuilt(source)}"
            else:
                entry["result"] = "fail"
                entry["detail"] = f"expected 200, got {status}"

        elif outcome == "410":
            if status == 410:
                entry["result"] = "pass"
                entry["detail"] = "410"
            elif status == 404:
                entry["result"] = "not_implemented"
                entry["detail"] = (
                    "404: gone.json is not wired to a route handler yet, so the path "
                    "falls through to the 404 page"
                )
            else:
                entry["result"] = "fail"
                entry["detail"] = f"expected 410, got {status}"

        results.append(entry)

    counts = Counter(r["result"] for r in results)
    failures = [r for r in results if r["result"] == "fail"]

    # Trailing-slash behaviour. Every real legacy URL ends in "/", and Next.js
    # normalizes that away with its own 308 before redirect matching, so measure
    # how many rows cost an extra hop when requested in their original form.
    slash_extra_hop = 0
    slash_direct = 0
    slash_other = []
    for row in rows:
        source = row["source_path"]
        if row["outcome"] not in ("301", "same_url") or "?" in source or source == "/":
            continue
        status, location = fetch(base + source + "/")
        got = strip_base(location, base)
        if status in (301, 308) and got == source:
            slash_extra_hop += 1
        elif status == 200 or (status in (301, 308) and got == row["destination"]):
            slash_direct += 1
        else:
            slash_other.append((source + "/", status, got))

    # Loop / chain check on the map itself, independent of the server.
    by_source = {r["source_path"]: r for r in rows}
    map_problems = []
    for row in rows:
        if row["outcome"] != "301":
            continue
        target = by_source.get(row["destination"])
        if target is not None and target["outcome"] == "301":
            map_problems.append(
                f"chain: {row['source_path']} -> {row['destination']} -> {target['destination']}"
            )
        if row["destination"] == row["source_path"]:
            map_problems.append(f"loop: {row['source_path']}")

    lines = []
    a = lines.append
    a("# Redirect verification report")
    a("")
    a(f"Base URL: `{base}`  ")
    a(f"Map: `docs/redirects/redirect-map.csv` ({len(rows)} rows)  ")
    a("Generated by `scripts/redirects/verify_redirects.py`. Redirects are never")
    a("followed, so any chain shows up as a chain.")
    a("")
    a("| Result | Count | Meaning |")
    a("|---|---:|---|")
    a(f"| pass | {counts.get('pass', 0)} | Behaved exactly as the map says |")
    a(f"| destination_not_built | {counts.get('destination_not_built', 0)} | Redirect/status is correct; the destination 404s because the prototype has not built that route or product yet |")
    a(f"| not_implemented | {counts.get('not_implemented', 0)} | 410 row that currently 404s (`gone.json` is not wired to a route handler yet) |")
    a(f"| skipped | {counts.get('skipped', 0)} | `client_decision` rows and query-only sources |")
    a(f"| **fail** | **{counts.get('fail', 0)}** | Real problem |")
    a("")
    a(f"Static map check (loops and chains): {'**' + str(len(map_problems)) + ' problem(s)**' if map_problems else 'clean'}")
    if map_problems:
        a("")
        for p in map_problems:
            a(f"- {p}")
    a("")

    if failures:
        a("## Failures")
        a("")
        a("| Source | Outcome | Destination | Detail |")
        a("|---|---|---|---|")
        for r in failures:
            a(f"| `{r['source']}` | {r['outcome']} | `{r['destination'] or '-'}` | {r['detail']} |")
        a("")
    else:
        a("## Failures")
        a("")
        a("None.")
        a("")

    nb = [r for r in results if r["result"] == "destination_not_built"]
    a("## Destinations not built yet")
    a("")
    if nb:
        a(f"{len(nb)} rows. The redirect itself is correct; the target route does not exist")
        a("in the prototype. These become passes once the content routes and the full")
        a("Shopify catalog land.")
        a("")
        grouped: Counter[str] = Counter(r["detail"].split(": ", 1)[-1] for r in nb)
        a("| Reason | Rows |")
        a("|---|---:|")
        for reason, n in sorted(grouped.items()):
            a(f"| {reason} | {n} |")
        a("")
        a("<details><summary>Full list</summary>")
        a("")
        a("| Source | Destination |")
        a("|---|---|")
        for r in sorted(nb, key=lambda x: x["source"]):
            a(f"| `{r['source']}` | `{r['destination'] or r['source']}` |")
        a("")
        a("</details>")
    else:
        a("None.")
    a("")

    a("## Trailing slash")
    a("")
    a("Every legacy URL on the WordPress site ends in `/`. Next.js normalizes the")
    a("trailing slash with its own 308 **before** it matches `redirects()`, and a")
    a("`source` written with a trailing slash is unreachable (verified: it 404s without")
    a("the slash and only ever 308s to the slash-free form). So sources are stored")
    a("slash-free, which is the only form that matches.")
    a("")
    a(f"- Rows that cost one extra normalization hop when requested as `/path/`: **{slash_extra_hop}**")
    a(f"- Rows that reach their destination or a 200 directly from `/path/`: {slash_direct}")
    if slash_other:
        a(f"- Unexpected responses: {len(slash_other)}")
        for src, status, got in slash_other[:20]:
            a(f"  - `{src}` -> {status} {got or ''}")
    a("")
    a("The redirect map itself has no chains; this is a platform normalization hop, not")
    a("a redirect chain in the map. To make legacy `/path/` requests land in a single")
    a("hop, strip the trailing slash at the CDN/edge before the request reaches Next.js")
    a("(the execution plan's \"Next.js/edge layer\"). Doing it inside the app instead")
    a("would mean `skipTrailingSlashRedirect: true` plus a proxy that handles both")
    a("forms, which changes trailing-slash behaviour for every route.")
    a("")

    ni = [r for r in results if r["result"] == "not_implemented"]
    a("## 410 rows not yet implemented")
    a("")
    if ni:
        a(f"{len(ni)} rows in `gone.json` currently answer 404 instead of 410. Wire a route")
        a("handler (or proxy) that reads `docs/redirects/gone.json` to close this.")
        a("")
        a("<details><summary>Full list</summary>")
        a("")
        for r in sorted(ni, key=lambda x: x["source"]):
            a(f"- `{r['source']}`")
        a("")
        a("</details>")
    else:
        a("None.")
    a("")

    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(f"pass={counts.get('pass', 0)} "
          f"destination_not_built={counts.get('destination_not_built', 0)} "
          f"not_implemented={counts.get('not_implemented', 0)} "
          f"skipped={counts.get('skipped', 0)} "
          f"fail={counts.get('fail', 0)}")
    print(f"report: {args.report}")
    if map_problems:
        for p in map_problems:
            print("MAP: " + p, file=sys.stderr)
    return 1 if failures or map_problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
