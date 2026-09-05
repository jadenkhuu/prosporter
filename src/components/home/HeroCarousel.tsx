import Link from "next/link";
import Image from "next/image";
import type { CatalogProduct } from "@/lib/catalog-view";

/**
 * Popular-items "conveyor belt": a CSS-driven marquee that scrolls on its own
 * and pauses while the strip is hovered (see `.marquee` in globals.css). The
 * list is rendered twice so the -50% translate loops seamlessly. Cards are
 * sized in container-query units so ~3.5 are visible regardless of column
 * width, and the edges fade out via a mask gradient.
 */
export function HeroCarousel({ products }: { products: CatalogProduct[] }) {
  if (products.length === 0) return null;
  const track = [...products, ...products];

  return (
    <div className="w-full">
      <div className="mb-3">
        <span className="eyebrow text-paper">Popular items</span>
      </div>

      <div className="marquee fade-x overflow-hidden [container-type:inline-size]">
        <ul className="marquee-track gap-3" aria-label="Popular items">
          {track.map((p, i) => (
            <li
              key={i}
              aria-hidden={i >= products.length}
              className="w-[calc((100cqw-1.5rem)/3.2)] shrink-0"
            >
              <Link
                href={`/product/${p.handle}`}
                tabIndex={i >= products.length ? -1 : 0}
                className="group/card block overflow-hidden rounded-card bg-paper text-ink shadow-lg shadow-ink/20"
              >
                <div className="relative aspect-[4/5] overflow-hidden bg-surface">
                  <Image
                    src={p.image?.url ?? "/products/ace-unisex.png"}
                    alt={p.image?.alt ?? p.title}
                    fill
                    sizes="160px"
                    className="object-cover transition-transform duration-500 group-hover/card:scale-105"
                  />
                  {!p.inStock && (
                    <span className="absolute right-2 top-2 rounded-full bg-paper/90 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-ink">
                      Sold out
                    </span>
                  )}
                </div>
                <div className="p-3">
                  <h3 className="line-clamp-1 text-xs font-semibold">{p.title}</h3>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
