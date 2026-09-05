#!/usr/bin/env python3
"""Authenticated WooCommerce/WordPress audit for the ProSporter migration (CLNT-169).

  python3 scripts/audit/woo_audit.py export   # pull every source entity into exports/ (git-ignored)
  python3 scripts/audit/woo_audit.py report   # build docs/audit/* from exports/ (no personal data)
  python3 scripts/audit/woo_audit.py media    # re-run only the media HEAD reachability check
  python3 scripts/audit/woo_audit.py          # both

Credentials come from .env.local (WOO_BASE_URL, WOO_CONSUMER_KEY, WOO_CONSUMER_SECRET,
WP_MIGRATION_USER, WP_APPLICATION_PASSWORD). Nothing under exports/ may be committed.
"""
import base64, collections, csv, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "exports"
OUT = ROOT / "docs" / "audit"


def load_env():
    env = {}
    for line in (ROOT / ".env.local").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
BASE = ENV["WOO_BASE_URL"].rstrip("/")
WOO_AUTH = f"{ENV['WOO_CONSUMER_KEY']}:{ENV['WOO_CONSUMER_SECRET']}"
WP_AUTH = f"{ENV['WP_MIGRATION_USER']}:{ENV['WP_APPLICATION_PASSWORD']}"


def request(path, auth, method="GET"):
    url = path if path.startswith("http") else BASE + path
    for attempt in range(5):
        req = urllib.request.Request(url, method=method, headers={
            "Authorization": "Basic " + base64.b64encode(auth.encode()).decode(),
            "User-Agent": "prosporter-migration-audit/1.0",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
                return (json.loads(body) if body else None), dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            return {"__error__": e.code, "body": e.read().decode(errors="replace")[:300]}, dict(e.headers)
        except (urllib.error.URLError, TimeoutError):
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise


def paginate(path, auth, per_page=100):
    sep = "&" if "?" in path else "?"
    out, page = [], 1
    while True:
        data, headers = request(f"{path}{sep}per_page={per_page}&page={page}", auth)
        if isinstance(data, dict) and "__error__" in data:
            print(f"  ! {path} page {page}: HTTP {data['__error__']} {data['body'][:120]}")
            return out
        out.extend(data)
        total_pages = int(headers.get("X-WP-TotalPages", headers.get("x-wp-totalpages", "1")) or 1)
        if page >= total_pages or not data:
            return out
        page += 1


def save(name, data):
    p = EXPORTS / f"{name}.json"
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    n = len(data) if isinstance(data, list) else 1
    print(f"  {name}: {n}")
    return data


# ---------------------------------------------------------------- export
def export():
    EXPORTS.mkdir(exist_ok=True)
    os.chmod(EXPORTS, 0o700)
    started = datetime.now(timezone.utc).isoformat()
    print("WooCommerce")
    products = save("products", paginate("/wp-json/wc/v3/products?status=any&context=edit", WOO_AUTH))
    variable_ids = [p["id"] for p in products if p["type"] == "variable"]

    def fetch_variations(pid):
        return pid, paginate(f"/wp-json/wc/v3/products/{pid}/variations?status=any&context=edit", WOO_AUTH)

    variations = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for pid, vs in ex.map(fetch_variations, variable_ids):
            for v in vs:
                v["parent_id"] = pid
            variations.extend(vs)
    save("variations", variations)
    save("product_categories", paginate("/wp-json/wc/v3/products/categories?hide_empty=false", WOO_AUTH))
    save("product_tags", paginate("/wp-json/wc/v3/products/tags?hide_empty=false", WOO_AUTH))
    brands = paginate("/wp-json/wc/v3/products/brands?hide_empty=false", WOO_AUTH)
    save("product_brands", brands)
    attributes = save("product_attributes", paginate("/wp-json/wc/v3/products/attributes", WOO_AUTH))
    terms = {}
    for a in attributes:
        terms[a["slug"]] = paginate(f"/wp-json/wc/v3/products/attributes/{a['id']}/terms", WOO_AUTH)
    save("product_attribute_terms", terms)
    save("shipping_classes", paginate("/wp-json/wc/v3/products/shipping_classes", WOO_AUTH))
    save("product_reviews", paginate("/wp-json/wc/v3/products/reviews?status=all", WOO_AUTH))

    orders = save("orders", paginate("/wp-json/wc/v3/orders?status=any", WOO_AUTH))
    refund_parents = [o["id"] for o in orders if o.get("refunds")]

    def fetch_refunds(oid):
        return paginate(f"/wp-json/wc/v3/orders/{oid}/refunds", WOO_AUTH)

    refunds = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for rs in ex.map(fetch_refunds, refund_parents):
            refunds.extend(rs)
    save("refunds", refunds)
    save("order_notes_sample", [])  # order notes require per-order calls; archived in Workstream 5
    save("customers", paginate("/wp-json/wc/v3/customers?role=all", WOO_AUTH))
    save("coupons", paginate("/wp-json/wc/v3/coupons", WOO_AUTH))
    zones = paginate("/wp-json/wc/v3/shipping/zones", WOO_AUTH)
    for z in zones:
        z["locations"], _ = request(f"/wp-json/wc/v3/shipping/zones/{z['id']}/locations", WOO_AUTH)
        z["methods"], _ = request(f"/wp-json/wc/v3/shipping/zones/{z['id']}/methods", WOO_AUTH)
    save("shipping_zones", zones)
    save("tax_rates", paginate("/wp-json/wc/v3/taxes", WOO_AUTH))
    save("tax_classes", request("/wp-json/wc/v3/taxes/classes", WOO_AUTH)[0])
    save("payment_gateways", request("/wp-json/wc/v3/payment_gateways", WOO_AUTH)[0])
    save("webhooks", paginate("/wp-json/wc/v3/webhooks", WOO_AUTH))
    settings = {}
    for group in ("general", "products", "tax", "shipping", "account", "email", "advanced"):
        settings[group], _ = request(f"/wp-json/wc/v3/settings/{group}", WOO_AUTH)
    save("wc_settings", settings)
    save("system_status", request("/wp-json/wc/v3/system_status", WOO_AUTH)[0])

    print("WordPress")
    save("pages", paginate("/wp-json/wp/v2/pages?status=any&context=edit", WP_AUTH))
    save("posts", paginate("/wp-json/wp/v2/posts?status=any&context=edit", WP_AUTH))
    save("media", paginate("/wp-json/wp/v2/media?context=edit", WP_AUTH))
    save("post_categories", paginate("/wp-json/wp/v2/categories?hide_empty=false", WP_AUTH))
    save("post_tags", paginate("/wp-json/wp/v2/tags?hide_empty=false", WP_AUTH))
    save("users", paginate("/wp-json/wp/v2/users?context=edit", WP_AUTH))
    save("plugins", request("/wp-json/wp/v2/plugins", WP_AUTH)[0])
    save("menus", paginate("/wp-json/wp/v2/menus", WP_AUTH))
    save("menu_items", paginate("/wp-json/wp/v2/menu-items", WP_AUTH))
    save("wp_settings", request("/wp-json/wp/v2/settings", WP_AUTH)[0])
    save("cf7_forms", request("/wp-json/contact-form-7/v1/contact-forms", WP_AUTH)[0])
    save("comments", paginate("/wp-json/wp/v2/comments?status=all&context=edit", WP_AUTH))

    print("Sitemaps")
    urls = []
    try:
        idx = urllib.request.urlopen(BASE + "/sitemap_index.xml", timeout=60).read()
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in ET.fromstring(idx).findall(".//s:loc", ns):
            sub = urllib.request.urlopen(loc.text, timeout=60).read()
            for u in ET.fromstring(sub).findall(".//s:url", ns):
                urls.append({"sitemap": loc.text.rsplit("/", 1)[-1], "loc": u.find("s:loc", ns).text,
                             "lastmod": (u.find("s:lastmod", ns).text if u.find("s:lastmod", ns) is not None else "")})
    except Exception as e:
        print("  ! sitemap:", e)
    save("sitemap_urls", urls)

    media_check(products, variations)
    (EXPORTS / "_manifest.json").write_text(json.dumps({"started": started, "finished": datetime.now(timezone.utc).isoformat(), "base": BASE}, indent=1))


def media_check(products=None, variations=None):
    products = products or load("products")
    variations = variations or load("variations")
    print("Media reachability (HEAD)")
    media = json.loads((EXPORTS / "media.json").read_text())
    product_img_urls = {img["src"] for p in products for img in p.get("images", [])}
    product_img_urls |= {v["image"]["src"] for v in variations if v.get("image")}
    check = sorted(product_img_urls | {m["source_url"] for m in media if m.get("source_url")})

    def head(u):
        try:
            safe = urllib.parse.quote(u, safe=":/?=&%+@")
            req = urllib.request.Request(safe, method="HEAD", headers={"User-Agent": "prosporter-migration-audit/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return u, r.status, r.headers.get("Content-Length", ""), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            return u, e.code, "", ""
        except Exception:
            return u, 0, "", ""

    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(head, check))
    save("media_head", [{"url": u, "status": s, "bytes": b, "type": t} for u, s, b, t in results])


PLUGIN_PATTERNS = {
    "PPOM": r"^PPOM", "Return Refund and Exchange": r"Return Refund|RMA Return", "Yoast SEO": r"^Yoast SEO", "Advanced Coupons": r"^Advanced Coupons",
    "Stripe": r"Stripe Gateway", "WooPayments": r"^WooPayments$", "Product Bundles": r"Product Bundles", "Contact Form 7": r"^Contact Form 7",
    "Flexible Checkout Fields": r"^Flexible Checkout Fields", "Mirakl": r"Mirakl", "SellKit": r"^SellKit", "Variation Swatches": r"^Variation Swatches", "Wishlist": r"Wishlist",
}


# ---------------------------------------------------------------- report
def load(name):
    return json.loads((EXPORTS / f"{name}.json").read_text())


def meta(obj, key, default=""):
    for m in obj.get("meta_data", []):
        if m["key"] == key:
            return m["value"]
    return default


def report():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = load("_manifest")
    products, variations, orders, refunds = load("products"), load("variations"), load("orders"), load("refunds")
    customers, coupons, pages, posts, media = load("customers"), load("coupons"), load("pages"), load("posts"), load("media")
    plugins, sitemap, head = load("plugins"), load("sitemap_urls"), load("media_head")
    head_by_url = {h["url"]: h for h in head}
    C = collections.Counter
    dq = []  # data-quality rows

    def issue(severity, entity, ident, field, problem, owner="purpl", disposition=""):
        dq.append({"severity": severity, "entity": entity, "id": ident, "field": field, "problem": problem, "owner": owner, "disposition": disposition})

    # ---- products & variations
    by_parent = collections.defaultdict(list)
    for v in variations:
        by_parent[v["parent_id"]].append(v)
    skus = C(x["sku"] for x in products + variations if x.get("sku"))
    for p in products:
        pid = f"product:{p['id']}"
        vs = by_parent.get(p["id"], [])
        if p["type"] == "variable" and not vs:
            issue("high", "product", p["id"], "variations", "variable product with no variations")
        if p["type"] == "simple" and not p.get("sku"):
            issue("high", "product", p["id"], "sku", "simple product missing SKU")
        if not p.get("images"):
            issue("high", "product", p["id"], "images", "no product images")
        if not (p.get("description") or "").strip():
            issue("medium", "product", p["id"], "description", "empty description")
        if not (p.get("weight") or "").strip() and not vs:
            issue("low", "product", p["id"], "weight", "no weight (shipping rates by weight will not work)")
        if p["status"] != "publish":
            issue("info", "product", p["id"], "status", f"status={p['status']}; confirm migrate/exclude", owner="client")
        if p["type"] not in ("simple", "variable"):
            issue("high", "product", p["id"], "type", f"type={p['type']} (bundle plugin); no direct Shopify equivalent", owner="client")
        if meta(p, "_yoast_post_redirect_info"):
            issue("info", "product", p["id"], "yoast_redirect", "Yoast redirect info present; include in redirect map")
        if len(p.get("attributes", [])) > 3:
            issue("high", "product", p["id"], "attributes", f"{len(p['attributes'])} attributes; Shopify allows 3 options")
        if len(vs) > 100:
            issue("high", "product", p["id"], "variations", f"{len(vs)} variations; Shopify limit 100 (2048 with extended)")
        for img in p.get("images", []):
            if not (img.get("alt") or "").strip():
                issue("low", "product", p["id"], f"image:{img['id']}", "missing alt text")
            h = head_by_url.get(img["src"])
            if h and h["status"] != 200:
                issue("high", "product", p["id"], f"image:{img['id']}", f"image HEAD returned {h['status']}")
    for v in variations:
        if not v.get("sku"):
            issue("high", "variation", v["id"], "sku", f"variation missing SKU (parent {v['parent_id']})")
        elif skus[v["sku"]] > 1:
            issue("high", "variation", v["id"], "sku", f"duplicate SKU {v['sku']} used {skus[v['sku']]} times")
        if not v.get("regular_price"):
            issue("high", "variation", v["id"], "regular_price", f"variation has no regular price (parent {v['parent_id']})")
        if v.get("manage_stock") and v.get("stock_quantity") is not None and v["stock_quantity"] < 0:
            issue("medium", "variation", v["id"], "stock_quantity", f"negative stock {v['stock_quantity']}")
        if not (v.get("weight") or "").strip():
            issue("low", "variation", v["id"], "weight", "no weight")
    for sku, n in skus.items():
        if n > 1 and not any(r["field"] == "sku" and sku in r["problem"] for r in dq):
            issue("high", "product", sku, "sku", f"duplicate SKU across products used {n} times")

    attr_values = collections.defaultdict(set)
    for p in products:
        for a in p.get("attributes", []):
            attr_values[a["name"]].update(a.get("options", []))
    plugin_meta_keys = C(m["key"] for p in products for m in p.get("meta_data", []))

    # ---- orders
    order_ids = [o["id"] for o in orders]
    dates = sorted(o["date_created"] for o in orders)
    line_meta = C(m["key"] for o in orders for l in o["line_items"] for m in l.get("meta_data", []))
    order_meta = C(m["key"] for o in orders for m in o.get("meta_data", []))
    guest_emails = {o["billing"]["email"].lower() for o in orders if not o.get("customer_id") and o["billing"].get("email")}
    open_orders = [o for o in orders if o["status"] in ("processing", "on-hold", "pending")]
    for o in open_orders:
        issue("high", "order", o["id"], "status", f"open order status={o['status']} at snapshot; must be resolved or re-snapshotted at cutover", owner="client")
    tracking_keys = [k for k in set(order_meta) | set(line_meta) if re.search(r"track|carrier|shipment|consign|ship_", k, re.I)]

    # ---- customers
    emails = C(c["email"].lower() for c in customers if c.get("email"))
    dup_emails = {e: n for e, n in emails.items() if n > 1}
    no_address = sum(1 for c in customers if not (c.get("billing", {}).get("address_1") or c.get("shipping", {}).get("address_1")))
    consent_keys = sorted({m["key"] for c in customers for m in c.get("meta_data", []) if re.search(r"consent|newsletter|marketing|subscribe|optin|opt_in", m["key"], re.I)}
                          | {k for k in order_meta if re.search(r"consent|newsletter|marketing|subscribe|optin|opt_in", k, re.I)})
    for e, n in dup_emails.items():
        issue("medium", "customer", "redacted", "email", f"duplicate customer email ({n} accounts)", owner="client", disposition="merge or pick canonical")

    # ---- content
    shortcode_re = re.compile(r"\[(\w[\w-]*)")
    content_rows = []
    internal_links = C()
    for kind, items in (("page", pages), ("post", posts)):
        for it in items:
            raw = it["content"].get("raw") or ""
            shortcodes = C(shortcode_re.findall(raw))
            imgs = re.findall(r'<img[^>]+src="([^"]+)"', raw)
            links = re.findall(r'href="([^"]+)"', raw)
            for l in links:
                if l.startswith(BASE) or l.startswith("/"):
                    internal_links[l] += 1
            yh = it.get("yoast_head_json") or {}
            content_rows.append({
                "type": kind, "id": it["id"], "slug": it["slug"], "status": it["status"], "author": it.get("author"),
                "date": it.get("date"), "modified": it.get("modified"), "link": it.get("link"), "template": it.get("template", ""),
                "elementor": "yes" if (it.get("meta", {}) or {}).get("_elementor_edit_mode") == "builder" or "elementor" in raw else "no",
                "words": len(re.sub(r"<[^>]+>", " ", raw).split()), "embedded_images": len(imgs), "shortcodes": ";".join(f"{k}x{n}" for k, n in shortcodes.items()),
                "internal_links": sum(1 for l in links if l.startswith(BASE) or l.startswith("/")),
                "yoast_title": yh.get("title", ""), "yoast_description": yh.get("description", ""), "canonical": yh.get("canonical", ""),
                "robots": (yh.get("robots") or {}).get("index", ""), "og_image": (yh.get("og_image") or [{}])[0].get("url", "") if yh.get("og_image") else "",
            })
            if it["status"] != "publish":
                issue("info", kind, it["id"], "status", f"status={it['status']} (slug '{it['slug']}'); confirm migrate/exclude", owner="client")
            if re.search(r"-2$", it["slug"] or ""):
                issue("medium", kind, it["id"], "slug", f"looks like a duplicate page ('{it['slug']}')", owner="client", disposition="confirm canonical")
            if kind == "post" and not raw.strip():
                issue("medium", kind, it["id"], "content", "empty post body")
    slugs = C((r["type"], r["slug"]) for r in content_rows)

    # ---- media inventory
    media_rows = []
    for m in media:
        h = head_by_url.get(m.get("source_url"), {})
        md = m.get("media_details", {}) or {}
        media_rows.append({"attachment_id": m["id"], "file": md.get("file", ""), "source_url": m.get("source_url", ""), "mime": m.get("mime_type", ""),
                           "width": md.get("width", ""), "height": md.get("height", ""), "filesize": md.get("filesize", ""), "alt": (m.get("alt_text") or "").strip(),
                           "title": (m.get("title") or {}).get("raw", ""), "attached_to_post": m.get("post") or "", "date": m.get("date"),
                           "http_status": h.get("status", ""), "used_by_products": ""})
    used = collections.defaultdict(set)
    for p in products:
        for img in p.get("images", []):
            used[img["id"]].add(p["id"])
    for v in variations:
        if v.get("image"):
            used[v["image"]["id"]].add(v["parent_id"])
    for r in media_rows:
        r["used_by_products"] = ";".join(map(str, sorted(used.get(r["attachment_id"], []))))
        if r["http_status"] not in (200, ""):
            issue("high", "media", r["attachment_id"], "source_url", f"HEAD returned {r['http_status']}")
    media_missing_alt = sum(1 for r in media_rows if not r["alt"] and str(r["mime"]).startswith("image/"))
    unreachable_media = sum(1 for r in media_rows if r["http_status"] not in (200, ""))

    # ---- URL inventory
    url_rows = []
    for u in sitemap:
        url_rows.append({"url": u["loc"], "source": "sitemap:" + u["sitemap"], "type": u["sitemap"].split("-sitemap")[0], "status": "publish", "lastmod": u["lastmod"], "proposed_destination": "", "redirect_type": "", "notes": ""})
    seen = {r["url"] for r in url_rows}
    for p in products:
        if p.get("permalink") and p["permalink"] not in seen:
            url_rows.append({"url": p["permalink"], "source": "wc:product", "type": "product", "status": p["status"], "lastmod": p.get("date_modified", ""), "proposed_destination": f"/products/{p['slug']}", "redirect_type": "301", "notes": ""})
    for r in content_rows:
        if r["link"] and r["link"] not in seen:
            url_rows.append({"url": r["link"], "source": f"wp:{r['type']}", "type": r["type"], "status": r["status"], "lastmod": r["modified"], "proposed_destination": "", "redirect_type": "", "notes": ""})
    for u in url_rows:
        if u["source"].startswith("sitemap:product") and u["type"] == "product":
            slug = u["url"].rstrip("/").rsplit("/", 1)[-1]
            u["proposed_destination"] = f"/products/{slug}"
            u["redirect_type"] = "301"
    for u in url_rows:
        if u["type"] in ("product_cat",):
            u["proposed_destination"] = "/shop/…  (per approved collection mapping)"
            u["redirect_type"] = "301"
        if u["type"] in ("page", "post"):
            u["proposed_destination"] = urllib.parse.urlparse(u["url"]).path
            u["redirect_type"] = "keep path (200) or 301"

    # ---- plugin register
    active = [p for p in plugins if p.get("status") == "active"]
    sys_status = load("system_status")
    db_tables = list((sys_status.get("database", {}) or {}).get("database_tables", {}).get("other", {}).keys()) if isinstance(sys_status, dict) else []
    fingerprints = {
        "PPOM": ("Product add-on fields", sum(1 for k in line_meta if k == "_ppom_fields") and line_meta["_ppom_fields"], "line items", "migrate as line-item properties / metafield-driven form"),
        "Return Refund and Exchange": ("RMA requests", sum(v for k, v in order_meta.items() if k.startswith("wps_")), "order meta keys (sum)", "archive; Shopify returns handled natively or via app"),
        "Yoast SEO": ("SEO metadata", sum(v for k, v in plugin_meta_keys.items() if k.startswith("_yoast_wpseo_")), "product meta keys (sum)", "export to Shopify SEO fields / Next metadata"),
        "Advanced Coupons": ("coupon rules", sum(1 for c in coupons if any(m["key"].startswith("_acfw") for m in c.get("meta_data", []))), "coupons", "recreate as Shopify discounts; check unsupported rules"),
        "Stripe": ("payments", sum(1 for o in orders if "stripe" in (o.get("payment_method") or "")), "orders", "gateway decision (CLNT-170)"),
        "WooPayments": ("payments", sum(1 for o in orders if o.get("payment_method") == "woocommerce_payments"), "orders", "gateway decision (CLNT-170)"),
        "Product Bundles": ("bundles", sum(1 for p in products if p["type"] not in ("simple", "variable")) , "products", "manual recreation; decide bundle approach"),
        "Contact Form 7": ("forms", len(load("cf7_forms")) if isinstance(load("cf7_forms"), list) else 0, "forms", "rebuild in Next.js with server action / email provider"),
        "Flexible Checkout Fields": ("custom checkout fields", sum(v for k, v in order_meta.items() if k.startswith("_fcf") or k.startswith("fcf_")), "order meta keys (sum)", "not available on Shopify hosted checkout; client decision"),
        "Mirakl": ("marketplace sync", sum(v for k, v in order_meta.items() if "mirakl" in k.lower()), "order meta keys (sum)", "confirm decommission"),
        "SellKit": ("funnels/checkout", sum(v for k, v in order_meta.items() if "sellkit" in k.lower()), "order meta keys (sum)", "confirm decommission"),
        "Variation Swatches": ("swatch display", sum(1 for k in plugin_meta_keys if "swatch" in k.lower()), "product meta keys", "display-only; recreate in Next.js UI"),
        "Wishlist": ("wishlists", sum(1 for k in order_meta if "wish" in k.lower()), "order meta keys", "display-only; not migrated"),
    }
    reg = [f"# Plugin and integration register\n", f"Snapshot: {manifest['finished'][:19]}Z from `{BASE}` (authenticated). {len(active)} active plugins of {len(plugins)} installed.\n",
           "Usage evidence counts data fingerprints found in the authenticated export; a zero means no product, order, or coupon carries data from the plugin and it is a candidate for 'not migrated'.\n",
           "| Plugin | Version | Usage evidence | Holds migratable data | Disposition |", "|---|---:|---|---|---|"]
    for p in sorted(active, key=lambda x: x["name"].lower()):
        name = re.sub(r"&amp;", "&", p["name"])
        ev, holds, disp = "no data fingerprint", "no", "not migrated (confirm with client)"
        for key, (what, n, unit, d) in fingerprints.items():
            if re.search(PLUGIN_PATTERNS[key], name, re.I):
                ev = f"{n} {unit} ({what})"
                holds = "yes" if n else "no"
                disp = d if n else "installed but unused; not migrated"
        if "woocommerce" == name.lower():
            ev, holds, disp = f"{len(products)} products, {len(orders)} orders, {len(customers)} customers", "yes", "source of truth for migration"
        if "updraft" in name.lower():
            ev, holds, disp = "backup plugin", "n/a", "use for CLNT-168 verified backup"
        if "elementor" in name.lower():
            ev, holds, disp = f"{sum(1 for r in content_rows if r['elementor']=='yes')} pages/posts built with Elementor", "yes (layout)", "content re-authored in Next.js; copy migrated as HTML/Markdown"
        reg.append(f"| {name} | {p.get('version','')} | {ev} | {holds} | {disp} |")
    reg += ["", "## Payment, refund, fulfilment and tracking data locations", "",
            f"- Payment methods used across {len(orders)} orders: " + ", ".join(f"{k or '(none)'} ×{v}" for k, v in C((o.get('payment_method_title') or o.get('payment_method') or '') for o in orders).most_common()),
            f"- Refund objects: {len(refunds)} across {sum(1 for o in orders if o.get('refunds'))} orders (Woo core `shop_order_refund`; Stripe refund IDs in `_stripe_refund_id` ×{order_meta.get('_stripe_refund_id',0)})",
            f"- RMA plugin (wps_*) meta present on {sum(1 for o in orders if any(m['key'].startswith('wps_') for m in o.get('meta_data',[])))} orders",
            f"- Order/line meta keys that look like carrier/tracking data: {', '.join(sorted(tracking_keys)) or 'none found'}",
            f"- Non-core database tables reported by WooCommerce system status: {len(db_tables)} (see `exports/system_status.json`)",
            "- Invoices/packing slips: no invoice plugin active; WooCommerce order emails are the only customer-facing documents.",
            "", "## Sitemap / SEO", "", f"- Yoast sitemap URLs: {len(sitemap)} across {len(set(u['sitemap'] for u in sitemap))} sub-sitemaps",
            "- Yoast Premium redirect manager is not exposed via REST: export `SEO → Redirects → Export` (CSV) manually and add to `url-inventory.csv`.",
            ]
    (OUT / "plugin-and-integration-register.md").write_text("\n".join(reg) + "\n")

    # ---- source inventory
    inv = {
        "snapshot": manifest, "source": BASE,
        "products": {"total": len(products), "by_status": C(p["status"] for p in products), "by_type": C(p["type"] for p in products),
                     "on_sale": sum(1 for p in products if p.get("on_sale")), "featured": sum(1 for p in products if p.get("featured")),
                     "without_images": sum(1 for p in products if not p.get("images")), "with_yoast_title": sum(1 for p in products if meta(p, "_yoast_wpseo_title")),
                     "with_yoast_metadesc": sum(1 for p in products if meta(p, "_yoast_wpseo_metadesc")), "max_attributes": max((len(p.get("attributes", [])) for p in products), default=0),
                     "tax_status": C(p.get("tax_status") for p in products), "tax_class": C(p.get("tax_class") or "standard" for p in products),
                     "stock_status": C(p.get("stock_status") for p in products), "plugin_meta_keys": dict(plugin_meta_keys.most_common())},
        "variations": {"total": len(variations), "by_status": C(v["status"] for v in variations), "with_sku": sum(1 for v in variations if v.get("sku")),
                       "unique_skus": len(skus), "duplicate_skus": sum(1 for n in skus.values() if n > 1), "with_image": sum(1 for v in variations if v.get("image")),
                       "manage_stock": sum(1 for v in variations if v.get("manage_stock")), "total_stock_units": sum((v.get("stock_quantity") or 0) for v in variations if v.get("manage_stock")),
                       "backorders": C(v.get("backorders") for v in variations), "with_sale_price": sum(1 for v in variations if v.get("sale_price")),
                       "with_weight": sum(1 for v in variations if (v.get("weight") or "").strip()), "max_per_product": max((len(v) for v in by_parent.values()), default=0),
                       "stock_status": C(v.get("stock_status") for v in variations)},
        "taxonomy": {"product_categories": len(load("product_categories")), "product_tags": len(load("product_tags")), "brands": len(load("product_brands")) if isinstance(load("product_brands"), list) else 0,
                     "global_attributes": [a["name"] for a in load("product_attributes")], "attribute_values": {k: sorted(v) for k, v in attr_values.items()}, "shipping_classes": len(load("shipping_classes"))},
        "orders": {"total": len(orders), "by_status": C(o["status"] for o in orders), "highest_id": max(order_ids), "lowest_id": min(order_ids), "first": dates[0], "last": dates[-1],
                   "open_at_snapshot": len(open_orders), "guest_orders": sum(1 for o in orders if not o.get("customer_id")), "unique_guest_emails": len(guest_emails),
                   "currencies": C(o["currency"] for o in orders), "payment_methods": C(o.get("payment_method_title") or o.get("payment_method") or "(none)" for o in orders),
                   "refunds": len(refunds), "orders_with_refunds": sum(1 for o in orders if o.get("refunds")), "line_items": sum(len(o["line_items"]) for o in orders),
                   "line_item_meta_keys": dict(line_meta.most_common()), "order_meta_keys": dict(order_meta.most_common()), "tracking_like_keys": sorted(tracking_keys)},
        "customers": {"total": len(customers), "by_role": C(c.get("role") for c in customers), "duplicate_emails": len(dup_emails), "without_address": no_address,
                      "paying": sum(1 for c in customers if c.get("is_paying_customer")), "consent_like_meta_keys": consent_keys},
        "coupons": {"total": len(coupons), "by_type": C(c["discount_type"] for c in coupons), "active": sum(1 for c in coupons if not c.get("date_expires") or c["date_expires"] > manifest["finished"]),
                    "codes": [{"code": c["code"], "type": c["discount_type"], "amount": c["amount"], "uses": c["usage_count"], "expires": c.get("date_expires"),
                               "product_ids": len(c.get("product_ids", [])), "categories": len(c.get("product_categories", [])), "acfw_meta": sorted(m["key"] for m in c.get("meta_data", []) if m["key"].startswith("_acfw"))} for c in coupons]},
        "shipping": [{"zone": z["name"], "locations": [l["code"] for l in (z.get("locations") or [])], "methods": [{"title": m["title"], "id": m["method_id"], "enabled": m["enabled"], "cost": (m.get("settings", {}).get("cost") or {}).get("value", "")} for m in (z.get("methods") or [])]} for z in load("shipping_zones")],
        "tax": {"rates": len(load("tax_rates")), "classes": [c["name"] for c in load("tax_classes")], "prices_include_tax": next((s["value"] for s in load("wc_settings")["tax"] if s["id"] == "woocommerce_prices_include_tax"), ""),
                "calc_taxes": next((s["value"] for s in load("wc_settings")["general"] if s["id"] == "woocommerce_calc_taxes"), "")},
        "payment_gateways_enabled": [g["id"] for g in load("payment_gateways") if g.get("enabled")],
        "content": {"pages": C(p["status"] for p in pages), "posts": C(p["status"] for p in posts), "authors": len({r["author"] for r in content_rows}), "post_categories": len(load("post_categories")),
                    "post_tags": len(load("post_tags")), "users_total": len(load("users")), "comments": len(load("comments")), "menus": [m["name"] for m in load("menus")] if isinstance(load("menus"), list) else [],
                    "menu_items": len(load("menu_items")) if isinstance(load("menu_items"), list) else 0, "cf7_forms": [f["title"] for f in load("cf7_forms")] if isinstance(load("cf7_forms"), list) else [],
                    "shortcodes_used": dict(C(s.split("x")[0] for r in content_rows for s in r["shortcodes"].split(";") if s).most_common()),
                    "elementor_pages": sum(1 for r in content_rows if r["elementor"] == "yes"), "internal_links": len(internal_links),
                    "duplicate_slug_suffix": [r["slug"] for r in content_rows if (r["slug"] or "").endswith("-2")],
                    "yoast": {"with_title": sum(1 for r in content_rows if r["yoast_title"]), "with_description": sum(1 for r in content_rows if r["yoast_description"]), "noindex": sum(1 for r in content_rows if r["robots"] == "noindex")}},
        "media": {"attachments": len(media), "by_mime": C(m.get("mime_type") for m in media), "missing_alt": media_missing_alt, "unreachable": unreachable_media,
                  "used_by_products": sum(1 for r in media_rows if r["used_by_products"]), "total_bytes": sum(int(r["filesize"] or 0) for r in media_rows)},
        "urls": {"sitemap_urls": len(sitemap), "sitemaps": dict(C(u["sitemap"] for u in sitemap)), "inventory_rows": len(url_rows)},
        "data_quality": {"rows": len(dq), "by_severity": C(r["severity"] for r in dq)},
        "discrepancies": {"repo_mock_products": 94, "public_store_api_products_2026_09_03": 141, "authenticated_products": len(products), "authenticated_published": sum(1 for p in products if p["status"] == "publish")},
    }
    (OUT / "source-inventory.json").write_text(json.dumps(inv, indent=2, ensure_ascii=False, default=lambda o: dict(o) if isinstance(o, C) else str(o)))

    def write_csv(name, rows, fields):
        with (OUT / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    sev = {"high": 0, "medium": 1, "low": 2, "info": 3}
    write_csv("data-quality-report.csv", sorted(dq, key=lambda r: (sev[r["severity"]], r["entity"], str(r["id"]))), ["severity", "entity", "id", "field", "problem", "owner", "disposition"])
    write_csv("url-inventory.csv", url_rows, ["url", "source", "type", "status", "lastmod", "proposed_destination", "redirect_type", "notes"])
    write_csv("media-inventory.csv", media_rows, ["attachment_id", "file", "source_url", "mime", "width", "height", "filesize", "alt", "title", "attached_to_post", "used_by_products", "date", "http_status"])
    write_csv("content-inventory.csv", content_rows, list(content_rows[0].keys()) if content_rows else [])
    print(json.dumps({k: inv[k] for k in ("products", "variations", "orders", "customers", "media", "urls", "data_quality", "discrepancies")}, indent=1, default=lambda o: dict(o) if isinstance(o, C) else str(o)))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("export", "all"):
        export()
    if mode == "media":
        media_check()
    if mode in ("report", "all"):
        report()
