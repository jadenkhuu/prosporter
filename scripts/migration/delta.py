#!/usr/bin/env python3
"""Builds a controlled delta copy of a source export directory.

Used by the idempotency proof: the second source differs from the first by
exactly four known changes, so the loader can be shown to update only those
records.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from common import read_json, rel, write_json
from normalize import ATTRIBUTE_POLICY
from transform import FUNCTIONAL_PAGE

DELTA_MARK = " (Delta Test)"


def build_delta_source(source_dir: Path, delta_dir: Path) -> dict:
    source_dir, delta_dir = Path(source_dir), Path(delta_dir)
    if delta_dir.exists():
        shutil.rmtree(delta_dir)
    delta_dir.mkdir(parents=True)
    for path in sorted(source_dir.glob("*.json")):
        shutil.copy2(path, delta_dir / path.name)

    products = read_json(delta_dir / "products.json")
    variations = read_json(delta_dir / "variations.json")

    by_parent: dict[int, list] = {}
    for variation in variations:
        by_parent.setdefault(variation.get("parent_id"), []).append(variation)

    product = _pick_product(products, by_parent)
    rows = sorted(by_parent[product["id"]], key=lambda v: (v.get("menu_order", 0), v["id"]))

    changes = {"product_title": None, "variant_price": None,
               "variant_stock": None, "variant_added": None,
               "page_body_image": None}

    # 1. one title change
    product["name"] = product["name"] + DELTA_MARK
    changes["product_title"] = {"woo_id": product["id"], "slug": product["slug"]}

    # 2. one price change
    priced = rows[0]
    old_price = float(priced.get("regular_price") or priced.get("price") or "10")
    priced["regular_price"] = f"{old_price + 5:.2f}"
    priced["price"] = priced["regular_price"]
    changes["variant_price"] = {"woo_id": priced["id"],
                                "from": f"{old_price:.2f}", "to": priced["regular_price"]}

    # 3. one stock quantity change
    stocked = rows[1] if len(rows) > 1 else rows[0]
    old_stock = stocked.get("stock_quantity") or 0
    stocked["manage_stock"] = True
    stocked["stock_quantity"] = old_stock + 7
    changes["variant_stock"] = {"woo_id": stocked["id"],
                                "from": old_stock, "to": stocked["stock_quantity"]}

    # 4. one added variation, carrying a brand-new option value
    template = rows[0]
    new_id = max(v["id"] for v in variations) + 1
    new_variation = dict(template)
    new_variation["id"] = new_id
    new_variation["sku"] = ""
    new_variation["menu_order"] = max(v.get("menu_order", 0) for v in rows) + 1
    new_variation["attributes"] = [dict(a) for a in template.get("attributes") or []]
    if new_variation["attributes"]:
        new_variation["attributes"][0]["option"] = "Delta"
    variations.append(new_variation)
    changes["variant_added"] = {"woo_id": new_id, "parent_id": product["id"]}

    # 5. one page body gains a WordPress image reference (CLNT-323). The body
    #    rewrite happens at load time, so this proves the ledger notices a
    #    rewritten body: a new File is uploaded and exactly one Page updates.
    changes["page_body_image"] = _add_page_body_image(delta_dir)

    write_json(delta_dir / "products.json", products)
    write_json(delta_dir / "variations.json", variations)
    return {"delta_dir": rel(delta_dir), "changes": changes}


def _content(page) -> str:
    content = page.get("content")
    if isinstance(content, dict):
        return content.get("rendered") or content.get("raw") or ""
    return content or ""


def _set_content(page, value) -> None:
    if isinstance(page.get("content"), dict):
        page["content"]["rendered"] = value
    else:
        page["content"] = value


def _add_page_body_image(delta_dir: Path):
    """Add one body image to the lowest-id migratable page.

    The image is a media file no page or post body already references, so the
    delta creates exactly one File and updates exactly one Page.
    """
    pages_path, media_path = delta_dir / "pages.json", delta_dir / "media.json"
    if not (pages_path.exists() and media_path.exists()):
        return None
    pages = read_json(pages_path)
    posts = read_json(delta_dir / "posts.json") if (delta_dir / "posts.json").exists() else []
    media = read_json(media_path)

    candidates = [
        p for p in sorted(pages, key=lambda p: p["id"])
        if p.get("status") == "publish"
        and not FUNCTIONAL_PAGE.match(str(p.get("slug") or ""))
    ]
    if not candidates:
        return None
    page = candidates[0]

    bodies = "".join(_content(row) for row in pages + posts)
    url = next(
        (m["source_url"] for m in sorted(media, key=lambda m: m.get("id") or 0)
         if m.get("source_url") and m["source_url"] not in bodies),
        None,
    )
    if not url:
        return None
    _set_content(page, _content(page)
                 + f'<p><img src="{url}" alt="Delta body image" /></p>')
    write_json(pages_path, pages)
    return {"woo_id": page["id"], "slug": page.get("slug"),
            "filename": url.rsplit("/", 1)[-1]}


def _pick_product(products, by_parent):
    """Lowest-id variable product whose attributes are all plain option axes."""
    candidates = []
    for product in products:
        if product.get("status") != "publish" or product.get("type") != "variable":
            continue
        rows = by_parent.get(product["id"]) or []
        if len(rows) < 3:
            continue
        attributes = [a for a in product.get("attributes") or [] if a.get("variation")]
        policies = {
            ATTRIBUTE_POLICY.get(str(a.get("name")).lower(), ("decision", None))[0]
            for a in attributes
        }
        if policies != {"option"}:
            continue
        if any(not (v.get("regular_price") or v.get("price")) for v in rows):
            continue
        candidates.append(product)
    if not candidates:
        raise RuntimeError("no suitable product found to build a delta from")
    return min(candidates, key=lambda p: p["id"])
