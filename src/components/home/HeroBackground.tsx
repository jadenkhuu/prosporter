"use client";

import { useEffect, useState } from "react";
import Image from "next/image";

// Each slide carries its own object-position so the focal point stays framed.
const SLIDES = [
  { src: "/hero/silhouettes.jpg", position: "60% 72%" }, // nudged up to reveal the players
  { src: "/hero/indoor.jpg", position: "50% 32%" },
  { src: "/hero/beach-match.jpg", position: "50% 42%" },
];

const INTERVAL_MS = 6500;
/**
 * Slides 2 and 3 are not rendered until this has elapsed. They sit inside the
 * viewport, so `loading="lazy"` does nothing for them: the browser fetches all
 * three straight away and they compete with slide 1 — the home page's LCP
 * element — for bandwidth (QA defect D3). Mounting them after first paint,
 * well before the first transition at INTERVAL_MS, leaves the LCP image alone
 * on the wire and still gives the next slide seconds to decode.
 */
const REST_DELAY_MS = 1500;

export function HeroBackground() {
  const [active, setActive] = useState(0);
  const [showRest, setShowRest] = useState(false);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let rotate: ReturnType<typeof setInterval> | undefined;
    const start = setTimeout(() => {
      setShowRest(true);
      rotate = setInterval(() => setActive((i) => (i + 1) % SLIDES.length), INTERVAL_MS);
    }, REST_DELAY_MS);
    return () => {
      clearTimeout(start);
      if (rotate) clearInterval(rotate);
    };
  }, []);

  return (
    <div className="absolute inset-0 -z-10 bg-ink">
      {SLIDES.map((slide, i) => {
        if (i > 0 && !showRest) return null;
        return (
          <Image
            key={slide.src}
            src={slide.src}
            alt=""
            fill
            // `priority` alone: passing an explicit `loading` next to it strips
            // the `fetchpriority="high"` that makes this the LCP fetch, and the
            // deferred slides are lazy by default anyway.
            priority={i === 0}
            sizes="100vw"
            style={{ objectPosition: slide.position }}
            className={`object-cover transition-opacity duration-1000 ease-in-out ${
              i === active ? "opacity-100" : "opacity-0"
            }`}
          />
        );
      })}
    </div>
  );
}
