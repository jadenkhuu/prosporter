import Link from "next/link";
import Image from "next/image";
import { catalog, taxonomy, byNewest, getPopularProducts } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";
import { HeroCarousel } from "@/components/home/HeroCarousel";
import { HeroBackground } from "@/components/home/HeroBackground";
import { ArrowRight } from "@/components/icons";

// Pick a representative image for a category (first in-stock product).
function categoryImage(catId: string): string {
  const p =
    catalog.find((x) => x.primary_category === catId && x.in_stock) ??
    catalog.find((x) => x.primary_category === catId);
  return p?.image_local ?? "/products/ace-unisex.png";
}

function surfaceImage(surface: "beach" | "indoor"): string {
  const p = catalog.find((x) => x.surface === surface);
  return p?.image_local ?? "/products/ace-unisex.png";
}

export default function Home() {
  const newArrivals = byNewest(catalog).slice(0, 8);
  const clubs = taxonomy.collections.filter((c) => c.type === "club");
  const popular = getPopularProducts();

  return (
    <div>
      {/* ───────────────────────── Hero ───────────────────────── */}
      <section className="relative isolate overflow-hidden bg-ink text-paper">
        {/* Rotating background photos */}
        <HeroBackground />
        {/* Green wash from the left to keep the copy legible */}
        <div className="pointer-events-none absolute inset-0 -z-[5] bg-gradient-to-r from-green-deeper/90 via-green-deeper/40 to-transparent" />

        <div className="mx-auto grid max-w-[1400px] items-center gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[1fr_minmax(0,500px)] lg:gap-12 lg:px-8 lg:py-24">
          {/* Copy */}
          <div className="max-w-xl">
            <h1 className="display text-5xl italic leading-[0.92] sm:text-6xl lg:text-7xl">
              Play in
              <br />
              your <span className="text-neon">colours</span>
            </h1>
            <p className="mt-6 max-w-md text-base leading-relaxed text-surface-2">
              Volleyball apparel, club teamwear and protective gear for indoor and
              beach. Shipped across Australia.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/shop"
                className="flex items-center gap-2 rounded-full bg-paper px-6 py-3.5 text-sm font-semibold text-ink transition-colors hover:bg-surface-2"
              >
                Shop all gear
                <ArrowRight width={18} height={18} />
              </Link>
              <Link
                href="/shop/beach"
                className="flex items-center gap-2 rounded-full border border-paper/30 px-6 py-3.5 text-sm font-semibold text-paper transition-colors hover:bg-paper/10"
              >
                Beach collection
              </Link>
            </div>
          </div>

          {/* Most-popular carousel */}
          <div className="w-full">
            <HeroCarousel products={popular} />
          </div>
        </div>
      </section>

      {/* ──────────────────── Shop by type ──────────────────── */}
      <section className="mx-auto max-w-[1400px] px-4 py-16 sm:px-6 lg:px-8">
        <div className="mb-8 flex items-end justify-between">
          <div>
            <p className="eyebrow text-subtle">Browse the range</p>
            <h2 className="display mt-2 text-3xl sm:text-4xl">Shop by category</h2>
          </div>
          <Link
            href="/shop"
            className="hidden items-center gap-1.5 text-sm font-semibold text-ink hover:text-green-deep sm:flex"
          >
            View all <ArrowRight width={16} height={16} />
          </Link>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {taxonomy.primary_nav.map((cat) => (
            <Link
              key={cat.id}
              href={`/shop/${cat.id}`}
              className="group relative aspect-[4/5] overflow-hidden rounded-card bg-surface"
            >
              <Image
                src={categoryImage(cat.id)}
                alt={cat.label}
                fill
                sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 16vw"
                className="object-cover transition-transform duration-500 group-hover:scale-105"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-ink/75 via-ink/15 to-transparent" />
              <div className="absolute inset-x-0 bottom-0 p-3">
                <h3 className="display text-sm leading-tight text-paper">{cat.label}</h3>
                <p className="mt-0.5 text-[11px] text-surface-2">{cat.count} items</p>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ──────────────────── Indoor / Beach split ──────────────────── */}
      <section className="mx-auto max-w-[1400px] px-4 pb-16 sm:px-6 lg:px-8">
        <div className="grid gap-x-6 gap-y-8 md:grid-cols-2">
          {(["indoor", "beach"] as const).map((s) => (
            <Link key={s} href={`/shop/${s}`} className="group block">
              {/* Title sits above the card to distinguish these from the category tiles */}
              <div className="mb-3 flex items-end justify-between">
                <div>
                  <p className="eyebrow text-subtle">
                    {s === "beach" ? "Sand & sun" : "Court season"}
                  </p>
                  <h3 className="display mt-1 text-2xl text-ink sm:text-3xl">
                    {s === "beach" ? "Beach" : "Indoor"}
                  </h3>
                </div>
                <span className="flex items-center gap-1.5 text-sm font-semibold text-ink transition-colors group-hover:text-green-deep">
                  Shop the collection
                  <ArrowRight width={16} height={16} />
                </span>
              </div>
              <div className="relative aspect-[16/9] overflow-hidden rounded-card bg-surface">
                <Image
                  src={surfaceImage(s)}
                  alt={`${s} collection`}
                  fill
                  sizes="(max-width: 768px) 100vw, 50vw"
                  className="object-cover transition-transform duration-500 group-hover:scale-105"
                />
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ──────────────────── New arrivals ──────────────────── */}
      <section className="mx-auto max-w-[1400px] px-4 pb-16 sm:px-6 lg:px-8">
        <div className="mb-8 flex items-end justify-between">
          <div>
            <p className="eyebrow text-subtle">Just dropped</p>
            <h2 className="display mt-2 text-3xl sm:text-4xl">New arrivals</h2>
          </div>
          <Link
            href="/shop/new-arrivals"
            className="flex items-center gap-1.5 text-sm font-semibold text-ink hover:text-green-deep"
          >
            <span className="hidden sm:inline">View all</span>
            <ArrowRight width={16} height={16} />
          </Link>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-8 md:grid-cols-4">
          {newArrivals.map((p, i) => (
            <ProductCard key={p.id} product={p} priority={i < 4} />
          ))}
        </div>
      </section>

      {/* ──────────────────── Clubs strip ──────────────────── */}
      <section className="bg-surface">
        <div className="mx-auto max-w-[1400px] px-4 py-16 sm:px-6 lg:px-8">
          <div className="mb-8 max-w-2xl">
            <p className="eyebrow text-subtle">Made for your team</p>
            <h2 className="display mt-2 text-3xl sm:text-4xl">Clubs &amp; teams</h2>
            <p className="mt-3 text-base leading-relaxed text-muted">
              Official kits and custom teamwear for clubs across the country. Find
              your club’s store below.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            {clubs.map((club) => {
              const img =
                catalog.find((p) => p.clubs.includes(club.id))?.image_local ??
                "/products/ace-unisex.png";
              return (
                <Link
                  key={club.id}
                  href={`/shop/clubs/${club.id}`}
                  className="group flex items-center gap-4 rounded-card border border-line bg-paper p-4 transition-colors hover:border-muted"
                >
                  <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-card bg-surface">
                    <Image src={img} alt={club.label} fill sizes="64px" className="object-cover" />
                  </div>
                  <div className="flex-1">
                    <h3 className="text-sm font-semibold text-ink">{club.label}</h3>
                    <p className="text-xs text-muted">{club.count} items</p>
                  </div>
                  <ArrowRight
                    width={18}
                    height={18}
                    className="text-subtle transition-colors group-hover:text-green-deep"
                  />
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      {/* ──────────────────── Value props ──────────────────── */}
      <section className="mx-auto max-w-[1400px] px-4 py-16 sm:px-6 lg:px-8">
        <div className="grid gap-8 sm:grid-cols-3">
          {[
            { t: "Free shipping over $150", d: "Fast dispatch, Australia-wide." },
            { t: "30-day easy returns", d: "Unworn, with tags — no fuss." },
            { t: "Trusted by clubs", d: "Official teamwear partner." },
          ].map((v) => (
            <div key={v.t} className="border-t-2 border-ink pt-4">
              <h3 className="text-base font-semibold text-ink">{v.t}</h3>
              <p className="mt-1 text-sm text-muted">{v.d}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
