"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import Image from "next/image";
import type { Product } from "@/lib/catalog";
import { ArrowRight } from "@/components/icons";

/**
 * Popular-items strip: natively scrollable left/right (drag, wheel, or arrows),
 * with a gentle auto-scroll that pauses on hover/touch/focus. The list is
 * duplicated so the auto-scroll loops seamlessly. Halts under reduced-motion.
 */
export function HeroCarousel({ products }: { products: Product[] }) {
  const scroller = useRef<HTMLDivElement>(null);
  const paused = useRef(false);
  const resumeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let raf = 0;
    let last = performance.now();
    const speed = 26; // px / second

    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      if (!paused.current) {
        el.scrollLeft += speed * dt;
        const half = el.scrollWidth / 2;
        if (el.scrollLeft >= half) el.scrollLeft -= half;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  if (products.length === 0) return null;
  const track = [...products, ...products];

  const pause = () => {
    paused.current = true;
    if (resumeTimer.current) clearTimeout(resumeTimer.current);
  };
  const resume = (delay = 0) => {
    if (resumeTimer.current) clearTimeout(resumeTimer.current);
    resumeTimer.current = setTimeout(() => (paused.current = false), delay);
  };

  const nudge = (dir: number) => {
    const el = scroller.current;
    if (!el) return;
    pause();
    el.scrollBy({ left: dir * 256, behavior: "smooth" });
    resume(2500);
  };

  return (
    <div className="w-full">
      {/* Label + arrows */}
      <div className="mb-3 flex items-center justify-between">
        <span className="eyebrow text-paper">Popular items</span>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => nudge(-1)}
            aria-label="Scroll left"
            className="grid h-8 w-8 place-items-center rounded-full border border-paper/25 text-paper transition-colors hover:bg-paper hover:text-ink"
          >
            <ArrowRight width={15} height={15} className="rotate-180" />
          </button>
          <button
            onClick={() => nudge(1)}
            aria-label="Scroll right"
            className="grid h-8 w-8 place-items-center rounded-full border border-paper/25 text-paper transition-colors hover:bg-paper hover:text-ink"
          >
            <ArrowRight width={15} height={15} />
          </button>
        </div>
      </div>

      {/* Scrollable strip */}
      <div
        ref={scroller}
        className="hide-scrollbar flex w-full gap-4 overflow-x-auto"
        onMouseEnter={pause}
        onMouseLeave={() => resume()}
        onFocusCapture={pause}
        onBlurCapture={() => resume()}
        onTouchStart={pause}
        onTouchEnd={() => resume(2500)}
        role="group"
        aria-label="Popular items"
      >
        {track.map((p, i) => (
          <Link
            key={i}
            href={`/product/${p.slug}`}
            tabIndex={i >= products.length ? -1 : 0}
            aria-hidden={i >= products.length}
            className="group block w-40 shrink-0 overflow-hidden rounded-card bg-paper text-ink shadow-lg shadow-ink/20 sm:w-44"
          >
            <div className="relative aspect-[4/5] overflow-hidden bg-surface">
              <Image
                src={p.image_local}
                alt={p.name}
                fill
                sizes="180px"
                className="object-cover transition-transform duration-500 group-hover:scale-105"
              />
              {!p.in_stock && (
                <span className="absolute right-2 top-2 rounded-full bg-paper/90 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-ink">
                  Sold out
                </span>
              )}
            </div>
            <div className="p-3">
              <h3 className="line-clamp-1 text-xs font-semibold">{p.name}</h3>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
