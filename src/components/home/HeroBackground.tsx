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

export function HeroBackground() {
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setInterval(
      () => setActive((i) => (i + 1) % SLIDES.length),
      INTERVAL_MS,
    );
    return () => clearInterval(id);
  }, []);

  return (
    <div className="absolute inset-0 -z-10 bg-ink">
      {SLIDES.map((slide, i) => (
        <Image
          key={slide.src}
          src={slide.src}
          alt=""
          fill
          priority={i === 0}
          sizes="100vw"
          style={{ objectPosition: slide.position }}
          className={`object-cover transition-opacity duration-1000 ease-in-out ${
            i === active ? "opacity-100" : "opacity-0"
          }`}
        />
      ))}
    </div>
  );
}
