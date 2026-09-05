#!/usr/bin/env python3
"""End-to-end Storefront API check for a migrated product.

Reads the product through the *public* Storefront API token (the same token the
Next.js storefront uses), so it proves what a shopper-facing request would see:
publication to the Headless channel, ACTIVE status, variants, images, the
``prosporter.*`` metafields, and that a cart with one of its variants gets a
checkout URL.

    python3 scripts/migration/storefront_check.py nago

Exit code 1 when the product is not visible or any check fails.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from shopify_admin import load_env, store_domain
from common import SHOPIFY_API_VERSION

PRODUCT_QUERY = """
query($handle: String!) {
  product(handle: $handle) {
    id handle title availableForSale
    options { name optionValues { name } }
    images(first: 20) { nodes { url altText } }
    variants(first: 250) {
      nodes { id sku title availableForSale quantityAvailable price { amount currencyCode } image { url } }
    }
    metafields(identifiers: [
      {namespace: "prosporter", key: "surface"}, {namespace: "prosporter", key: "club"},
      {namespace: "prosporter", key: "gender"}, {namespace: "prosporter", key: "size_guide"},
      {namespace: "prosporter", key: "personalisation"}
    ]) { key value type }
    collections(first: 10) { nodes { handle } }
    seo { title description }
  }
}
"""

CART_MUTATION = """
mutation($lines: [CartLineInput!]!) {
  cartCreate(input: {lines: $lines, buyerIdentity: {countryCode: AU}}) {
    cart { id checkoutUrl totalQuantity cost { totalAmount { amount currencyCode } } }
    userErrors { field message }
  }
}
"""


def storefront(env, query, variables):
    domain = store_domain(env)
    token = env.get("SHOPIFY_STOREFRONT_TOKEN", "").strip()
    if not token:
        raise SystemExit("SHOPIFY_STOREFRONT_TOKEN missing from .env.local")
    version = env.get("SHOPIFY_STOREFRONT_API_VERSION", "").strip() or SHOPIFY_API_VERSION
    request = urllib.request.Request(
        f"https://{domain}/api/{version}/graphql.json",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Content-Type": "application/json", "X-Shopify-Storefront-Access-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Storefront API HTTP {exc.code}: {exc.read().decode()[:300]}")
    if payload.get("errors"):
        raise SystemExit(f"Storefront API errors: {payload['errors']}")
    return payload["data"]


def main(argv):
    handle = argv[1] if len(argv) > 1 else "nago"
    env = load_env()
    product = storefront(env, PRODUCT_QUERY, {"handle": handle}).get("product")
    checks = []
    if not product:
        print(json.dumps({"handle": handle, "visible": False,
                          "hint": "product is DRAFT or not published to the Headless publication"}, indent=2))
        return 1
    variants = product["variants"]["nodes"]
    metafields = [m for m in product["metafields"] if m]
    checks.append(("visible through Storefront API", True))
    checks.append(("has variants", bool(variants)))
    checks.append(("has images", bool(product["images"]["nodes"])))
    checks.append(("prosporter metafields readable", bool(metafields)))
    checks.append(("in a collection", bool(product["collections"]["nodes"])))
    purchasable = [v for v in variants if v["availableForSale"]] or variants
    cart = None
    if purchasable:
        result = storefront(env, CART_MUTATION,
                            {"lines": [{"merchandiseId": purchasable[0]["id"], "quantity": 1}]})["cartCreate"]
        cart = result.get("cart")
        checks.append(("cartCreate returned checkoutUrl",
                       bool(cart and cart.get("checkoutUrl")) and not result.get("userErrors")))
    summary = {
        "handle": handle,
        "title": product["title"],
        "availableForSale": product["availableForSale"],
        "options": [(o["name"], [v["name"] for v in o["optionValues"]]) for o in product["options"]],
        "variants": [{"sku": v["sku"], "title": v["title"], "price": v["price"]["amount"],
                      "available": v["availableForSale"], "qty": v["quantityAvailable"],
                      "image": bool(v["image"])} for v in variants],
        "images": len(product["images"]["nodes"]),
        "metafields": {m["key"]: m["value"] for m in metafields},
        "collections": [c["handle"] for c in product["collections"]["nodes"]],
        "seo": product["seo"],
        "cart": {"total": cart["cost"]["totalAmount"], "checkoutUrl_host": cart["checkoutUrl"].split("/")[2]} if cart else None,
        "checks": {name: ok for name, ok in checks},
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
