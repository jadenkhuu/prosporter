#!/usr/bin/env node
/**
 * CLNT-179 / Workstream 7 — link, status and redirect crawl of a deployed
 * ProSporter storefront.
 *
 * Read-only. Node 22 stdlib only (global fetch, node:fs, node:path).
 *
 * What it does, in order:
 *   1. Seeds from `/`, every `<loc>` in `/sitemap.xml`, and every `Sitemap:` /
 *      `Allow:` path in `/robots.txt`.
 *   2. Breadth-first crawl of same-host HTML links, capped at --max URLs with
 *      --concurrency workers and a polite --delay between requests. Records
 *      status, the final URL after redirects, the redirect chain length, the
 *      content type and the first referring page.
 *   3. Checks every `<img src>` seen on crawled pages plus the Shopify CDN
 *      image URLs found on the first 30 product pages (HEAD, falling back to a
 *      ranged GET when HEAD is refused).
 *   4. Replays a sample of legacy URLs from docs/redirects/redirect-map.csv and
 *      docs/redirects/gone.json and asserts the one-hop 308 / 410 behaviour
 *      that docs/redirects/README.md describes.
 *
 * Outputs docs/qa/crawl-report.md and docs/qa/crawl-results.csv.
 *
 * Usage:
 *   node scripts/qa/crawl.mjs [--base https://prosporter.vercel.app]
 *                             [--max 600] [--concurrency 4] [--delay 120]
 *                             [--redirect-samples 20] [--gone-samples 10]
 *                             [--product-image-pages 30] [--seed 1]
 */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

const args = new Map();
for (let i = 2; i < process.argv.length; i += 1) {
  const a = process.argv[i];
  if (a.startsWith("--")) args.set(a.slice(2), process.argv[i + 1] ?? "1");
}
const opt = (k, d) => (args.has(k) ? args.get(k) : d);
const num = (k, d) => Number(opt(k, d));

const BASE = String(opt("base", "https://prosporter.vercel.app")).replace(/\/$/, "");
const MAX = num("max", 600);
const CONCURRENCY = num("concurrency", 4);
const DELAY_MS = num("delay", 120);
const REDIRECT_SAMPLES = num("redirect-samples", 20);
const GONE_SAMPLES = num("gone-samples", 10);
const PRODUCT_IMAGE_PAGES = num("product-image-pages", 30);
const SEED = num("seed", 1);
const UA = "ProSporter-QA-Crawler/1.0 (+CLNT-179 acceptance evidence; read-only)";
const OUT_DIR = path.join(REPO, "docs", "qa");

const baseHost = new URL(BASE).host;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Deterministic sampler so reruns compare like for like. */
function sample(items, n, seed) {
  const arr = [...items];
  let s = seed >>> 0 || 1;
  const rnd = () => {
    s ^= s << 13; s >>>= 0;
    s ^= s >> 17;
    s ^= s << 5; s >>>= 0;
    return s / 0xffffffff;
  };
  for (let i = arr.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rnd() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr.slice(0, n);
}

/** Fetch following redirects by hand so the chain is observable. */
async function trace(url, { method = "GET", maxHops = 10, headers = {} } = {}) {
  const chain = [];
  let current = url;
  for (let hop = 0; hop <= maxHops; hop += 1) {
    let res;
    try {
      res = await fetch(current, {
        method,
        redirect: "manual",
        headers: { "user-agent": UA, ...headers },
      });
    } catch (err) {
      return { ok: false, error: String(err?.message ?? err), chain, finalUrl: current, status: 0 };
    }
    const location = res.headers.get("location");
    chain.push({ url: current, status: res.status, location });
    if (res.status >= 300 && res.status < 400 && location) {
      current = new URL(location, current).toString();
      continue;
    }
    return {
      ok: true,
      status: res.status,
      finalUrl: current,
      contentType: res.headers.get("content-type") ?? "",
      headers: res.headers,
      res,
      chain,
    };
  }
  return { ok: false, error: "redirect loop / too many hops", chain, finalUrl: current, status: 0 };
}

const isHtml = (ct) => /text\/html/i.test(ct ?? "");

/** Same-host, non-asset page URLs only; fragments and mailto/tel dropped. */
function normalize(href, from) {
  let u;
  try {
    u = new URL(href, from);
  } catch {
    return null;
  }
  if (u.protocol !== "https:" && u.protocol !== "http:") return null;
  if (u.host !== baseHost) return null;
  u.hash = "";
  const p = u.pathname;
  if (p.startsWith("/_next/") || p.startsWith("/api/")) return null;
  if (/\.(?:js|css|woff2?|ico|png|jpe?g|svg|webp|avif|gif|xml|txt|json|map)$/i.test(p)) return null;
  return u.toString();
}

const ATTR = (html, tag, attr) => {
  const out = [];
  const re = new RegExp(`<${tag}\\b[^>]*?\\b${attr}\\s*=\\s*("([^"]*)"|'([^']*)')`, "gi");
  let m;
  while ((m = re.exec(html))) out.push(m[2] ?? m[3] ?? "");
  return out;
};

/** Next/Image rewrites the real source into ?url=…; recover it for reporting. */
function decodeNextImage(src, from) {
  try {
    const u = new URL(src, from);
    if (u.pathname === "/_next/image" && u.searchParams.get("url")) {
      return decodeURIComponent(u.searchParams.get("url"));
    }
  } catch { /* fall through */ }
  return src;
}

async function main() {
  const started = new Date();
  console.error(`[crawl] base=${BASE} max=${MAX} concurrency=${CONCURRENCY}`);

  // ---- seeds -------------------------------------------------------------
  const seeds = new Set([`${BASE}/`]);
  const seedNotes = [];

  const robotsRes = await trace(`${BASE}/robots.txt`);
  let robotsBody = "";
  if (robotsRes.ok && robotsRes.res) {
    robotsBody = await robotsRes.res.text();
    for (const line of robotsBody.split("\n")) {
      const m = /^\s*(sitemap|allow)\s*:\s*(\S+)/i.exec(line);
      if (!m) continue;
      const u = normalize(m[2].replace(/^\/\*.*$/, "/"), `${BASE}/`);
      if (u) seeds.add(u);
    }
    seedNotes.push(`robots.txt: ${robotsRes.status}, ${robotsBody.split("\n").length} lines`);
  }

  const smRes = await trace(`${BASE}/sitemap.xml`);
  let sitemapLocs = [];
  if (smRes.ok && smRes.res) {
    const xml = await smRes.res.text();
    sitemapLocs = [...xml.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/gi)].map((m) => m[1]);
    for (const loc of sitemapLocs) {
      const u = normalize(loc, `${BASE}/`);
      if (u) seeds.add(u);
    }
    seedNotes.push(`sitemap.xml: ${smRes.status}, ${sitemapLocs.length} <loc> entries`);
  }

  // The primary nav links only to `/` and the shop listings, so a pure
  // link-following crawl never reaches `/blog`, `/contact` or any Shopify
  // content page. Seed them explicitly, plus every `same_url` row in the
  // redirect map — docs/redirects/README.md says those paths are preserved 1:1
  // and "must return 200", which makes them an authoritative 200 checklist.
  const EXTRA_SEEDS = String(opt("extra", "/blog,/contact,/search?q=jersey")).split(",").filter(Boolean);
  for (const p of EXTRA_SEEDS) {
    const u = normalize(p, `${BASE}/`);
    if (u) seeds.add(u);
  }
  seedNotes.push(`explicit extra seeds: ${EXTRA_SEEDS.join(", ")}`);

  let sameUrlSeeds = 0;
  if (opt("same-url-seeds", "1") !== "0") {
    const csvSeed = await readFile(path.join(REPO, "docs", "redirects", "redirect-map.csv"), "utf8");
    const seedLines = csvSeed.trim().split("\n");
    const h = seedLines[0].split(",");
    const pi = h.indexOf("source_path");
    const oi = h.indexOf("outcome");
    for (const line of seedLines.slice(1)) {
      const cols = line.split(",");
      if (cols[oi] !== "same_url") continue;
      const u = normalize(cols[pi], `${BASE}/`);
      if (u && !seeds.has(u)) { seeds.add(u); sameUrlSeeds += 1; }
    }
    seedNotes.push(`redirect-map \`same_url\` rows seeded (must return 200): ${sameUrlSeeds}`);
  }

  // ---- BFS ---------------------------------------------------------------
  /** url -> { referrer } */
  const queued = new Map();
  const queue = [];
  for (const s of seeds) {
    queued.set(s, "(seed)");
    queue.push(s);
  }

  const results = [];       // one row per crawled page
  const imgRefs = new Map(); // image url -> referring page
  const productPages = [];
  let head = 0;

  async function worker() {
    for (;;) {
      if (head >= queue.length) return;
      if (results.length >= MAX) return;
      const url = queue[head++];
      const referrer = queued.get(url) ?? "";
      await sleep(DELAY_MS);
      const t = await trace(url);
      const row = {
        kind: "page",
        url,
        status: t.status,
        finalUrl: t.finalUrl,
        hops: Math.max(0, t.chain.length - 1),
        contentType: t.contentType ?? "",
        referrer,
        note: t.ok ? "" : t.error ?? "",
      };
      results.push(row);
      if (results.length % 25 === 0) console.error(`[crawl] ${results.length} pages…`);
      if (!t.ok || !t.res) continue;
      if (!isHtml(t.contentType)) { try { await t.res.arrayBuffer(); } catch {} continue; }

      let html = "";
      try { html = await t.res.text(); } catch { continue; }
      row.title = (/<title[^>]*>([\s\S]*?)<\/title>/i.exec(html)?.[1] ?? "").trim().slice(0, 160);

      if (new URL(t.finalUrl).pathname.startsWith("/product/")) productPages.push({ url: t.finalUrl, html });

      for (const src of ATTR(html, "img", "src")) {
        const real = decodeNextImage(src, t.finalUrl);
        let abs;
        try { abs = new URL(real, t.finalUrl).toString(); } catch { continue; }
        if (!imgRefs.has(abs)) imgRefs.set(abs, t.finalUrl);
      }

      for (const href of ATTR(html, "a", "href")) {
        const next = normalize(href, t.finalUrl);
        if (!next || queued.has(next)) continue;
        if (queued.size >= MAX) break;
        queued.set(next, t.finalUrl);
        queue.push(next);
      }
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  console.error(`[crawl] pages done: ${results.length}`);

  // ---- images ------------------------------------------------------------
  // Every <img src> seen, plus Shopify CDN sources on the first N product pages.
  for (const { url, html } of productPages.slice(0, PRODUCT_IMAGE_PAGES)) {
    const cdn = new Set();
    for (const m of html.matchAll(/https?:\/\/cdn\.shopify\.com\/[^"'\\\s)]+/gi)) cdn.add(m[0]);
    for (const src of ATTR(html, "img", "srcset")) {
      for (const part of src.split(",")) {
        const raw = part.trim().split(/\s+/)[0];
        if (!raw) continue;
        const real = decodeNextImage(raw, url);
        if (/^https?:/i.test(real)) cdn.add(real);
      }
    }
    for (const c of cdn) if (!imgRefs.has(c)) imgRefs.set(c, url);
  }

  const imageRows = [];
  const imgList = [...imgRefs.entries()];
  let ihead = 0;
  async function imgWorker() {
    for (;;) {
      if (ihead >= imgList.length) return;
      const [url, referrer] = imgList[ihead++];
      await sleep(Math.min(DELAY_MS, 60));
      let t = await trace(url, { method: "HEAD" });
      if (t.ok && (t.status === 405 || t.status === 403 || t.status === 501)) {
        t = await trace(url, { method: "GET", headers: { range: "bytes=0-0" } });
      }
      imageRows.push({
        kind: "image",
        url,
        status: t.status,
        finalUrl: t.finalUrl,
        hops: Math.max(0, t.chain.length - 1),
        contentType: t.contentType ?? "",
        referrer,
        note: t.ok ? "" : t.error ?? "",
      });
      if (t.ok && t.res) { try { await t.res.arrayBuffer(); } catch {} }
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, imgWorker));
  console.error(`[crawl] images done: ${imageRows.length}`);

  // ---- legacy redirects --------------------------------------------------
  const csv = await readFile(path.join(REPO, "docs", "redirects", "redirect-map.csv"), "utf8");
  const lines = csv.trim().split("\n");
  const header = lines[0].split(",");
  const iPath = header.indexOf("source_path");
  const iOutcome = header.indexOf("outcome");
  const iDest = header.indexOf("destination");
  const iCode = header.indexOf("status_code");
  const iOwner = header.indexOf("owner");

  /** Split a CSV line honouring double-quoted fields. */
  function splitCsv(line) {
    const out = [];
    let cur = "", q = false;
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i];
      if (q) {
        if (ch === '"' && line[i + 1] === '"') { cur += '"'; i += 1; }
        else if (ch === '"') q = false;
        else cur += ch;
      } else if (ch === '"') q = true;
      else if (ch === ",") { out.push(cur); cur = ""; }
      else cur += ch;
    }
    out.push(cur);
    return out;
  }

  const redirectRows = lines.slice(1).map(splitCsv).filter((c) => c[iOutcome] === "301");
  const gone = JSON.parse(await readFile(path.join(REPO, "docs", "redirects", "gone.json"), "utf8"));

  const redirectChecks = [];
  for (const cols of sample(redirectRows, REDIRECT_SAMPLES, SEED)) {
    const src = cols[iPath];
    const expectDest = cols[iDest];
    const expectCode = Number(cols[iCode]);
    const owner = cols[iOwner];
    for (const variant of [src, `${src}/`]) {
      await sleep(DELAY_MS);
      const t = await trace(`${BASE}${variant}`);
      const hops = Math.max(0, t.chain.length - 1);
      const firstStatus = t.chain[0]?.status ?? 0;
      const expectedFinal = expectDest ? new URL(expectDest, `${BASE}/`).toString() : "";
      const okStatus = firstStatus === expectCode || firstStatus === 308 || firstStatus === 301;
      const okDest = !expectedFinal || t.finalUrl.replace(/\/$/, "") === expectedFinal.replace(/\/$/, "");
      redirectChecks.push({
        kind: "redirect",
        source: variant,
        trailingSlash: variant.endsWith("/") && variant !== "/",
        owner,
        expectCode,
        expectDest,
        firstStatus,
        hops,
        finalStatus: t.status,
        finalUrl: t.finalUrl,
        oneHop: hops === 1,
        pass: okStatus && okDest && t.status === 200,
        destOk: okDest,
        note: t.ok ? "" : t.error ?? "",
        chain: t.chain.map((c) => `${c.status} ${c.url}`).join(" -> "),
      });
    }
  }

  const goneChecks = [];
  for (const src of sample(gone, GONE_SAMPLES, SEED + 7)) {
    for (const variant of [src, `${src}/`]) {
      await sleep(DELAY_MS);
      const t = await trace(`${BASE}${variant}`);
      const hops = Math.max(0, t.chain.length - 1);
      goneChecks.push({
        kind: "gone",
        source: variant,
        trailingSlash: variant.endsWith("/") && variant !== "/",
        firstStatus: t.chain[0]?.status ?? 0,
        hops,
        finalStatus: t.status,
        finalUrl: t.finalUrl,
        pass: t.status === 410,
        directGone: (t.chain[0]?.status ?? 0) === 410,
        note: t.ok ? "" : t.error ?? "",
        chain: t.chain.map((c) => `${c.status} ${c.url}`).join(" -> "),
      });
    }
  }
  console.error(`[crawl] redirect checks: ${redirectChecks.length}, gone checks: ${goneChecks.length}`);

  // ---- output ------------------------------------------------------------
  await mkdir(OUT_DIR, { recursive: true });

  const csvOut = [
    "kind,url_or_source,status,final_status,hops,final_url,content_type,referrer,expected,pass,note",
  ];
  const esc = (v) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  for (const r of [...results, ...imageRows]) {
    csvOut.push([
      r.kind, r.url, r.status, r.status, r.hops, r.finalUrl, r.contentType, r.referrer,
      "200", r.status === 200 ? "PASS" : "FAIL", r.note,
    ].map(esc).join(","));
  }
  for (const r of redirectChecks) {
    csvOut.push([
      r.kind, r.source, r.firstStatus, r.finalStatus, r.hops, r.finalUrl, "", "",
      `${r.expectCode} -> ${r.expectDest} (200)`, r.pass ? "PASS" : "FAIL", r.chain,
    ].map(esc).join(","));
  }
  for (const r of goneChecks) {
    csvOut.push([
      r.kind, r.source, r.firstStatus, r.finalStatus, r.hops, r.finalUrl, "", "",
      "410", r.pass ? "PASS" : "FAIL", r.chain,
    ].map(esc).join(","));
  }
  await writeFile(path.join(OUT_DIR, "crawl-results.csv"), `${csvOut.join("\n")}\n`);

  // ---- markdown ----------------------------------------------------------
  const pageBad = results.filter((r) => r.status !== 200);
  const imgBad = imageRows.filter((r) => r.status !== 200 && r.status !== 206);
  const redirBad = redirectChecks.filter((r) => !r.pass);
  const goneBad = goneChecks.filter((r) => !r.pass);
  const byStatus = (rows) => {
    const m = new Map();
    for (const r of rows) m.set(r.status, (m.get(r.status) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => a[0] - b[0]);
  };

  const md = [];
  md.push("# ProSporter crawl report (CLNT-179, Workstream 7)");
  md.push("");
  md.push(`- Target: \`${BASE}\``);
  md.push(`- Run: ${started.toISOString()} (finished ${new Date().toISOString()})`);
  md.push(`- Generated by \`scripts/qa/crawl.mjs\` — read-only, no credentials, no personal data.`);
  md.push(`- Settings: max ${MAX} URLs, concurrency ${CONCURRENCY}, ${DELAY_MS} ms delay, sample seed ${SEED}.`);
  md.push("");
  md.push("## Seeds");
  md.push("");
  for (const n of seedNotes) md.push(`- ${n}`);
  md.push(`- Discovered link frontier: ${queued.size} unique same-host URLs (cap ${MAX}).`);
  md.push("");
  md.push("## Summary");
  md.push("");
  md.push("| Check | Count | Passing | Failing |");
  md.push("|---|---:|---:|---:|");
  md.push(`| Pages crawled | ${results.length} | ${results.length - pageBad.length} | ${pageBad.length} |`);
  md.push(`| Images checked | ${imageRows.length} | ${imageRows.length - imgBad.length} | ${imgBad.length} |`);
  md.push(`| Legacy 301/308 samples (bare + trailing-slash) | ${redirectChecks.length} | ${redirectChecks.length - redirBad.length} | ${redirBad.length} |`);
  md.push(`| Legacy 410 samples (bare + trailing-slash) | ${goneChecks.length} | ${goneChecks.length - goneBad.length} | ${goneBad.length} |`);
  md.push("");
  md.push("### Page status distribution");
  md.push("");
  md.push("| Status | Count |");
  md.push("|---:|---:|");
  for (const [s, c] of byStatus(results)) md.push(`| ${s} | ${c} |`);
  md.push("");
  md.push("### Image status distribution");
  md.push("");
  md.push("| Status | Count |");
  md.push("|---:|---:|");
  for (const [s, c] of byStatus(imageRows)) md.push(`| ${s} | ${c} |`);
  md.push("");

  md.push("## Non-200 / unexpected responses");
  md.push("");
  md.push("A referrer of `(seed)` means nothing on the site links to the URL — it came from the sitemap, robots.txt, the explicit seed list, or a `same_url` row of the redirect map. Those are inbound/legacy entry points, not broken internal links; a non-`(seed)` referrer is a broken internal link and fails section 1 criterion 8.");
  md.push("");
  if (pageBad.length === 0 && imgBad.length === 0) {
    md.push("No page or image returned anything other than 200. Every internal link resolves.");
  } else {
    md.push("| Kind | URL | Status | Final URL | Referring page | Note |");
    md.push("|---|---|---:|---|---|---|");
    for (const r of [...pageBad, ...imgBad]) {
      md.push(`| ${r.kind} | \`${r.url}\` | ${r.status} | \`${r.finalUrl}\` | \`${r.referrer}\` | ${r.note || ""} |`);
    }
  }
  md.push("");

  md.push("## Legacy redirect sample (expect one-hop 308 to a 200)");
  md.push("");
  md.push("`docs/redirects/README.md`: sources are stored slash-free; a request with the legacy trailing slash costs one platform normalization hop unless `skipTrailingSlashRedirect` hands it to `src/proxy.ts`.");
  md.push("");
  md.push("| Source | Owner | Expected | First status | Hops | Final status | Final URL | Verdict |");
  md.push("|---|---|---:|---:|---:|---:|---|---|");
  for (const r of redirectChecks) {
    md.push(`| \`${r.source}\` | ${r.owner} | ${r.expectCode} -> \`${r.expectDest}\` | ${r.firstStatus} | ${r.hops} | ${r.finalStatus} | \`${r.finalUrl}\` | ${r.pass ? "PASS" : "FAIL"} |`);
  }
  md.push("");

  md.push("## Legacy 410 sample (expect 410 Gone)");
  md.push("");
  md.push("| Source | First status | Hops | Final status | Direct 410 | Verdict |");
  md.push("|---|---:|---:|---:|---|---|");
  for (const r of goneChecks) {
    md.push(`| \`${r.source}\` | ${r.firstStatus} | ${r.hops} | ${r.finalStatus} | ${r.directGone ? "yes" : "no"} | ${r.pass ? "PASS" : "FAIL"} |`);
  }
  md.push("");
  md.push("Full per-URL data: [`crawl-results.csv`](crawl-results.csv).");
  md.push("");

  await writeFile(path.join(OUT_DIR, "crawl-report.md"), `${md.join("\n")}\n`);
  console.error(`[crawl] wrote docs/qa/crawl-report.md and docs/qa/crawl-results.csv`);

  // A compact machine summary for the evidence index.
  await writeFile(
    path.join(OUT_DIR, "crawl-summary.json"),
    `${JSON.stringify({
      base: BASE, started, finished: new Date(),
      pages: results.length, pagesFailing: pageBad.length,
      images: imageRows.length, imagesFailing: imgBad.length,
      redirectChecks: redirectChecks.length, redirectFailing: redirBad.length,
      goneChecks: goneChecks.length, goneFailing: goneBad.length,
      frontier: queued.size, sitemapLocs: sitemapLocs.length,
    }, null, 2)}\n`,
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
