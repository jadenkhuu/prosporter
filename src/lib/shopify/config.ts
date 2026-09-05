import "server-only";

/**
 * Server-only Shopify configuration.
 *
 * The only module allowed to read Shopify environment variables. Everything
 * else imports from here so a missing or malformed variable fails in one
 * place with one message. `server-only` makes any client import a build error.
 */
export class ShopifyConfigError extends Error {
  readonly name = "ShopifyConfigError";
}

export type ShopifyConfig = {
  /** myshopify.com domain, e.g. prosporter.myshopify.com */
  storeDomain: string;
  /** Public Storefront API access token from the Headless channel */
  storefrontToken: string;
  /** Quarterly API version, e.g. 2026-07 */
  apiVersion: string;
  /** Per-request timeout in milliseconds */
  timeoutMs: number;
  /** Fully qualified Storefront GraphQL endpoint */
  endpoint: string;
};

const REQUIRED = ["SHOPIFY_STORE_DOMAIN", "SHOPIFY_STOREFRONT_TOKEN"] as const;
const DEFAULT_API_VERSION = "2026-07";
const DEFAULT_TIMEOUT_MS = 10_000;

/** Names of required variables that are missing or blank. Empty when configured. */
export function missingShopifyEnv(): string[] {
  return REQUIRED.filter((k) => !(process.env[k] ?? "").trim());
}

export function isShopifyConfigured(): boolean {
  return missingShopifyEnv().length === 0;
}

let cached: ShopifyConfig | null = null;

/** Read and validate the Shopify configuration. Throws ShopifyConfigError. */
export function getShopifyConfig(): ShopifyConfig {
  if (cached) return cached;

  const missing = missingShopifyEnv();
  if (missing.length) {
    throw new ShopifyConfigError(
      `Missing required environment variable(s): ${missing.join(", ")}. See .env.example.`,
    );
  }

  const storeDomain = process.env.SHOPIFY_STORE_DOMAIN!.trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "");
  if (!/^[a-z0-9-]+\.myshopify\.com$/i.test(storeDomain)) {
    throw new ShopifyConfigError(
      `SHOPIFY_STORE_DOMAIN must be the *.myshopify.com domain, got "${storeDomain}".`,
    );
  }

  const apiVersion = (process.env.SHOPIFY_STOREFRONT_API_VERSION || DEFAULT_API_VERSION).trim();
  if (!/^\d{4}-(01|04|07|10)$/.test(apiVersion) && apiVersion !== "unstable") {
    throw new ShopifyConfigError(
      `SHOPIFY_STOREFRONT_API_VERSION must look like 2026-07, got "${apiVersion}".`,
    );
  }

  const timeoutMs = Number(process.env.SHOPIFY_STOREFRONT_TIMEOUT_MS || DEFAULT_TIMEOUT_MS);
  if (!Number.isFinite(timeoutMs) || timeoutMs < 1000) {
    throw new ShopifyConfigError("SHOPIFY_STOREFRONT_TIMEOUT_MS must be a number >= 1000.");
  }

  cached = {
    storeDomain,
    storefrontToken: process.env.SHOPIFY_STOREFRONT_TOKEN!.trim(),
    apiVersion,
    timeoutMs,
    endpoint: `https://${storeDomain}/api/${apiVersion}/graphql.json`,
  };
  return cached;
}
