/* Decorative topographic contour lines — echoes the .moodboard 03-image banner.
   Purely ornamental; aria-hidden and excluded from interaction. */
export function TopoLines({ className = "" }: { className?: string }) {
  // One organic blob, redrawn at increasing scales to read as nested contours.
  const blob =
    "M-86,-34 C-66,-92 4,-110 54,-80 C104,-50 112,8 82,50 C52,94 -18,102 -60,72 C-102,42 -106,24 -86,-34 Z";
  const rings = [0.32, 0.46, 0.6, 0.74, 0.88, 1.02, 1.16, 1.3];

  return (
    <svg
      aria-hidden
      className={className}
      viewBox="-160 -160 320 320"
      fill="none"
      preserveAspectRatio="xMidYMid slice"
    >
      <g stroke="var(--color-neon)" strokeWidth="0.6">
        {rings.map((s, i) => (
          <path
            key={i}
            d={blob}
            transform={`scale(${s})`}
            style={{ opacity: 0.06 + i * 0.022 }}
          />
        ))}
      </g>
    </svg>
  );
}
