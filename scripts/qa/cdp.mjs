/**
 * Minimal Chrome DevTools Protocol client for the CLNT-179 QA scripts.
 *
 * Neither Playwright nor Puppeteer is a dependency of this repo, and the QA
 * pass is read-only, so nothing is installed: this drives the Chrome already on
 * the machine over `--remote-debugging-port` using Node 22's global WebSocket.
 */

import { spawn } from "node:child_process";
import { stat } from "node:fs/promises";
import path from "node:path";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
];

export async function findChrome() {
  for (const c of CHROME_CANDIDATES) {
    try { await stat(c); return c; } catch { /* next */ }
  }
  throw new Error(`no Chrome binary found; tried:\n  ${CHROME_CANDIDATES.join("\n  ")}`);
}

/** Launch headless Chrome and wait for its DevTools endpoint. Returns { proc, version, port }. */
export async function launchChrome(port) {
  const chrome = await findChrome();
  const profile = path.join(process.env.TMPDIR ?? "/tmp", `prosporter-qa-chrome-${port}-${process.pid}`);
  const proc = spawn(chrome, [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    "--headless=new",
    "--no-first-run", "--no-default-browser-check",
    "--disable-gpu", "--hide-scrollbars",
    "--disable-features=Translate,MediaRouter,OptimizationHints",
    "about:blank",
  ], { stdio: "ignore" });

  let version = null;
  for (let i = 0; i < 80 && !version; i += 1) {
    await sleep(300);
    try { version = await fetch(`http://127.0.0.1:${port}/json/version`).then((r) => r.json()); } catch { /* retry */ }
  }
  if (!version) { proc.kill(); throw new Error("Chrome DevTools endpoint never came up"); }
  return { proc, version, port, chrome };
}

export class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.handlers = new Map();
    ws.addEventListener("message", (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.id != null && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
        return;
      }
      const hs = this.handlers.get(msg.method);
      if (hs) for (const h of hs) h(msg.params);
    });
  }
  on(method, fn) {
    if (!this.handlers.has(method)) this.handlers.set(method, []);
    this.handlers.get(method).push(fn);
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }
      }, 60000);
    });
  }
  /** Convenience: evaluate an expression in the page and return its value. */
  async evaluate(expression) {
    const r = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    return r.result?.value;
  }
  close() { try { this.ws.close(); } catch { /* already gone */ } }
}

/** Open a fresh tab and attach to it. Returns { cdp, targetId }. */
export async function newTab(port) {
  const target = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" }).then((r) => r.json());
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", () => reject(new Error("websocket failed")), { once: true });
  });
  return { cdp: new Cdp(ws), targetId: target.id };
}

export async function closeTab(port, targetId) {
  await fetch(`http://127.0.0.1:${port}/json/close/${targetId}`).catch(() => {});
}
