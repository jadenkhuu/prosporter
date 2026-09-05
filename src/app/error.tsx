"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function ErrorPage({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    // Server errors arrive with a generic message plus a digest that matches
    // the server-side log line. Never show or log raw details client-side.
    console.error("route error", error.digest ?? error.name);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-[1400px] flex-col items-center px-4 py-24 text-center sm:px-6 lg:px-8 lg:py-32">
      <p className="eyebrow text-subtle">Something went wrong</p>
      <h1 className="display mt-3 text-4xl sm:text-5xl">Timeout on our end</h1>
      <p className="mt-4 max-w-md text-sm text-muted">
        We couldn&apos;t load this page. Try again in a moment, or head back to the shop.
      </p>
      {error.digest && (
        <p className="mt-2 font-mono text-[11px] text-subtle">Reference {error.digest}</p>
      )}
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <button
          onClick={() => retry()}
          className="rounded-full bg-ink px-5 py-2.5 text-sm font-semibold text-paper transition-colors hover:bg-ink-2"
        >
          Try again
        </button>
        <Link
          href="/shop"
          className="rounded-full border border-line px-5 py-2.5 text-sm font-semibold transition-colors hover:bg-surface"
        >
          Shop all
        </Link>
      </div>
    </div>
  );
}
