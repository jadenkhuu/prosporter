import { SITE_NAME } from "../site.ts";

/**
 * Open Graph fields every route repeats.
 *
 * Next.js does **not** deep-merge `openGraph`: a route that sets its own
 * `openGraph` replaces the root layout's object wholesale (see
 * `node_modules/next/dist/docs/.../generate-metadata.md`, "Inheriting fields").
 * Spreading `OG_DEFAULTS` into each route's `openGraph` is what keeps
 * `og:site_name` and `og:locale` on pages that set a title of their own.
 */
export const OG_DEFAULTS = {
  siteName: SITE_NAME,
  locale: "en_AU",
} as const;
