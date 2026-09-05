import redirectsJson from "../../../docs/redirects/redirects.json";

/**
 * PLACEHOLDER (CLNT-175). The blog slugs the legacy redirect map points at,
 * derived from `docs/redirects/redirects.json` so the placeholder routes beside
 * this file can never drift from the redirect layer. Delete this together with
 * the placeholders when the real blog lands.
 */
export const blogSlugs: string[] = Array.from(
  new Set(
    (redirectsJson as { destination: string }[])
      .map((rule) => rule.destination)
      .filter((destination) => destination.startsWith("/blog/"))
      .map((destination) => destination.slice("/blog/".length))
      .filter((slug) => slug !== "" && !slug.includes("/")),
  ),
).sort();
