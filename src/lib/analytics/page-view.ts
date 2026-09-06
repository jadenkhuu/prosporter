/**
 * App Router `page_view` de-duplication (CLNT-179).
 *
 * Pure and import-free, so `node --test` can load it and so the rule it encodes
 * is testable without React.
 *
 * The problem it solves: gtag's `config` call fires a `page_view` of its own on
 * every script load, and a client-side navigation fires nothing at all. Setting
 * `send_page_view: false` and sending the event ourselves fixes the second half
 * but re-opens the first — a React effect keyed on the location runs again on
 * re-render, on Strict Mode's double invocation, and on a back/forward that
 * lands on the same URL.
 *
 * So: one `page_view` per distinct pathname+search, and only when it differs
 * from the last one sent. The caller keeps `previous` in a ref.
 */

/** `page_location` path: pathname plus a non-empty query string. */
export function pageViewPath(pathname: string, search?: string | null): string {
  const path = pathname && pathname.startsWith("/") ? pathname : `/${pathname ?? ""}`;
  const query = (search ?? "").replace(/^\?/, "");
  return query ? `${path}?${query}` : path;
}

export type PageViewDecision = {
  /** The url to remember, whether or not it was sent. */
  url: string;
  /** True when the caller should send exactly one `page_view` now. */
  send: boolean;
};

/**
 * Decide whether this render's location is a new page view.
 *
 * `previous` is null before the first one, which is why a hard load still
 * reports exactly one `page_view` even though `config` sent none.
 */
export function nextPageView(previous: string | null, url: string): PageViewDecision {
  return { url, send: previous !== url };
}
