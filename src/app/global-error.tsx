"use client";

/**
 * Replaces the root layout when it throws. Must render its own <html>/<body>
 * and cannot rely on globals.css or fonts, so styles are inline.
 */
export default function GlobalError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#ffffff",
          color: "#181817",
          fontFamily: "system-ui, sans-serif",
          textAlign: "center",
          padding: "2rem",
        }}
      >
        <div>
          <p style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "#8c9286", fontWeight: 600 }}>
            ProSporter
          </p>
          <h1 style={{ fontSize: 32, margin: "0.5rem 0 1rem", textTransform: "uppercase", fontWeight: 800 }}>
            Something went wrong
          </h1>
          <p style={{ color: "#5b6157", fontSize: 14, maxWidth: 420, margin: "0 auto" }}>
            The page failed to load. Please try again.
          </p>
          {error.digest && (
            <p style={{ fontFamily: "monospace", fontSize: 11, color: "#8c9286", marginTop: 8 }}>
              Reference {error.digest}
            </p>
          )}
          <button
            onClick={() => retry()}
            style={{
              marginTop: 24,
              borderRadius: 999,
              background: "#181817",
              color: "#fff",
              border: 0,
              padding: "10px 20px",
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
