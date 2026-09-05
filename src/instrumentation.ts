import { log } from "@/lib/log";

/**
 * Runs once when the Next.js server starts. Validates Shopify configuration
 * up front so a misconfigured deployment fails at boot, not on the first
 * product page. Development only warns, because the mock catalog still
 * drives the prototype until the Shopify data layer replaces it.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const { missingShopifyEnv, getShopifyConfig } = await import("@/lib/shopify/config");
  const missing = missingShopifyEnv();
  if (missing.length) {
    const msg = `Shopify is not configured; missing ${missing.join(", ")}`;
    if (process.env.NODE_ENV === "production" && process.env.SHOPIFY_OPTIONAL !== "1") {
      throw new Error(`${msg}. Set the variables or SHOPIFY_OPTIONAL=1 to boot without Shopify.`);
    }
    log.warn("startup.shopify_unconfigured", { missing: missing.join(",") });
    return;
  }
  const cfg = getShopifyConfig(); // throws ShopifyConfigError on malformed values
  log.info("startup.shopify_configured", { storeDomain: cfg.storeDomain, apiVersion: cfg.apiVersion });
}
