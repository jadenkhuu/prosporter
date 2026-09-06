import { SITE_NAME } from "../site.ts";

/**
 * Default Open Graph card. Every page that does not carry a picture of its own
 * shares with this (QA defect D7): before it, only product pages had an
 * `og:image`, so the home page, listings, the journal and the policy pages
 * shared as a bare text card.
 *
 * A file-convention `opengraph-image` route would not do the job here. Next
 * only folds file-based image metadata in when the segment's own metadata has
 * no `images` key (`resolve-metadata.js`), and every route in this app exports
 * an `openGraph` object, so the default has to travel with `OG_DEFAULTS`.
 *
 * The path is resolved against `metadataBase` (set in the root layout), so it
 * comes out absolute as Open Graph requires.
 */
export const OG_IMAGE = {
  url: "/og/prosporter-og.png",
  width: 1200,
  height: 630,
  alt: `${SITE_NAME} — volleyball teamwear and apparel`,
};

/**
 * Open Graph fields every route repeats.
 *
 * Next.js does **not** deep-merge `openGraph`: a route that sets its own
 * `openGraph` replaces the root layout's object wholesale (see
 * `node_modules/next/dist/docs/.../generate-metadata.md`, "Inheriting fields").
 * Spreading `OG_DEFAULTS` into each route's `openGraph` is what keeps
 * `og:site_name`, `og:locale` and `og:image` on pages that set a title of their
 * own. A route with a picture of its own — a product photo, an article's
 * featured image — passes `images` after the spread and replaces it.
 */
export const OG_DEFAULTS = {
  siteName: SITE_NAME,
  locale: "en_AU",
  images: [OG_IMAGE],
};
