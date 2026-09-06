#!/usr/bin/env node
/**
 * CLNT-179 / Workstream 7 — console errors, horizontal-overflow check and
 * responsive screenshots for the acceptance criteria in
 * docs/prosporter-project-schedule.md section 1 (criterion 1 responsive layout,
 * criterion 9 no JavaScript console errors).
 *
 * Neither Playwright nor Puppeteer is a dependency of this repo and this is a
 * read-only QA task, so nothing is installed: the script launches the Chrome
 * already on the machine with `--remote-debugging-port` and drives it over the
 * Chrome DevTools Protocol using Node 22's global WebSocket. No third-party
 * packages, no node_modules changes.
 *
 * For each page x each viewport width it records:
 *   - `Runtime.exceptionThrown` (uncaught JS errors)
 *   - `Runtime.consoleAPICalled` at level `error`
 *   - `Log.entryAdded` at level `error` (browser-side errors: CSP, mixed
 *     content, failed subresources)
 *   - `Network.loadingFailed` and any response >= 400
 *   - `documentElement.scrollWidth > clientWidth` (horizontal overflow)
 *   - a PNG screenshot under docs/qa/screenshots/
 *
 * Usage:
 *   node scripts/qa/console-and-responsive.mjs [--base URL] [--port 9333]
 *                                              [--settle 3000] [--no-shots]
 */

import { mkdir, writeFile, stat, readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { closeTab, launchChrome, newTab, sleep } from "./cdp.mjs";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const QA = path.join(REPO, "docs", "qa");
const SHOTS = path.join(QA, "screenshots");

const argv = process.argv.slice(2);
const flag = (n, d) => { const i = argv.indexOf(`--${n}`); return i === -1 ? d : argv[i + 1]; };
const has = (n) => argv.includes(`--${n}`);

const BASE = String(flag("base", "https://prosporter.vercel.app")).replace(/\/$/, "");
const PORT = Number(flag("port", 9333));
const SETTLE = Number(flag("settle", 3000));
const SHOOT = !has("no-shots");
/** How many product pages to sweep for horizontal overflow at 375 px. 0 disables. */
const SWEEP = Number(flag("sweep", 30));

const WIDTHS = [375, 768, 1280];
const HEIGHTS = { 375: 812, 768: 1024, 1280: 800 };

/** Evidence-pack budget: keep every screenshot small enough to commit and read. */
const MAX_SHOT_BYTES = Number(flag("max-shot-kb", 400)) * 1024;
const MAX_SHOT_HEIGHT = Number(flag("max-shot-height", 3200));

/** The key pages named in the CLNT-179 brief. */
const PAGES = [
  { label: "home", path: "/" },
  { label: "shop", path: "/shop" },
  { label: "collection", path: "/shop/jerseys" },
  { label: "product", path: "/product/ace-unisex" },
  { label: "search", path: "/search?q=jersey" },
  { label: "blog", path: "/blog" },
  { label: "article", path: null },       // resolved from /blog at runtime
  { label: "contact", path: "/contact" },
  { label: "not-found", path: "/qa-404-check-clnt-179" },
];

/** Trim a console/exception payload to something safe to commit. */
function short(text, n = 400) {
  return String(text ?? "").replace(/\s+/g, " ").trim().slice(0, n);
}

/** Product URLs the crawler already proved return 200, evenly sampled. */
async function productSample(n) {
  let csv = "";
  try { csv = await readFile(path.join(QA, "crawl-results.csv"), "utf8"); } catch { return []; }
  const urls = csv.split("\n").slice(1)
    .map((line) => line.split(","))
    .filter((c) => c[0] === "page" && c[2] === "200" && c[1].includes("/product/"))
    .map((c) => c[1]);
  if (urls.length <= n) return urls;
  const step = urls.length / n;
  return Array.from({ length: n }, (_, i) => urls[Math.floor(i * step)]);
}

async function main() {
  await mkdir(SHOTS, { recursive: true });

  // Resolve one real article URL from the blog index.
  const blogHtml = await fetch(`${BASE}/blog`, { headers: { "user-agent": "ProSporter-QA/1.0" } }).then((r) => r.text());
  const articleHref = [...blogHtml.matchAll(/href="(\/blog\/[^"#?]+)"/g)].map((m) => m[1]).find((h) => h !== "/blog");
  const pages = PAGES.map((p) => (p.label === "article" ? { ...p, path: articleHref ?? "/blog" } : p));
  if (!articleHref) console.error("[cdp] warning: no article link found on /blog; using /blog for the article slot");

  console.error(`[cdp] launching headless Chrome on port ${PORT}`);
  const { proc, version } = await launchChrome(PORT);
  console.error(`[cdp] ${version.Browser}`);

  const rows = [];
  const sweep = [];
  try {
    for (const page of pages) {
      for (const width of WIDTHS) {
        const url = `${BASE}${page.path}`;
        // A fresh target per measurement so listeners never bleed across pages.
        const { cdp, targetId } = await newTab(PORT);

        const consoleErrors = [];
        const pageErrors = [];
        const networkErrors = [];
        cdp.on("Runtime.exceptionThrown", (p) => {
          const d = p.exceptionDetails ?? {};
          pageErrors.push(short(d.exception?.description ?? d.text ?? "uncaught exception"));
        });
        cdp.on("Runtime.consoleAPICalled", (p) => {
          if (p.type !== "error" && p.type !== "assert") return;
          consoleErrors.push(short((p.args ?? []).map((a) => a.description ?? a.value ?? a.type).join(" ")));
        });
        cdp.on("Log.entryAdded", (p) => {
          if (p.entry?.level !== "error") return;
          const line = short(`[${p.entry.source}] ${p.entry.text}${p.entry.url ? ` (${p.entry.url})` : ""}`);
          // Chrome logs a failed request at error level even when the failure
          // is the page's own intended status (a 404 route). That is a network
          // fact, not a JavaScript error, so keep the two columns honest.
          if (p.entry.source === "network") networkErrors.push(line);
          else consoleErrors.push(line);
        });
        cdp.on("Network.loadingFailed", (p) => {
          if (p.canceled) return;
          networkErrors.push(short(`loadingFailed ${p.type}: ${p.errorText}`));
        });
        cdp.on("Network.responseReceived", (p) => {
          if (p.response.status >= 400) networkErrors.push(short(`${p.response.status} ${p.response.url}`));
        });

        await cdp.send("Runtime.enable");
        await cdp.send("Log.enable");
        await cdp.send("Network.enable");
        await cdp.send("Page.enable");
        await cdp.send("Emulation.setDeviceMetricsOverride", {
          width, height: HEIGHTS[width], deviceScaleFactor: 1, mobile: width <= 768,
        });
        if (width <= 768) {
          await cdp.send("Emulation.setUserAgentOverride", {
            userAgent: `${version["User-Agent"].replace("HeadlessChrome", "Chrome")} Mobile`,
          }).catch(() => {});
          await cdp.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 }).catch(() => {});
        }

        const loaded = new Promise((resolve) => cdp.on("Page.loadEventFired", resolve));
        let httpStatus = null;
        cdp.on("Network.responseReceived", (p) => {
          if (p.type === "Document" && httpStatus === null) httpStatus = p.response.status;
        });
        await cdp.send("Page.navigate", { url });
        await Promise.race([loaded, sleep(30000)]);
        await sleep(SETTLE);

        const probe = await cdp.send("Runtime.evaluate", {
          returnByValue: true,
          expression: `(() => {
            const d = document.documentElement;
            const over = [];
            for (const el of document.querySelectorAll('body *')) {
              const r = el.getBoundingClientRect();
              if (r.width > 0 && (r.right > d.clientWidth + 1 || r.left < -1)) {
                over.push({
                  tag: el.tagName.toLowerCase(),
                  cls: (el.className && typeof el.className === 'string' ? el.className : '').slice(0, 80),
                  right: Math.round(r.right), left: Math.round(r.left),
                });
                if (over.length >= 8) break;
              }
            }
            return {
              scrollWidth: d.scrollWidth,
              clientWidth: d.clientWidth,
              bodyScrollWidth: document.body ? document.body.scrollWidth : null,
              docHeight: d.scrollHeight,
              title: document.title,
              h1: [...document.querySelectorAll('h1')].map(h => h.textContent.trim().slice(0, 90)),
              headingOrder: [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h => h.tagName).slice(0, 40),
              overflowing: over,
            };
          })()`,
        }).then((r) => r.result?.value ?? {});

        let shot = "";
        if (SHOOT) {
          const name = `${page.label}-${width}.png`;
          try {
            // Full-page PNG, but the evidence pack has a ~400 KB per-file
            // budget. Re-capture at a smaller clip scale until it fits rather
            // than switching format — layout review wants lossless edges.
            const clipHeight = Math.min(probe.docHeight ?? HEIGHTS[width], MAX_SHOT_HEIGHT);
            let buf = null;
            for (const scale of [1, 0.7, 0.5, 0.35]) {
              const img = await cdp.send("Page.captureScreenshot", {
                format: "png",
                captureBeyondViewport: true,
                optimizeForSpeed: false,
                clip: { x: 0, y: 0, width, height: clipHeight, scale },
              });
              buf = Buffer.from(img.data, "base64");
              if (buf.length <= MAX_SHOT_BYTES) break;
            }
            await writeFile(path.join(SHOTS, name), buf);
            shot = name;
          } catch (err) {
            console.error(`[cdp] screenshot failed ${name}: ${err.message}`);
          }
        }

        const overflow = (probe.scrollWidth ?? 0) > (probe.clientWidth ?? 0);
        rows.push({
          page: page.label, path: page.path, width, httpStatus,
          scrollWidth: probe.scrollWidth ?? null, clientWidth: probe.clientWidth ?? null,
          overflow, overflowing: probe.overflowing ?? [],
          title: probe.title ?? "", h1: probe.h1 ?? [], headingOrder: probe.headingOrder ?? [],
          consoleErrors: [...new Set(consoleErrors)],
          pageErrors: [...new Set(pageErrors)],
          networkErrors: [...new Set(networkErrors)],
          screenshot: shot,
        });
        console.error(`[cdp] ${page.label} @${width}: status=${httpStatus} overflow=${overflow} errors=${consoleErrors.length + pageErrors.length}`);

        cdp.close();
        await closeTab(PORT, targetId);
      }
    }
    // Horizontal overflow on a product page turned out to depend on how many
    // gallery thumbnails the product has, so one product page is not evidence.
    // Sweep a sample of the product URLs the crawler already proved return 200.
    if (SWEEP > 0) {
      for (const url of await productSample(SWEEP)) {
        const { cdp, targetId } = await newTab(PORT);
        await cdp.send("Page.enable");
        await cdp.send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
        const loaded = new Promise((resolve) => cdp.on("Page.loadEventFired", resolve));
        await cdp.send("Page.navigate", { url });
        await Promise.race([loaded, sleep(30000)]);
        await sleep(1800);
        const r = await cdp.send("Runtime.evaluate", {
          returnByValue: true,
          expression: `(() => {
            const d = document.documentElement;
            // Ignore anything inside a fixed overlay (the closed drawers sit
            // off-screen by design); report the widest in-flow element.
            const inFixed = (el) => { let n = el; while (n && n !== document.body) { if (getComputedStyle(n).position === 'fixed') return true; n = n.parentElement; } return false; };
            // The outermost wrapper of an overflowing subtree is the symptom;
            // the deepest element that is still over-wide is the cause. Rank by
            // right edge, then by DOM depth, and prefer one that has a class.
            const depth = (el) => { let n = 0, x = el; while (x.parentElement) { n += 1; x = x.parentElement; } return n; };
            let widest = null;
            for (const el of document.querySelectorAll('main *')) {
              const b = el.getBoundingClientRect();
              if (!(b.width > 0 && b.right > d.clientWidth + 1) || inFixed(el)) continue;
              const cls = typeof el.className === 'string' ? el.className : '';
              const cand = { sel: el.tagName.toLowerCase() + (cls ? '.' + cls.split(' ').filter(Boolean).slice(0, 5).join('.') : ''), right: Math.round(b.right), width: Math.round(b.width), depth: depth(el), hasClass: Boolean(cls) };
              if (!widest) { widest = cand; continue; }
              if (cand.right > widest.right + 1) { widest = cand; continue; }
              if (Math.abs(cand.right - widest.right) <= 1) {
                if ((cand.hasClass && !widest.hasClass) || (cand.hasClass === widest.hasClass && cand.depth > widest.depth)) widest = cand;
              }
            }
            return { scrollWidth: d.scrollWidth, clientWidth: d.clientWidth, widest };
          })()`,
        }).then((x) => x.result?.value ?? {});
        sweep.push({ url, scrollWidth: r.scrollWidth ?? null, clientWidth: r.clientWidth ?? null, overflow: (r.scrollWidth ?? 0) > (r.clientWidth ?? 0), widest: r.widest ?? null });
        cdp.close();
        await closeTab(PORT, targetId);
      }
      console.error(`[cdp] product sweep: ${sweep.filter((s) => s.overflow).length}/${sweep.length} overflow at 375 px`);
    }
  } finally {
    proc.kill("SIGTERM");
  }

  await writeFile(path.join(QA, "console-and-responsive.json"), `${JSON.stringify({ base: BASE, generated: new Date().toISOString(), widths: WIDTHS, rows, productSweep: sweep }, null, 2)}\n`);

  // ---- markdown ----------------------------------------------------------
  const shotFiles = SHOOT ? await readdir(SHOTS).catch(() => []) : [];
  const sizes = {};
  for (const f of shotFiles) sizes[f] = (await stat(path.join(SHOTS, f))).size;

  const md = [];
  md.push("# Responsive layout and console errors (CLNT-179, Workstream 7)");
  md.push("");
  md.push(`- Target: \`${BASE}\``);
  md.push(`- Engine: ${version.Browser} driven over the Chrome DevTools Protocol by \`scripts/qa/console-and-responsive.mjs\` (no Playwright/Puppeteer in this repo; nothing was installed).`);
  md.push(`- Widths: ${WIDTHS.join(", ")} px. Each measurement is a fresh tab and a fresh navigation, then ${SETTLE} ms of settle time for hydration.`);
  md.push(`- Generated ${new Date().toISOString()}.`);
  md.push("");
  md.push("Acceptance criteria covered: section 1 criterion 1 (renders without horizontal scroll or broken layout at 375/768/1280) and criterion 9 (no JavaScript console errors on any key page).");
  md.push("");
  md.push("## Summary");
  md.push("");
  const anyOverflow = rows.filter((r) => r.overflow);
  const anyErrors = rows.filter((r) => r.consoleErrors.length || r.pageErrors.length);
  md.push(`- Measurements: ${rows.length} (${pages.length} pages x ${WIDTHS.length} widths).`);
  md.push(`- Horizontal overflow: **${anyOverflow.length}** of ${rows.length}.`);
  md.push(`- Measurements with console or uncaught JS errors: **${anyErrors.length}** of ${rows.length}.`);
  md.push(`- Screenshots: ${shotFiles.length} PNG${shotFiles.length === 1 ? "" : "s"} in \`screenshots/\`${shotFiles.length ? `, largest ${Math.round(Math.max(...Object.values(sizes)) / 1024)} KB` : ""}.`);
  md.push("");
  md.push("## Horizontal overflow (`documentElement.scrollWidth > clientWidth`)");
  md.push("");
  md.push("| Page | Path | 375 px | 768 px | 1280 px |");
  md.push("|---|---|---|---|---|");
  for (const page of pages) {
    const cells = WIDTHS.map((w) => {
      const r = rows.find((x) => x.page === page.label && x.width === w);
      if (!r) return "—";
      return r.overflow ? `**OVERFLOW** ${r.scrollWidth}>${r.clientWidth}` : `ok (${r.scrollWidth})`;
    });
    md.push(`| ${page.label} | \`${page.path}\` | ${cells.join(" | ")} |`);
  }
  md.push("");
  if (anyOverflow.length) {
    md.push("### Overflowing elements");
    md.push("");
    md.push("| Page | Width | Element | Class | left | right |");
    md.push("|---|---:|---|---|---:|---:|");
    for (const r of anyOverflow) {
      for (const o of r.overflowing) md.push(`| ${r.page} | ${r.width} | \`${o.tag}\` | \`${o.cls}\` | ${o.left} | ${o.right} |`);
      if (!r.overflowing.length) md.push(`| ${r.page} | ${r.width} | (no single element wider than the viewport; check padding/margins) | | | |`);
    }
    md.push("");
  }
  if (sweep.length) {
    const bad = sweep.filter((s) => s.overflow);
    md.push("## Product-page overflow sweep (375 px)");
    md.push("");
    md.push(`One product page is not enough evidence: the overflow scales with the number of gallery thumbnails. ${sweep.length} product URLs (evenly sampled from the ${"`"}crawl-results.csv${"`"} 200s) were measured at 375 px.`);
    md.push("");
    md.push(`- Overflowing: **${bad.length} of ${sweep.length}** (${Math.round((bad.length / sweep.length) * 100)}%).`);
    if (bad.length) {
      const widths = [...new Set(bad.map((b) => b.scrollWidth))].sort((a, b) => a - b);
      md.push(`- Document scroll widths seen: ${widths.join(", ")} px against a 375 px viewport.`);
      const sels = new Map();
      for (const b of bad) if (b.widest) sels.set(b.widest.sel, (sels.get(b.widest.sel) ?? 0) + 1);
      md.push(`- Widest in-flow element on each overflowing page:`);
      for (const [sel, count] of [...sels.entries()].sort((a, b) => b[1] - a[1])) md.push(`  - \`${sel}\` on ${count} page${count === 1 ? "" : "s"}`);
    }
    md.push("");
    md.push("| Product URL | scrollWidth | Overflow | Widest in-flow element |");
    md.push("|---|---:|---|---|");
    for (const s of sweep) md.push(`| \`${new URL(s.url).pathname}\` | ${s.scrollWidth} | ${s.overflow ? "**yes**" : "no"} | ${s.widest ? `\`${s.widest.sel}\` (${s.widest.width} px)` : "—"} |`);
    md.push("");
  }
  md.push("## Console and JavaScript errors");
  md.push("");
  md.push("`console.error` counts JavaScript-side errors only. Chrome's own network log entries (including the 404 route's intended status) are counted in the last column instead, because they are not JavaScript console errors and criterion 9 is about JavaScript.");
  md.push("");
  md.push("| Page | Width | HTTP | Uncaught JS | console.error | Network >= 400 / failed |");
  md.push("|---|---:|---:|---:|---:|---:|");
  for (const r of rows) {
    md.push(`| ${r.page} | ${r.width} | ${r.httpStatus ?? "—"} | ${r.pageErrors.length} | ${r.consoleErrors.length} | ${r.networkErrors.length} |`);
  }
  md.push("");
  const detail = rows.filter((r) => r.pageErrors.length || r.consoleErrors.length || r.networkErrors.length);
  if (!detail.length) {
    md.push("No uncaught JavaScript errors, no `console.error` output and no failed subresources on any page at any width.");
  } else {
    md.push("### Detail");
    md.push("");
    for (const r of detail) {
      md.push(`**${r.page} @ ${r.width} px** (\`${r.path}\`)`);
      md.push("");
      for (const e of r.pageErrors) md.push(`- uncaught: \`${e}\``);
      for (const e of r.consoleErrors) md.push(`- console.error: \`${e}\``);
      for (const e of r.networkErrors) md.push(`- network: \`${e}\``);
      md.push("");
    }
  }
  md.push("## Headings and titles seen (semantic structure, criterion 6)");
  md.push("");
  md.push("| Page | `<title>` | h1 count | First headings |");
  md.push("|---|---|---:|---|");
  for (const page of pages) {
    const r = rows.find((x) => x.page === page.label && x.width === 1280);
    if (!r) continue;
    md.push(`| ${page.label} | ${r.title ? `\`${r.title}\`` : "(none)"} | ${r.h1.length} | \`${r.headingOrder.slice(0, 8).join(" ")}\` |`);
  }
  md.push("");
  if (shotFiles.length) {
    md.push("## Screenshots");
    md.push("");
    md.push("| Page | 375 px | 768 px | 1280 px |");
    md.push("|---|---|---|---|");
    for (const page of pages) {
      const cells = WIDTHS.map((w) => {
        const f = `${page.label}-${w}.png`;
        return shotFiles.includes(f) ? `[${w}](screenshots/${f}) (${Math.round(sizes[f] / 1024)} KB)` : "—";
      });
      md.push(`| ${page.label} | ${cells.join(" | ")} |`);
    }
    md.push("");
  }
  await writeFile(path.join(QA, "responsive-and-console.md"), `${md.join("\n")}\n`);
  console.error("[cdp] wrote docs/qa/responsive-and-console.md");
}

main().catch((e) => { console.error(e); process.exit(1); });
