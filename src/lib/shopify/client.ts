import "server-only";

import { randomUUID } from "node:crypto";
import { getShopifyConfig, ShopifyConfigError } from "./config";
import { log, errorFields } from "@/lib/log";

/**
 * Single request wrapper for the Shopify Storefront API.
 *
 * - One timeout per request (AbortSignal.timeout)
 * - A request ID sent to Shopify and included in every log line and error
 * - Next.js cache tags / revalidation via the fetch `next` option
 * - One retry for idempotent queries on network failure, 429 or 5xx
 * - Errors normalized to ShopifyError with a stable `code`
 */
export type ShopifyErrorCode =
  | "CONFIG"
  | "TIMEOUT"
  | "NETWORK"
  | "HTTP"
  | "GRAPHQL"
  | "THROTTLED"
  | "INVALID_RESPONSE";

type GraphQLErrorItem = {
  message: string;
  path?: (string | number)[];
  extensions?: Record<string, unknown>;
};

export class ShopifyError extends Error {
  readonly name = "ShopifyError";
  constructor(
    readonly code: ShopifyErrorCode,
    message: string,
    readonly details: {
      requestId: string;
      status?: number;
      graphqlErrors?: GraphQLErrorItem[];
      operation?: string;
    },
  ) {
    super(message);
  }
}

type GraphQLResponse<T> = {
  data?: T;
  errors?: GraphQLErrorItem[];
};

export type ShopifyFetchOptions<V> = {
  query: string;
  variables?: V;
  /** Cache tags for on-demand revalidation. Ignored when `cache` is "no-store". */
  tags?: string[];
  /** Seconds before background revalidation. Ignored when `cache` is "no-store". */
  revalidate?: number | false;
  /** "no-store" for mutations and anything buyer-specific (carts). */
  cache?: "force-cache" | "no-store";
  /** Buyer IP forwarded for rate limiting / fraud signals. Server-side only. */
  buyerIp?: string;
  /** Human-readable operation name for logs. Defaults to the parsed GraphQL name. */
  operation?: string;
  /** Retry once on transient failure. Defaults to true for queries, false for mutations. */
  retry?: boolean;
};

const OPERATION_RE = /(query|mutation)\s+([A-Za-z0-9_]+)/;

function operationName(query: string, fallback?: string): { kind: "query" | "mutation"; name: string } {
  // Fragments precede the operation, so search rather than anchor at ^.
  const m = OPERATION_RE.exec(query);
  return {
    kind: m?.[1] === "mutation" ? "mutation" : "query",
    name: fallback ?? m?.[2] ?? "anonymous",
  };
}

type NextFetchInit = RequestInit & { next?: { tags?: string[]; revalidate?: number | false } };

export async function shopifyFetch<T, V = Record<string, unknown>>(opts: ShopifyFetchOptions<V>): Promise<T> {
  const requestId = randomUUID();
  const op = operationName(opts.query, opts.operation);
  const isMutation = op.kind === "mutation";
  const retry = opts.retry ?? !isMutation;

  let config;
  try {
    config = getShopifyConfig();
  } catch (err) {
    if (err instanceof ShopifyConfigError) {
      throw new ShopifyError("CONFIG", err.message, { requestId, operation: op.name });
    }
    throw err;
  }

  const cacheMode = opts.cache ?? (isMutation ? "no-store" : "force-cache");
  const init: NextFetchInit = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-Shopify-Storefront-Access-Token": config.storefrontToken,
      "X-Request-ID": requestId,
      ...(opts.buyerIp ? { "Shopify-Storefront-Buyer-IP": opts.buyerIp } : {}),
    },
    body: JSON.stringify({ query: opts.query, variables: opts.variables ?? {} }),
    cache: cacheMode,
  };
  if (cacheMode === "force-cache") {
    init.next = { tags: opts.tags, revalidate: opts.revalidate };
  }

  const started = Date.now();
  const base = { requestId, operation: op.name, kind: op.kind, apiVersion: config.apiVersion };
  const maxAttempts = retry ? 2 : 1;

  for (let attempt = 1; ; attempt++) {
    const last = attempt >= maxAttempts;
    try {
      const res = await fetch(config.endpoint, { ...init, signal: AbortSignal.timeout(config.timeoutMs) });
      const durationMs = Date.now() - started;

      if (res.status === 429 || res.status >= 500) {
        if (!last) {
          log.warn("shopify.retry", { ...base, status: res.status, attempt });
          continue;
        }
        throw new ShopifyError(
          res.status === 429 ? "THROTTLED" : "HTTP",
          `Shopify responded ${res.status} for ${op.name}`,
          { requestId, status: res.status, operation: op.name },
        );
      }
      if (!res.ok) {
        throw new ShopifyError("HTTP", `Shopify responded ${res.status} for ${op.name}`, {
          requestId,
          status: res.status,
          operation: op.name,
        });
      }

      let json: GraphQLResponse<T>;
      try {
        json = (await res.json()) as GraphQLResponse<T>;
      } catch {
        throw new ShopifyError("INVALID_RESPONSE", `Non-JSON response for ${op.name}`, {
          requestId,
          status: res.status,
          operation: op.name,
        });
      }

      if (json.errors?.length) {
        const throttled = json.errors.some((e) => e.extensions?.code === "THROTTLED");
        if (throttled && !last) {
          log.warn("shopify.retry", { ...base, reason: "graphql-throttled", attempt });
          continue;
        }
        log.error("shopify.graphql_error", {
          ...base,
          durationMs,
          count: json.errors.length,
          first: json.errors[0].message.slice(0, 200),
        });
        throw new ShopifyError(
          throttled ? "THROTTLED" : "GRAPHQL",
          `GraphQL error in ${op.name}: ${json.errors[0].message}`,
          { requestId, status: res.status, graphqlErrors: json.errors, operation: op.name },
        );
      }
      if (json.data === undefined || json.data === null) {
        throw new ShopifyError("INVALID_RESPONSE", `Empty data for ${op.name}`, {
          requestId,
          status: res.status,
          operation: op.name,
        });
      }

      log.debug("shopify.request", { ...base, durationMs, status: res.status, cache: cacheMode, attempt });
      return json.data;
    } catch (err) {
      if (err instanceof ShopifyError) throw err;
      const timedOut = err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError");
      if (!last) {
        log.warn("shopify.retry", { ...base, reason: timedOut ? "timeout" : "network", attempt, ...errorFields(err) });
        continue;
      }
      log.error(timedOut ? "shopify.timeout" : "shopify.network_error", {
        ...base,
        durationMs: Date.now() - started,
        ...errorFields(err),
      });
      throw new ShopifyError(
        timedOut ? "TIMEOUT" : "NETWORK",
        timedOut
          ? `Shopify request ${op.name} timed out after ${config.timeoutMs}ms`
          : `Network error calling Shopify for ${op.name}`,
        { requestId, operation: op.name },
      );
    }
  }
}

/** Narrow an unknown error to ShopifyError. */
export function isShopifyError(err: unknown): err is ShopifyError {
  return err instanceof ShopifyError;
}
