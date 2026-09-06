/**
 * Site-level configuration: the canonical origin and the deployment signal the
 * SEO routes depend on. Deliberately *not* `server-only` — it holds no secret,
 * reads no `SHOPIFY_*` variable, and the JSON-LD builders that import it are
 * unit-tested with plain Node.
 *
 * The origin is a single config value. Set `NEXT_PUBLIC_SITE_URL` on the host
 * (see `docs/deployment.md`); everything else is a fallback so a preview
 * deployment, a CI build and `next dev` all produce sensible absolute URLs:
 *
 *   NEXT_PUBLIC_SITE_URL  -> explicit, wins everywhere (set this in production)
 *   SITE_URL              -> same value for hosts that dislike NEXT_PUBLIC_*
 *   VERCEL_PROJECT_PRODUCTION_URL -> the project's stable production hostname
 *   VERCEL_URL            -> this deployment's per-commit hostname
 *   http://localhost:3000 -> local development
 */

/** Origin used when nothing else is configured (local development). */
const DEFAULT_SITE_URL = "http://localhost:3000";

export const SITE_NAME = "ProSporter";
export const SITE_DESCRIPTION =
  "Indoor and beach volleyball apparel, club teamwear and protective gear. Built for the Australian game.";
/** Logo used by the Organization JSON-LD; served from `public/`. */
export const SITE_LOGO_PATH = "/brand/prosporter-logo.png";

/** `example.com`, `https://example.com/` and `https://example.com` all normalise to the origin. */
function normalizeOrigin(value: string | undefined): string | null {
  const trimmed = (value ?? "").trim();
  if (!trimmed) return null;
  const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    return new URL(withScheme).origin;
  } catch {
    return null;
  }
}

/** The canonical origin, without a trailing slash. */
export function siteUrl(): string {
  const candidates = [
    process.env.NEXT_PUBLIC_SITE_URL,
    process.env.SITE_URL,
    process.env.VERCEL_PROJECT_PRODUCTION_URL,
    process.env.VERCEL_URL,
  ];
  for (const candidate of candidates) {
    const origin = normalizeOrigin(candidate);
    if (origin) return origin;
  }
  return DEFAULT_SITE_URL;
}

/**
 * Absolute URL for an app path. Paths are kept slash-free (`/shop/beach`, not
 * `/shop/beach/`) to match `src/proxy.ts`, which normalises trailing slashes
 * away in a single hop.
 */
export function absoluteUrl(path = "/"): string {
  const base = siteUrl();
  if (!path || path === "/") return base;
  const withLeadingSlash = path.startsWith("/") ? path : `/${path}`;
  return `${base}${withLeadingSlash.replace(/\/+$/, "")}`;
}

export type DeploymentEnvironment = "production" | "preview" | "development";

/**
 * Vercel sets `VERCEL_ENV` to production | preview | development. Off Vercel we
 * fall back to `NODE_ENV`, so `next start` on a self-hosted box still counts as
 * production and `next dev` does not.
 */
export function deploymentEnvironment(): DeploymentEnvironment {
  const vercelEnv = (process.env.VERCEL_ENV ?? "").trim().toLowerCase();
  if (vercelEnv === "production" || vercelEnv === "preview" || vercelEnv === "development") {
    return vercelEnv;
  }
  return process.env.NODE_ENV === "production" ? "production" : "development";
}

/**
 * Only the production deployment may be crawled. Every preview URL is a
 * duplicate of production and would compete with it in the index, so
 * `src/app/robots.ts` returns disallow-all for anything that is not production.
 */
export function isIndexableDeployment(): boolean {
  return deploymentEnvironment() === "production";
}

/** One URL in `src/app/sitemap.ts`. `path` is an app path, not an absolute URL. */
export type SitemapEntry = {
  path: string;
  /** ISO 8601 timestamp from the source (Shopify `updatedAt`/`publishedAt`), or null. */
  lastModified: string | null;
};
