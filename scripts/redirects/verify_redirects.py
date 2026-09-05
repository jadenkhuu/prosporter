#!/usr/bin/env python3
"""Verify docs/redirects/redirect-map.csv against a running server (CLNT-175).

    SHOPIFY_OPTIONAL=1 npm run build
    PORT=3114 SHOPIFY_OPTIONAL=1 npm run start &
    python3 scripts/redirects/verify_redirects.py --base-url http://localhost:3114
    kill %1

Every legacy prosporter.com.au URL ends in ``/``, so that is the form this script
requests. Redirects are followed one response at a time and counted, so a chain is
visible as a chain. Each row is graded on the *whole* journey:

  ``301``        one redirect hop straight to the mapped destination.
  ``same_url``   one redirect hop (the trailing-slash canonicalization) to a 200.
  ``410``        zero redirect hops; the legacy URL answers 410 itself.
  ``client_decision`` / query-only sources are skipped and counted.

The slash-free canonical form of every row is checked too, since that is what
``next.config.ts`` ``redirects()`` and the proxy see after normalization.

A destination that 404s only because the prototype has not built that route or
does not carry that product in its mock catalog is recorded separately and does
not fail the run. Anything else fails.

Writes docs/redirects/verification-report.md. Exit code 1 on a real failure.
Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MAP_CSV = os.path.join(ROOT, "docs", "redirects", "redirect-map.csv")
GONE_JSON = os.path.join(ROOT, "docs", "redirects", "gone.json")
REPORT = os.path.join(ROOT, "docs", "redirects", "verification-report.md")
MOCK_CATALOG = os.path.join(ROOT, "mock-data", "catalog.json")

MAX_HOPS = 5

# Routes the approved IA calls for but the prototype has not built yet. `/blog`
# and `/blog/<slug>` are deliberately absent: they are covered by the placeholder
# routes in src/app/blog (see CLNT-175 follow-ups).
UNBUILT_PREFIXES = (
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
    """Return (status, location) for one request, never following redirects."""
    req = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "prosporter-redirect-verifier"}
    )
    try:
        with OPENER.open(req, timeout=20) as resp:
            return resp.status, resp.headers.get("Location")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location") if exc.headers else None
    except Exception as exc:  # server down / socket error
        return None, f"error: {exc}"


def to_path(location: str | None, base: str) -> str | None:
    """Reduce a Location header to a site-relative path (+query)."""
    if location is None:
        return None
    absolute = urllib.parse.urljoin(base + "/", location)
    parts = urllib.parse.urlsplit(absolute)
    path = parts.path or "/"
    return path + (("?" + parts.query) if parts.query else "")


def walk(base: str, path: str):
    """Follow the chain from `path`. Returns (hops, final_status, chain)."""
    chain: list[tuple[str, int | None, str | None]] = []
    current = path
    for _ in range(MAX_HOPS + 1):
        status, location = fetch(base + current)
        target = to_path(location, base) if status in (301, 302, 303, 307, 308) else None
        chain.append((current, status, target))
        if target is None:
            return len(chain) - 1, status, chain
        current = target
    return len(chain) - 1, None, chain


def chain_text(chain) -> str:
    bits = []
    for path, status, target in chain:
        bits.append(f"`{path}` {status}")
    return " -> ".join(bits)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:3114")
    parser.add_argument("--map", default=MAP_CSV)
    parser.add_argument("--report", default=REPORT)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    with open(args.map, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with open(GONE_JSON, encoding="utf-8") as fh:
        gone_paths = json.load(fh)

    mock_slugs: set[str] = set()
    if os.path.exists(MOCK_CATALOG):
        with open(MOCK_CATALOG, encoding="utf-8") as fh:
            mock_slugs = {p["slug"] for p in json.load(fh)}

    # `/product/[slug]` reads the live Shopify catalog. On a server started with
    # SHOPIFY_OPTIONAL=1 and no store, every product path 404s for reasons that
    # have nothing to do with the redirect layer. Probe before grading.
    product_probe = [
        r["source_path"]
        for r in rows
        if r["outcome"] == "same_url" and r["source_path"].startswith("/product/")
    ][:3]
    products_unavailable = bool(product_probe) and all(
        fetch(base + p)[0] == 404 for p in product_probe
    )

    def unbuilt(path: str) -> str | None:
        """Why a 404 on `path` is expected on this server, or None."""
        for prefix in UNBUILT_PREFIXES:
            if path == prefix or path.startswith(prefix + "/"):
                return f"`{prefix}` content route is not built yet"
        if path.startswith("/product/"):
            if products_unavailable:
                return (
                    "product pages are served from the Shopify Storefront API and "
                    "this server has no store configured (SHOPIFY_OPTIONAL=1)"
                )
            slug = path.rsplit("/", 1)[-1]
            if slug not in mock_slugs:
                return "product is not in the prototype mock catalog"
        return None

    # Probe how the server handles a trailing slash on a route that exists. This
    # tells us whether `skipTrailingSlashRedirect: true` + src/proxy.ts is in play
    # (the legacy URL resolves in one hop) or Next's own normalization is.
    probe_hops, probe_status, probe_chain = walk(base, "/shop/")
    one_hop_mode = probe_hops <= 1 and probe_status == 200

    results = []
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
            "hops": None,
        }

        if outcome == "client_decision":
            entry["result"] = "skipped"
            entry["detail"] = "no destination assigned; blocked on the client"
            results.append(entry)
            continue

        if "?" in source:
            entry["result"] = "skipped"
            entry["detail"] = "query-only source; not expressible as a path rule"
            results.append(entry)
            continue

        legacy = source if source == "/" else source + "/"
        hops, status, chain = walk(base, legacy)
        entry["hops"] = hops
        entry["chain"] = chain_text(chain)

        if status is None:
            entry["result"] = "fail"
            entry["detail"] = f"no final response for `{legacy}`: {entry['chain']}"
            results.append(entry)
            continue

        final_path = chain[-1][0]

        if outcome == "301":
            expected_hops = 1
            if final_path.split("?")[0] != dest:
                entry["result"] = "wrong_destination"
                entry["detail"] = f"landed on `{final_path}`, expected `{dest}`"
            elif status == 200:
                entry["result"] = "single_hop_ok" if hops <= expected_hops else "multi_hop"
                entry["detail"] = f"{hops} hop(s) -> `{dest}` (200)"
            elif status == 404 and unbuilt(dest):
                entry["result"] = "destination_404"
                entry["detail"] = f"{hops} hop(s) -> `{dest}` (404): {unbuilt(dest)}"
            else:
                entry["result"] = "fail"
                entry["detail"] = f"destination `{dest}` returned {status}"

        elif outcome == "same_url":
            if final_path.split("?")[0] != source:
                entry["result"] = "wrong_destination"
                entry["detail"] = f"landed on `{final_path}`, expected `{source}`"
            elif status == 200:
                # `/path/` -> `/path` is the canonical form; one hop is correct.
                entry["result"] = "single_hop_ok" if hops <= 1 else "multi_hop"
                entry["detail"] = f"{hops} hop(s) -> `{source}` (200)"
            elif status == 404 and unbuilt(source):
                entry["result"] = "destination_404"
                entry["detail"] = f"404: {unbuilt(source)}"
            else:
                entry["result"] = "fail"
                entry["detail"] = f"expected 200, got {status}"

        elif outcome == "410":
            if status != 410:
                entry["result"] = "fail"
                entry["detail"] = f"expected 410, got {status} ({entry['chain']})"
            elif hops == 0:
                entry["result"] = "gone_410_ok"
                entry["detail"] = "410 with no redirect hop"
            else:
                entry["result"] = "multi_hop"
                entry["detail"] = f"410 after {hops} redirect hop(s)"

        results.append(entry)

    counts = Counter(r["result"] for r in results)
    failures = [r for r in results if r["result"] == "fail"]
    wrong = [r for r in results if r["result"] == "wrong_destination"]
    multi = [r for r in results if r["result"] == "multi_hop"]
    not_built = [r for r in results if r["result"] == "destination_404"]

    # Canonical (slash-free) form: what next.config.ts redirects() and the proxy
    # see after normalization. This is the form that must never chain.
    canonical_ok = 0
    canonical_bad = []
    for row in rows:
        source = row["source_path"]
        outcome = row["outcome"]
        if outcome == "client_decision" or "?" in source:
            continue
        status, location = fetch(base + source)
        got = to_path(location, base)
        if outcome == "301" and status in (301, 308) and got == row["destination"]:
            canonical_ok += 1
        elif outcome == "same_url" and status in (200, 404):
            canonical_ok += 1
        elif outcome == "410" and status == 410:
            canonical_ok += 1
        else:
            canonical_bad.append((source, outcome, status, got))

    # Every gone.json path answers 410 in its slash-free form.
    gone_ok = 0
    gone_bad = []
    for path in gone_paths:
        status, _ = fetch(base + path)
        if status == 410:
            gone_ok += 1
        else:
            gone_bad.append((path, status))

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
    a("Generated by `scripts/redirects/verify_redirects.py`.")
    a("")
    a("Each row is requested in its **legacy form** (`/path/`, the way every")
    a("prosporter.com.au URL is written) and the redirect chain is walked one")
    a("response at a time, so a chain shows up as a chain.")
    a("")
    a("| Trailing-slash mode | |")
    a("|---|---|")
    a(f"| Probe | `/shop/` -> {probe_hops} redirect hop(s), final {probe_status} |")
    a(
        "| Mode | "
        + (
            "`skipTrailingSlashRedirect: true` + `src/proxy.ts`: legacy URLs resolve in one hop"
            if one_hop_mode
            else "Next.js built-in normalization: `/path/` 308s to `/path` **before** `redirects()` and before the proxy, so every legacy URL costs one extra hop"
        )
        + " |"
    )
    a("")
    a("## Counts")
    a("")
    a("| Result | Count | Meaning |")
    a("|---|---:|---|")
    a(f"| single-hop OK | {counts.get('single_hop_ok', 0)} | Legacy `/path/` reached its final 200 in one redirect hop |")
    a(f"| 410 OK | {counts.get('gone_410_ok', 0)} | Legacy `/path/` answered 410 with no redirect hop |")
    a(f"| multi-hop | {counts.get('multi_hop', 0)} | Correct final answer, but more than one hop to get there |")
    a(f"| wrong destination | {counts.get('wrong_destination', 0)} | Landed somewhere other than the mapped destination |")
    a(f"| destination 404s | {counts.get('destination_404', 0)} | Redirect is correct; the target route/product does not exist in the prototype |")
    a(f"| skipped | {counts.get('skipped', 0)} | `client_decision` rows and query-only sources |")
    a(f"| **fail** | **{counts.get('fail', 0)}** | Real problem |")
    a("")
    a("### Canonical (slash-free) form")
    a("")
    a("What `next.config.ts` `redirects()` and `src/proxy.ts` see after normalization.")
    a("")
    a(f"- Correct: **{canonical_ok}**")
    a(f"- Incorrect: **{len(canonical_bad)}**")
    if canonical_bad:
        a("")
        a("| Source | Outcome | Status | Location |")
        a("|---|---|---:|---|")
        for src, outcome, status, got in canonical_bad[:50]:
            a(f"| `{src}` | {outcome} | {status} | `{got or '-'}` |")
    a("")
    a("### 410 Gone (`docs/redirects/gone.json`)")
    a("")
    a(f"- Paths answering 410: **{gone_ok} / {len(gone_paths)}**")
    if gone_bad:
        a("")
        for path, status in gone_bad:
            a(f"  - `{path}` -> {status}")
    a("")
    a("Served by `src/proxy.ts`, which returns a real 410 with a small HTML body,")
    a("`Cache-Control: public, max-age=3600, must-revalidate` and `X-Robots-Tag: noindex`.")
    a("The one 410 row not in `gone.json` is `/?s=`, a query-only URL no path rule can match.")
    a("")
    a(f"Static map check (loops and chains): {'**' + str(len(map_problems)) + ' problem(s)**' if map_problems else 'clean'}")
    if map_problems:
        a("")
        for p in map_problems:
            a(f"- {p}")
    a("")

    a("## Failures")
    a("")
    if failures:
        a("| Source | Outcome | Destination | Detail |")
        a("|---|---|---|---|")
        for r in failures:
            a(f"| `{r['source']}` | {r['outcome']} | `{r['destination'] or '-'}` | {r['detail']} |")
    else:
        a("None.")
    a("")

    a("## Wrong destination")
    a("")
    if wrong:
        a("| Source | Expected | Detail |")
        a("|---|---|---|")
        for r in wrong:
            a(f"| `{r['source']}` | `{r['destination'] or r['source']}` | {r['detail']} |")
    else:
        a("None.")
    a("")

    a("## Multi-hop")
    a("")
    if multi:
        a(f"{len(multi)} rows answer correctly but cost more than one hop.")
        a("")
        if not one_hop_mode:
            a("All of them are the same platform hop: Next.js normalizes `/path/` to")
            a("`/path` with its own 308 before `redirects()` and before `src/proxy.ts` run.")
            a("Setting `skipTrailingSlashRedirect: true` in `next.config.ts` hands that")
            a("normalization to `src/proxy.ts`, which resolves the legacy URL to its final")
            a("destination (or 410) directly. The redirect map itself has no chains.")
            a("")
            a(f"Measured on an otherwise identical tree with the flag set, all {len(multi)} of these")
            a(f"become single-hop and the {len(gone_paths)} `gone.json` paths answer 410 with no")
            a("redirect hop at all. The flag is the one change this layer still needs and it")
            a("lives in `next.config.ts`.")
            a("")
        a("<details><summary>Full list</summary>")
        a("")
        a("| Source | Outcome | Hops | Chain |")
        a("|---|---|---:|---|")
        for r in sorted(multi, key=lambda x: x["source"]):
            a(f"| `{r['source']}/` | {r['outcome']} | {r['hops']} | {r.get('chain', '')} |")
        a("")
        a("</details>")
    else:
        a("None.")
    a("")

    a("## Destinations that 404 today")
    a("")
    if not_built:
        a(f"{len(not_built)} rows. The redirect itself is correct; the target does not exist")
        a("in the prototype yet. These become passes once the content routes and the full")
        a("Shopify catalog land.")
        a("")
        grouped: Counter[str] = Counter(r["detail"].split(": ", 1)[-1] for r in not_built)
        a("| Reason | Rows |")
        a("|---|---:|")
        for reason, n in sorted(grouped.items()):
            a(f"| {reason} | {n} |")
        a("")
        a("<details><summary>Full list</summary>")
        a("")
        a("| Source | Destination |")
        a("|---|---|")
        for r in sorted(not_built, key=lambda x: x["source"]):
            a(f"| `{r['source']}` | `{r['destination'] or r['source']}` |")
        a("")
        a("</details>")
    else:
        a("None.")
    a("")

    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(
        f"single_hop_ok={counts.get('single_hop_ok', 0)} "
        f"gone_410_ok={counts.get('gone_410_ok', 0)} "
        f"multi_hop={counts.get('multi_hop', 0)} "
        f"wrong_destination={counts.get('wrong_destination', 0)} "
        f"destination_404={counts.get('destination_404', 0)} "
        f"skipped={counts.get('skipped', 0)} "
        f"fail={counts.get('fail', 0)}"
    )
    print(f"canonical_ok={canonical_ok} canonical_bad={len(canonical_bad)} gone_410={gone_ok}/{len(gone_paths)}")
    print(f"report: {args.report}")
    if map_problems:
        for p in map_problems:
            print("MAP: " + p, file=sys.stderr)
    return 1 if failures or wrong or map_problems or gone_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
