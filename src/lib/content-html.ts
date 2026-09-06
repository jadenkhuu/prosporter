/**
 * HTML clean-up for migrated WordPress content (CLNT-171).
 *
 * Shopify stores `Page.body` and `Article.contentHtml` exactly as the migration
 * wrote them, which means WordPress block markup and Elementor page-builder
 * output: block comments (`<!-- wp:paragraph -->`), tracking scripts, embedded
 * iframes, icon `<svg>` sprites, Contact Form 7 markup and hundreds of
 * `elementor-*` classes that reference a stylesheet this site does not ship.
 *
 * `sanitizeContentHtml` reduces that to plain semantic prose we can style with
 * the `.page-content` rules in `globals.css`:
 *
 *   1. every HTML comment is dropped (this covers the `<!-- wp:... -->` pairs);
 *   2. tags in DROP_WITH_CONTENT are removed together with their contents —
 *      `<script>` above all, plus styles, iframes, media embeds, inline SVG
 *      icons and any `<form>`;
 *   3. remaining tags are filtered against an allowlist. A tag that is not
 *      allowed is unwrapped (its text survives, the element does not);
 *   4. attributes are filtered per tag. `class`, `id`, `style`, `data-*` and
 *      every `on*` handler are dropped, so nothing can carry script or depend
 *      on WordPress CSS. `href`/`src` values are restricted to http(s), mailto,
 *      tel, fragments and site-relative paths.
 *
 * The result is inserted with `dangerouslySetInnerHTML`; step 2 and step 4 are
 * what make that safe for this content. It is a display-oriented cleaner for
 * first-party migrated copy, not a general-purpose sanitiser for user input.
 */

/** Removed along with everything between the open and close tag. */
const DROP_WITH_CONTENT = [
  "script",
  "style",
  "noscript",
  "iframe",
  "object",
  "embed",
  "svg",
  "form",
  "select",
  "textarea",
  "button",
  "canvas",
  "video",
  "audio",
  "map",
  "template",
] as const;

/** Void elements that are simply deleted. */
const DROP_VOID = ["input", "source", "track", "link", "meta", "param", "col"] as const;

/** Tags kept in the output. Anything else is unwrapped. */
const ALLOWED_TAGS = new Set([
  "p", "br", "hr", "div", "span", "section", "article", "aside", "header", "footer", "main",
  "h1", "h2", "h3", "h4", "h5", "h6",
  "strong", "b", "em", "i", "u", "s", "small", "sup", "sub", "mark", "abbr", "cite", "q",
  "ul", "ol", "li", "dl", "dt", "dd",
  "a", "img", "figure", "figcaption", "picture",
  "blockquote", "pre", "code", "kbd", "samp", "var",
  "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup",
]);

/** Attributes kept, per tag. Every other attribute is dropped. */
const ALLOWED_ATTRS: Record<string, Set<string>> = {
  a: new Set(["href", "title"]),
  img: new Set(["src", "alt", "width", "height"]),
  th: new Set(["colspan", "rowspan", "scope"]),
  td: new Set(["colspan", "rowspan"]),
  blockquote: new Set(["cite"]),
  q: new Set(["cite"]),
};

const SAFE_URL = /^(https?:|mailto:|tel:|#|\/(?!\/))/i;

const VOID_TAGS = new Set(["br", "hr", "img", "wbr"]);

const ATTR_RE = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'`=<>]+)))?/g;
const TAG_RE = /<\/?([a-zA-Z][a-zA-Z0-9:-]*)((?:"[^"]*"|'[^']*'|[^"'>])*)>/g;

function escapeAttr(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function filterAttributes(tag: string, raw: string): string {
  const allowed = ALLOWED_ATTRS[tag];
  if (!allowed) return "";
  const out: string[] = [];
  ATTR_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = ATTR_RE.exec(raw))) {
    const name = m[1].toLowerCase();
    if (!allowed.has(name)) continue;
    const value = (m[2] ?? m[3] ?? m[4] ?? "").trim();
    if ((name === "href" || name === "src" || name === "cite") && !SAFE_URL.test(value)) continue;
    out.push(`${name}="${escapeAttr(value)}"`);
  }
  return out.length ? ` ${out.join(" ")}` : "";
}

function dropElements(html: string): string {
  let out = html;
  for (const tag of DROP_WITH_CONTENT) {
    // Paired form first, then any orphan open tag left behind by bad markup.
    out = out.replace(new RegExp(`<${tag}\\b[^>]*>[\\s\\S]*?<\\/${tag}\\s*>`, "gi"), "");
    out = out.replace(new RegExp(`<\\/?${tag}\\b[^>]*>`, "gi"), "");
  }
  for (const tag of DROP_VOID) {
    out = out.replace(new RegExp(`<${tag}\\b[^>]*>`, "gi"), "");
  }
  return out;
}

export function sanitizeContentHtml(html: string | null | undefined): string {
  if (!html) return "";

  // 1. HTML comments, including the `<!-- wp:... -->` / `<!-- /wp:... -->` pairs
  //    and any conditional comment. Also drops doctype/CDATA style declarations.
  let out = html.replace(/<!--[\s\S]*?-->/g, "").replace(/<![\s\S]*?>/g, "");

  // 2. Scripts, styles, embeds, icon SVGs and forms, contents included.
  //
  //    The migrated Contact page carries a Contact Form 7 block (`<form>` plus
  //    inputs and a loader script) whose action posts to a WordPress endpoint
  //    that no longer exists. It stays stripped: the replacement is a real
  //    React form, `src/components/content/ContactSection.tsx`, which the
  //    `/contact` route renders after this sanitised copy. Any other `<form>`
  //    in migrated content is dead markup and is removed for the same reason.
  //    `docs/forms.md` records the disposition of all three legacy forms.
  out = dropElements(out);

  // 3 + 4. Allowlist tags, allowlist attributes.
  out = out.replace(TAG_RE, (match, rawName: string, rawAttrs: string) => {
    const tag = rawName.toLowerCase();
    if (!ALLOWED_TAGS.has(tag)) return "";
    const closing = match.startsWith("</");
    if (closing) return VOID_TAGS.has(tag) ? "" : `</${tag}>`;
    const attrs = filterAttributes(tag, rawAttrs);
    return VOID_TAGS.has(tag) ? `<${tag}${attrs} />` : `<${tag}${attrs}>`;
  });

  // Collapse the whitespace the page builder left between nested wrappers.
  return out.replace(/[ \t]*\n[ \t\n]*/g, "\n").trim();
}

/** Plain text from HTML, for metadata descriptions and excerpts. */
export function htmlToText(html: string | null | undefined, limit = 300): string {
  if (!html) return "";
  const text = dropElements(html.replace(/<!--[\s\S]*?-->/g, ""))
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&#8217;|&rsquo;/gi, "’")
    .replace(/&quot;/gi, '"')
    .replace(/\s+/g, " ")
    .trim();
  return text.length > limit ? `${text.slice(0, limit - 1).trimEnd()}…` : text;
}
