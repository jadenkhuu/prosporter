import { serializeJsonLd, type JsonLdObject } from "@/lib/seo/json-ld";

/**
 * Renders one or more schema.org nodes as a server-side
 * `<script type="application/ld+json">` block.
 *
 * `dangerouslySetInnerHTML` is required — React would HTML-escape the JSON if it
 * were rendered as a text child, which breaks the parser. Safety comes from
 * `serializeJsonLd`, which escapes `<`, `>`, `&` and the U+2028/U+2029 line
 * separators, so no value can close the script tag early.
 *
 * The component is a plain (server) component: no `"use client"`, no hooks, so
 * the JSON is present in the initial HTML that crawlers read.
 */
export function JsonLd({ data }: { data: JsonLdObject | JsonLdObject[] }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }}
    />
  );
}
