import assert from "node:assert/strict";
import test from "node:test";

import { contentSecurityPolicy, securityHeaders } from "../security-headers.ts";

/** The policy as a { directive: [sources] } map, for readable assertions. */
function parse(csp) {
  return Object.fromEntries(
    csp.split("; ").map((directive) => {
      const [name, ...sources] = directive.split(" ");
      return [name, sources];
    }),
  );
}

test("every required hardening header is present exactly once", () => {
  const headers = securityHeaders(false);
  const keys = headers.map((h) => h.key);
  for (const key of [
    "X-Content-Type-Options",
    "Referrer-Policy",
    "X-Frame-Options",
    "Permissions-Policy",
    "Content-Security-Policy",
  ]) {
    assert.equal(keys.filter((k) => k === key).length, 1, `${key} set once`);
  }
});

test("the D5 headers carry their agreed values", () => {
  const byKey = Object.fromEntries(securityHeaders(false).map((h) => [h.key, h.value]));
  assert.equal(byKey["X-Content-Type-Options"], "nosniff");
  assert.equal(byKey["Referrer-Policy"], "strict-origin-when-cross-origin");
  assert.equal(byKey["X-Frame-Options"], "DENY");
});

test("Permissions-Policy denies the sensitive features and the topics API", () => {
  const value = securityHeaders(false).find((h) => h.key === "Permissions-Policy").value;
  for (const feature of [
    "camera",
    "microphone",
    "geolocation",
    // Checkout is hosted by Shopify; this origin never takes a payment.
    "payment",
    "interest-cohort",
    "browsing-topics",
  ]) {
    assert.match(value, new RegExp(`(^|, )${feature}=\\(\\)(,|$)`), `${feature} denied`);
  }
});

test("the production policy allows GA4 and Shopify images and nothing else", () => {
  const csp = parse(contentSecurityPolicy(false));

  assert.deepEqual(csp["default-src"], ["'self'"]);
  assert.deepEqual(csp["object-src"], ["'none'"]);
  assert.deepEqual(csp["base-uri"], ["'self'"]);
  // Clickjacking: the CSP half of the X-Frame-Options pair.
  assert.deepEqual(csp["frame-ancestors"], ["'none'"]);
  // Checkout is a link navigation, not a form post, so no Shopify origin here.
  assert.deepEqual(csp["form-action"], ["'self'"]);
  assert.ok("upgrade-insecure-requests" in csp);

  // The inline ga4-init bootstrap needs 'unsafe-inline'; gtag.js needs its host.
  assert.ok(csp["script-src"].includes("'unsafe-inline'"));
  assert.ok(csp["script-src"].includes("https://www.googletagmanager.com"));

  assert.ok(csp["img-src"].includes("https://cdn.shopify.com"));
  // Transitional: migrated page bodies still hotlink legacy WordPress uploads.
  assert.ok(csp["img-src"].includes("https://prosporter.com.au"));
  // Cart writes are server actions, so no client-side call leaves for Shopify.
  assert.ok(csp["connect-src"].every((source) => !source.includes("myshopify.com")));
  assert.ok(csp["connect-src"].includes("https://*.google-analytics.com"));
});

test("'unsafe-eval' and the HMR socket are development-only", () => {
  const prod = contentSecurityPolicy(false);
  const dev = contentSecurityPolicy(true);

  assert.ok(!prod.includes("'unsafe-eval'"), "production must not allow eval");
  assert.ok(!/\bwss?:/.test(prod), "production needs no websocket source");
  assert.ok(parse(dev)["script-src"].includes("'unsafe-eval'"));
  assert.ok(parse(dev)["connect-src"].includes("wss:"));
});
