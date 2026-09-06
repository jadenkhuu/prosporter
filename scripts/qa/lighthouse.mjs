#!/usr/bin/env node
/**
 * CLNT-179 / Workstream 7 — Lighthouse mobile runs for the acceptance
 * thresholds in docs/prosporter-project-schedule.md sections 1.4 and 3.1-3.2:
 * Performance >= 85, LCP < 2.5 s, CLS < 0.1, INP < 200 ms.
 *
 * Runs `npx lighthouse` (12.x) three times per URL with the mobile preset and
 * reports the median run, chosen by Performance score. Lighthouse has no INP
 * audit in a lab run — INP needs real interactions — so Total Blocking Time is
 * recorded as the documented lab proxy alongside Max Potential FID.
 *
 * HTML reports are kept under docs/qa/lighthouse/. JSON is kept only long
 * enough to read the metrics out, then deleted unless --keep-json is passed
 * (the raw JSON is several MB per run).
 *
 * Usage:
 *   node scripts/qa/lighthouse.mjs [--base https://prosporter.vercel.app]
 *                                  [--runs 3] [--keep-json]
 *                                  [--url /path --url /other]
 *
 * `--rebuild` regenerates docs/qa/performance.md from the HTML reports already
 * in docs/qa/lighthouse/ without launching Chrome again. Lighthouse embeds the
 * whole LHR in its HTML report, so nothing is lost by deleting the JSON.
 */

import { execFile } from "node:child_process";
import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const run = promisify(execFile);
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const OUT = path.join(REPO, "docs", "qa", "lighthouse");

const argv = process.argv.slice(2);
const flag = (name, dflt) => {
  const i = argv.indexOf(`--${name}`);
  return i === -1 ? dflt : argv[i + 1];
};
const has = (name) => argv.includes(`--${name}`);
const collect = (name) => argv.reduce((acc, a, i) => (a === `--${name}` ? [...acc, argv[i + 1]] : acc), []);

const BASE = String(flag("base", "https://prosporter.vercel.app")).replace(/\/$/, "");
const RUNS = Number(flag("runs", 3));
const KEEP_JSON = has("keep-json");

/** Default targets: home, a collection listing, a product detail page. */
const DEFAULT_TARGETS = [
  { label: "home", path: "/" },
  { label: "collection", path: "/shop/jerseys" },
  { label: "product", path: "/product/ace-unisex" },
];
const explicit = collect("url");
const TARGETS = explicit.length
  ? explicit.map((p, i) => ({ label: `url${i + 1}-${p.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "root"}`, path: p }))
  : DEFAULT_TARGETS;

const CHROME_FLAGS = "--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage";

/** Pull the LHR back out of a saved HTML report. */
function lhrFromHtml(html) {
  const m = /window\.__LIGHTHOUSE_JSON__\s*=\s*(\{[\s\S]*?\});<\/script>/.exec(html);
  return m ? JSON.parse(m[1]) : null;
}

function metrics(lhr) {
  const a = lhr.audits ?? {};
  const nv = (k) => (typeof a[k]?.numericValue === "number" ? a[k].numericValue : null);
  // The audit's `details` is a list of two sub-tables: the element, then the
  // TTFB / load-delay / load-time / render-delay phase breakdown.
  const lcpTables = a["largest-contentful-paint-element"]?.details?.items ?? [];
  const rows = lcpTables.flatMap((t) => t?.items ?? []);
  const lcpNode = rows.find((r) => r.node)?.node ?? null;
  const phases = rows
    .filter((r) => r.phase)
    .map((p) => ({ phase: p.phase, ms: Math.round(p.timing ?? 0), percent: p.percent }));
  return {
    lcpSelector: lcpNode?.selector ?? null,
    lcpSnippet: (lcpNode?.snippet ?? "").slice(0, 120) || null,
    lcpPhases: phases,
    serverResponse: a["server-response-time"]?.displayValue ?? null,
    networkLatency: a["network-server-latency"]?.displayValue ?? null,
    performance: Math.round((lhr.categories?.performance?.score ?? 0) * 100),
    accessibility: lhr.categories?.accessibility ? Math.round(lhr.categories.accessibility.score * 100) : null,
    bestPractices: lhr.categories?.["best-practices"] ? Math.round(lhr.categories["best-practices"].score * 100) : null,
    seo: lhr.categories?.seo ? Math.round(lhr.categories.seo.score * 100) : null,
    fcpMs: nv("first-contentful-paint"),
    lcpMs: nv("largest-contentful-paint"),
    cls: nv("cumulative-layout-shift"),
    tbtMs: nv("total-blocking-time"),
    // Lab INP proxies. Real INP requires field data or scripted interactions.
    maxPotentialFidMs: nv("max-potential-fid"),
    speedIndexMs: nv("speed-index"),
    ttiMs: nv("interactive"),
  };
}

/** Median by Performance score; for an even count take the lower middle. */
function median(runsArr) {
  const sorted = [...runsArr].sort((x, y) => x.m.performance - y.m.performance);
  return sorted[Math.floor((sorted.length - 1) / 2)];
}

const fmtMs = (v) => (v == null ? "n/a" : `${(v / 1000).toFixed(2)} s`);
const fmtRaw = (v) => (v == null ? "n/a" : `${Math.round(v)} ms`);
const fmtCls = (v) => (v == null ? "n/a" : v.toFixed(3));

/** Rebuild the report set from HTML already on disk. */
async function rebuildFromHtml() {
  const files = (await readdir(OUT)).filter((f) => f.endsWith(".report.html"));
  const byLabel = new Map();
  for (const f of files.sort()) {
    const m = /^(.*)-mobile-run(\d+)\.report\.html$/.exec(f);
    if (!m) continue;
    const lhr = lhrFromHtml(await readFile(path.join(OUT, f), "utf8"));
    if (!lhr) continue;
    const entry = byLabel.get(m[1]) ?? { label: m[1], path: new URL(lhr.finalDisplayedUrl ?? lhr.requestedUrl).pathname, url: lhr.finalDisplayedUrl ?? lhr.requestedUrl, runs: [] };
    entry.runs.push({ i: Number(m[2]), m: metrics(lhr), html: path.join(OUT, f), fetchTime: lhr.fetchTime, lhVersion: lhr.lighthouseVersion });
    byLabel.set(m[1], entry);
  }
  const order = ["home", "collection", "product"];
  return [...byLabel.values()]
    .sort((a, b) => (order.indexOf(a.label) + 1 || 99) - (order.indexOf(b.label) + 1 || 99))
    .map((e) => ({ ...e, median: e.runs.length ? median(e.runs) : null }));
}

async function main() {
  await mkdir(OUT, { recursive: true });
  if (has("rebuild")) {
    const report = await rebuildFromHtml();
    await writeReports(report);
    console.error("[lh] rebuilt docs/qa/performance.md from saved HTML reports");
    return;
  }
  const report = [];

  for (const target of TARGETS) {
    const url = `${BASE}${target.path}`;
    const runsArr = [];
    for (let i = 1; i <= RUNS; i += 1) {
      const stem = path.join(OUT, `${target.label}-mobile-run${i}`);
      console.error(`[lh] ${target.label} run ${i}/${RUNS} -> ${url}`);
      try {
        await run("npx", [
          "--yes", "lighthouse@12", url,
          "--only-categories=performance,accessibility,best-practices,seo",
          "--form-factor=mobile",
          "--screenEmulation.mobile",
          "--throttling-method=simulate",
          "--output=json", "--output=html",
          `--output-path=${stem}`,
          `--chrome-flags=${CHROME_FLAGS}`,
          "--quiet",
          "--max-wait-for-load=60000",
        ].filter(Boolean), { maxBuffer: 256 * 1024 * 1024, timeout: 300000 });
      } catch (err) {
        console.error(`[lh] run failed: ${err?.message ?? err}`);
        runsArr.push({ i, error: String(err?.shortMessage ?? err?.message ?? err).slice(0, 300) });
        continue;
      }
      const jsonPath = `${stem}.report.json`;
      let lhr;
      try {
        lhr = JSON.parse(await readFile(jsonPath, "utf8"));
      } catch (err) {
        runsArr.push({ i, error: `could not read ${jsonPath}: ${err?.message}` });
        continue;
      }
      runsArr.push({ i, m: metrics(lhr), html: `${stem}.report.html`, json: jsonPath, fetchTime: lhr.fetchTime, lhVersion: lhr.lighthouseVersion });
      if (!KEEP_JSON) await rm(jsonPath, { force: true });
    }

    const good = runsArr.filter((r) => r.m);
    report.push({
      label: target.label,
      path: target.path,
      url,
      runs: runsArr,
      median: good.length ? median(good) : null,
    });
  }

  await writeReports(report);
}

async function writeReports(report) {
  await writeFile(path.join(OUT, "results.json"), `${JSON.stringify({ base: BASE, runs: RUNS, generated: new Date().toISOString(), report: report.map((r) => ({ ...r, runs: r.runs.map(({ html, ...rest }) => ({ ...rest, html: html ? path.basename(html) : null })) })) }, null, 2)}\n`);

  // ---- performance.md ----------------------------------------------------
  const md = [];
  md.push("# ProSporter mobile performance (CLNT-179, Workstream 7)");
  md.push("");
  md.push(`- Target: \`${BASE}\``);
  md.push(`- Tool: \`npx lighthouse@12\`, mobile preset (\`--form-factor=mobile --screenEmulation.mobile\`), simulated throttling, headless Chrome.`);
  md.push(`- ${RUNS} runs per page; the median run by Performance score is reported. Raw HTML reports are in this folder.`);
  md.push(`- Generated by \`scripts/qa/lighthouse.mjs\` on ${new Date().toISOString()}.`);
  md.push("");
  md.push("## Thresholds");
  md.push("");
  md.push("Schedule section 1 criterion 4 and section 3 criteria 1-2:");
  md.push("");
  md.push("| Metric | Threshold |");
  md.push("|---|---|");
  md.push("| Lighthouse Performance (mobile) | >= 85 |");
  md.push("| Largest Contentful Paint | < 2.5 s |");
  md.push("| Cumulative Layout Shift | < 0.1 |");
  md.push("| Interaction to Next Paint | < 200 ms |");
  md.push("");
  md.push("> **INP caveat.** Lighthouse lab runs do not measure INP: it needs real user interactions or a scripted user flow. Total Blocking Time is the accepted lab proxy and is reported below, with Max Potential FID as a secondary signal. A true INP number needs field data (CrUX / GA4 Web Vitals) after launch, so section 3 criterion 2's INP half is **not yet testable** on this deployment.");
  md.push("");
  md.push("## Median results");
  md.push("");
  md.push("| Page | URL | Perf | LCP | CLS | TBT (INP proxy) | Max Potential FID | FCP | Speed Index | Verdict |");
  md.push("|---|---|---:|---:|---:|---:|---:|---:|---:|---|");
  for (const r of report) {
    if (!r.median) { md.push(`| ${r.label} | \`${r.path}\` | — | — | — | — | — | — | — | RUN FAILED |`); continue; }
    const m = r.median.m;
    const pass = m.performance >= 85 && (m.lcpMs ?? Infinity) < 2500 && (m.cls ?? Infinity) < 0.1;
    md.push(`| ${r.label} | \`${r.path}\` | ${m.performance} | ${fmtMs(m.lcpMs)} | ${fmtCls(m.cls)} | ${fmtRaw(m.tbtMs)} | ${fmtRaw(m.maxPotentialFidMs)} | ${fmtMs(m.fcpMs)} | ${fmtMs(m.speedIndexMs)} | ${pass ? "PASS" : "FAIL"} |`);
  }
  md.push("");
  md.push("Threshold-by-threshold:");
  md.push("");
  md.push("| Page | Perf >= 85 | LCP < 2.5 s | CLS < 0.1 |");
  md.push("|---|---|---|---|");
  for (const r of report) {
    if (!r.median) { md.push(`| ${r.label} | — | — | — |`); continue; }
    const m = r.median.m;
    const y = (ok, v) => `${ok ? "PASS" : "FAIL"} (${v})`;
    md.push(`| ${r.label} | ${y(m.performance >= 85, m.performance)} | ${y((m.lcpMs ?? Infinity) < 2500, fmtMs(m.lcpMs))} | ${y((m.cls ?? Infinity) < 0.1, fmtCls(m.cls))} |`);
  }
  md.push("");
  md.push("## Other Lighthouse categories (median run, informational)");
  md.push("");
  md.push("| Page | Accessibility | Best Practices | SEO |");
  md.push("|---|---:|---:|---:|");
  for (const r of report) {
    const m = r.median?.m;
    md.push(`| ${r.label} | ${m?.accessibility ?? "—"} | ${m?.bestPractices ?? "—"} | ${m?.seo ?? "—"} |`);
  }
  md.push("");
  md.push("> The SEO category score is depressed on this deployment by design: it is `noindex, nofollow` until cutover (`NEXT_PUBLIC_SITE_URL` unset, commit 70dc500). That is expected, not a defect.");
  md.push("");
  md.push("## LCP diagnostics (median run)");
  md.push("");
  md.push("| Page | LCP element | Phase breakdown | Root document | Server latency |");
  md.push("|---|---|---|---|---|");
  for (const r of report) {
    const m = r.median?.m;
    if (!m) { md.push(`| ${r.label} | — | — | — | — |`); continue; }
    const phases = (m.lcpPhases ?? []).map((p) => `${p.phase} ${p.ms} ms (${p.percent})`).join(", ") || "—";
    md.push(`| ${r.label} | \`${m.lcpSelector ?? "—"}\` | ${phases} | ${m.serverResponse ?? "—"} | ${m.networkLatency ?? "—"} |`);
  }
  md.push("");
  md.push("## All runs");
  md.push("");
  md.push("| Page | Run | Perf | LCP | CLS | TBT | Report |");
  md.push("|---|---:|---:|---:|---:|---:|---|");
  for (const r of report) {
    for (const one of r.runs) {
      if (!one.m) { md.push(`| ${r.label} | ${one.i} | — | — | — | — | FAILED: ${one.error} |`); continue; }
      md.push(`| ${r.label} | ${one.i} | ${one.m.performance} | ${fmtMs(one.m.lcpMs)} | ${fmtCls(one.m.cls)} | ${fmtRaw(one.m.tbtMs)} | [html](${path.basename(one.html)}) |`);
    }
  }
  md.push("");
  await writeFile(path.join(REPO, "docs", "qa", "performance.md"), `${md.join("\n")}\n`);
  console.error("[lh] wrote docs/qa/performance.md");
}

main().catch((e) => { console.error(e); process.exit(1); });
