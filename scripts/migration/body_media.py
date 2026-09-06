#!/usr/bin/env python3
"""WordPress body-image extraction and rewriting (CLNT-323).

Migrated Shopify page and article bodies still carried
``<img src="https://prosporter.com.au/wp-content/uploads/...">``. At cutover DNS
moves prosporter.com.au to Vercel and every one of those images 404s, so the
files have to live on Shopify's CDN and the body HTML has to point at them.

This module is pure string work and has no Shopify or network dependency:

* :func:`origins` - the WordPress hosts to treat as "the old site".
* :func:`scan` - every WordPress upload URL inside a body, including ``srcset``
  candidates and ``<a href>`` links to uploads.
* :func:`resolve` - collapse a ``-WIDTHxHEIGHT`` resized variant onto the
  original file when the original exists in the media export.
* :func:`rewrite` - swap the URLs for their Shopify CDN equivalents.

The transform stage uses ``scan``/``resolve`` to emit one ``body_media`` record
per unique original; the load stage uploads each once and uses ``rewrite`` on
the page/article payload immediately before the create-or-update, so the ledger
checksum is taken over the rewritten body and a rerun is a no-op.
"""
from __future__ import annotations

import re
import urllib.parse

# WordPress puts every uploaded file under this path.
UPLOADS_PATH = "/wp-content/uploads/"

# "name-1024x684.jpg" -> "name.jpg". WordPress generates these thumbnails from
# one original; Shopify only needs the original.
RESIZED_RE = re.compile(r"^(?P<stem>.+?)-\d{2,5}x\d{2,5}(?P<ext>\.[A-Za-z0-9]{1,5})$")

IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
A_TAG_RE = re.compile(r"<a\b[^>]*>", re.IGNORECASE)

# Single-URL attributes and comma-separated candidate lists. The data-* forms
# are what the lazy-loading plugins on the source site emit.
URL_ATTRS = ("src", "data-src", "data-lazy-src", "data-orig-src", "data-large_image")
SRCSET_ATTRS = ("srcset", "data-srcset", "data-lazy-srcset")
DESCRIPTOR_ATTRS = ("sizes", "data-sizes")


def _attr_re(name: str) -> re.Pattern:
    return re.compile(
        r"(?P<pre>\b" + re.escape(name) + r"\s*=\s*(?P<q>[\"']))(?P<val>[^\"']*)(?P=q)",
        re.IGNORECASE,
    )


_ATTR_CACHE: dict[str, re.Pattern] = {}


def attr_re(name: str) -> re.Pattern:
    if name not in _ATTR_CACHE:
        _ATTR_CACHE[name] = _attr_re(name)
    return _ATTR_CACHE[name]


# --------------------------------------------------------------------------
# Origins
# --------------------------------------------------------------------------
def _host(value: str) -> str:
    """Bare lower-case host with any leading www. removed."""
    value = (value or "").strip()
    if not value:
        return ""
    if "//" not in value:
        value = "//" + value
    host = urllib.parse.urlsplit(value).hostname or ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


#: Public alias - the loader and reconcile need bare hosts too.
host_of = _host


def primary_origin(data: dict) -> str:
    """The host to absolutise root-relative URLs against."""
    base = _host((data.get("_meta") or {}).get("source_base") or "")
    if base:
        return base
    hosts = origins(data)
    return sorted(hosts)[0] if hosts else ""


def origins(data: dict) -> frozenset[str]:
    """The WordPress hosts for this snapshot.

    Derived, never hard-coded: the export manifest's ``base`` plus every host
    that appears in ``media.json``. ``www.`` is normalised away, so
    ``prosporter.com.au`` and ``www.prosporter.com.au`` are one origin.
    """
    hosts = set()
    base = (data.get("_meta") or {}).get("source_base")
    if base and base != "unknown":
        hosts.add(_host(base))
    for row in data.get("media") or []:
        hosts.add(_host(row.get("source_url") or ""))
        guid = row.get("guid")
        if isinstance(guid, dict):
            hosts.add(_host(guid.get("rendered") or guid.get("raw") or ""))
    hosts.discard("")
    return frozenset(hosts)


# --------------------------------------------------------------------------
# URL identity
# --------------------------------------------------------------------------
def absolutise(url: str, origin: str) -> str:
    """Protocol-relative and root-relative URLs -> absolute https URLs."""
    url = (url or "").strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return f"https://{origin}{url}" if origin else url
    return url


def canon(url: str) -> tuple[str, str]:
    """(host without www, decoded path) - the identity two spellings share."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host, urllib.parse.unquote(parts.path)


def is_upload(url: str, hosts) -> bool:
    if not url:
        return False
    host, path = canon(url)
    return bool(host) and host in hosts and UPLOADS_PATH in path


def filename(url: str) -> str:
    path = urllib.parse.urlsplit(url).path
    return urllib.parse.unquote(path.rsplit("/", 1)[-1]) or "file"


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "heic", "avif", "bmp", "svg"}


def content_type(url: str, mime: str = "") -> str:
    """Shopify FileContentType for a WordPress upload.

    Only images become IMAGE (and so get a CDN image URL); size-guide PDFs and
    anything else are generic FILEs.
    """
    if (mime or "").lower().startswith("image/"):
        return "IMAGE"
    if mime:
        return "FILE"
    ext = filename(url).rsplit(".", 1)[-1].lower()
    return "IMAGE" if ext in IMAGE_EXTENSIONS else "FILE"


def original_of(url: str) -> str | None:
    """The un-resized sibling of a ``-1024x684.jpg`` URL, or None."""
    parts = urllib.parse.urlsplit(url)
    name = parts.path.rsplit("/", 1)[-1]
    match = RESIZED_RE.match(name)
    if not match:
        return None
    stem = parts.path[: len(parts.path) - len(name)] + match.group("stem") + match.group("ext")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, stem, parts.query, parts.fragment))


def known_index(media_rows) -> dict[tuple[str, str], str]:
    """canon key -> the media export's own source_url for that file."""
    index = {}
    for row in media_rows or []:
        url = row.get("source_url")
        if url:
            index.setdefault(canon(url), url)
    return index


def resolve(url: str, known: dict) -> tuple[str, bool]:
    """(canonical source URL, resolved-against-media.json?).

    A resized variant collapses onto the original **only** when the original is
    in the media export; otherwise the URL is kept exactly as written so the
    unresolved reference is visible rather than silently pointed at a file that
    may not exist.
    """
    direct = known.get(canon(url))
    if direct:
        return direct, True
    original = original_of(url)
    if original:
        hit = known.get(canon(original))
        if hit:
            return hit, True
    return url, False


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------
def _srcset_candidates(value: str):
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split()
        yield bits[0], " ".join(bits[1:])


def scan(body_html: str, hosts, origin: str = "") -> list[dict]:
    """Every WordPress upload reference in the body, in document order.

    Each entry is ``{"url", "attr", "tag"}``. ``srcset`` candidates count
    individually - they are separate references that would each 404.
    """
    found: list[dict] = []
    if not body_html:
        return found
    default_origin = origin or (sorted(hosts)[0] if hosts else "")

    def take(raw, attr, tag):
        url = absolutise(raw, default_origin)
        if is_upload(url, hosts):
            found.append({"url": url, "attr": attr, "tag": tag})

    for tag in IMG_TAG_RE.findall(body_html):
        for attr in URL_ATTRS:
            match = attr_re(attr).search(tag)
            if match:
                take(match.group("val"), attr, "img")
        for attr in SRCSET_ATTRS:
            match = attr_re(attr).search(tag)
            if not match:
                continue
            for candidate, _descriptor in _srcset_candidates(match.group("val")):
                take(candidate, attr, "img")
    for tag in A_TAG_RE.findall(body_html):
        match = attr_re("href").search(tag)
        if match:
            take(match.group("val"), "href", "a")
    return found


# --------------------------------------------------------------------------
# Rewriting
# --------------------------------------------------------------------------
def rewrite(body_html: str, url_map: dict, hosts, origin: str = "") -> tuple[str, dict]:
    """Point every mapped WordPress upload at its Shopify CDN URL.

    ``url_map`` is keyed by :func:`canon` so every spelling of a file (http vs
    https, www vs bare, percent-encoded, and every ``-WIDTHxHEIGHT`` variant the
    transform collapsed) resolves to the same uploaded file.

    A rewritten ``<img>`` loses its ``srcset``/``sizes`` when every candidate
    collapsed onto the same CDN file: Shopify serves one original and a srcset
    listing the same URL at several widths would be a lie.

    Returns the new HTML and ``{references, rewritten, unrewritten}``.
    """
    stats = {"references": 0, "rewritten": 0, "unrewritten": 0}
    if not body_html:
        return body_html, stats
    default_origin = origin or (sorted(hosts)[0] if hosts else "")

    def target(raw):
        """CDN URL for a raw attribute value, or None if it is not ours."""
        url = absolutise(raw, default_origin)
        if not is_upload(url, hosts):
            return None
        stats["references"] += 1
        replacement = url_map.get(canon(url))
        if replacement is None:
            original = original_of(url)
            if original:
                replacement = url_map.get(canon(original))
        if replacement is None:
            stats["unrewritten"] += 1
            return None
        stats["rewritten"] += 1
        return replacement

    def sub_single(tag, attr):
        pattern = attr_re(attr)
        match = pattern.search(tag)
        if not match:
            return tag, None
        replacement = target(match.group("val"))
        if replacement is None:
            return tag, None
        return (
            tag[: match.start()] + match.group("pre") + replacement + match.group("q") + tag[match.end():],
            replacement,
        )

    def sub_srcset(tag, attr):
        pattern = attr_re(attr)
        match = pattern.search(tag)
        if not match:
            return tag, set()
        seen, parts = {}, []
        for candidate, descriptor in _srcset_candidates(match.group("val")):
            replacement = target(candidate)
            url = replacement if replacement is not None else candidate
            if url in seen:
                continue
            seen[url] = descriptor
            parts.append(f"{url} {descriptor}".strip())
        new_value = ", ".join(parts)
        return (
            tag[: match.start()] + match.group("pre") + new_value + match.group("q") + tag[match.end():],
            set(seen),
        )

    def drop_attr(tag, attr):
        return attr_re(attr).sub("", tag, count=1)

    def fix_img(match):
        tag = match.group(0)
        src = None
        for attr in URL_ATTRS:
            tag, replacement = sub_single(tag, attr)
            if attr == "src" and replacement:
                src = replacement
        for attr in SRCSET_ATTRS:
            tag, urls = sub_srcset(tag, attr)
            # One candidate left and it is exactly the src: the srcset says
            # nothing, and its width descriptor no longer matches the file.
            if urls and urls == {src}:
                tag = drop_attr(tag, attr)
                for extra in DESCRIPTOR_ATTRS:
                    tag = drop_attr(tag, extra)
        return re.sub(r"\s{2,}", " ", tag)

    def fix_a(match):
        tag, _ = sub_single(match.group(0), "href")
        return tag

    out = IMG_TAG_RE.sub(fix_img, body_html)
    out = A_TAG_RE.sub(fix_a, out)
    return out, stats


def residual(body_html: str, hosts, origin: str = "") -> int:
    """How many WordPress upload references a (rewritten) body still carries."""
    return len(scan(body_html, hosts, origin))
