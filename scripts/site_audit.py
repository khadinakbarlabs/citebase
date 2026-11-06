#!/usr/bin/env python3
"""Deterministic site crawler + technical/on-page SEO auditor.

Standard library only. Crawls one host politely (robots.txt aware), records
per-page SEO facts and site-level signals, then scores checks as
pass / warn / fail so the agent reports evidence instead of guesses.

Usage:
  python3 site_audit.py https://example.com --max-pages 50 --out audit.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter, defaultdict, deque
from html.parser import HTMLParser

UA = "Mozilla/5.0 (compatible; AISEOAgentAudit/1.0)"
TIMEOUT_S = 15
MAX_BYTES = 3_000_000
AI_CRAWLERS = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
    "PerplexityBot", "Google-Extended", "Googlebot", "Bingbot", "CCBot", "Applebot-Extended",
]
TITLE_RANGE = (30, 60)
DESC_RANGE = (70, 160)
THIN_WORDS = 300
LONG_CONTENT_WORDS = 600
SLOW_MS = 1500
HEAVY_HTML_KB = 500
MAX_DEPTH_OK = 3
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|avif|svg|zip|mp4|mp3|css|js|xml|json|ico)$", re.I)


class PageParser(HTMLParser):
    """Collects the SEO-relevant parts of one HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.meta: dict[str, str] = {}
        self.links: list[dict] = []
        self.canonical = ""
        self.hreflang: list[str] = []
        self.headings: dict[str, list[str]] = defaultdict(list)
        self._heading: str | None = None
        self._heading_buf: list[str] = []
        self.images: list[dict] = []
        self.jsonld: list[str] = []
        self._in_jsonld = False
        self._jsonld_buf: list[str] = []
        self._skip = 0
        self.text: list[str] = []
        self.lang = ""
        self._a_href: str | None = None
        self._a_rel = ""
        self._a_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if "canonical" in rel:
                self.canonical = a.get("href", "")
            if "alternate" in rel and a.get("hreflang"):
                self.hreflang.append(a.get("hreflang"))
        elif tag == "a":
            self._a_href = a.get("href")
            self._a_rel = a.get("rel", "").lower()
            self._a_text = []
        elif tag in ("h1", "h2", "h3"):
            self._heading, self._heading_buf = tag, []
        elif tag == "img":
            self.images.append({"src": a.get("src", ""), "alt": attrs_get(attrs, "alt")})
        elif tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_jsonld, self._jsonld_buf = True, []
        elif tag in ("script", "style", "noscript", "svg"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._a_href is not None:
            self.links.append({"href": self._a_href, "rel": self._a_rel,
                               "text": " ".join(self._a_text).strip()[:120]})
            self._a_href = None
        elif tag == self._heading:
            self.headings[tag].append(" ".join(self._heading_buf).strip()[:200])
            self._heading = None
        elif tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._jsonld_buf))
            self._in_jsonld = False
        elif tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self._skip:
            return
        if self._heading:
            self._heading_buf.append(data)
        if self._a_href is not None:
            self._a_text.append(data)
        self.text.append(data)


def attrs_get(attrs, name):
    """Returns the raw attribute value, or None when the attribute is absent."""
    for k, v in attrs:
        if k.lower() == name:
            return v or ""
    return None


def _ssl_context() -> ssl.SSLContext:
    """Uses certifi or the system bundle when Python ships without CA certs (python.org macOS builds)."""
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for path in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/opt/homebrew/etc/ca-certificates/cert.pem"):
        if os.path.exists(path):
            return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_ssl_context()))


def fetch(url: str) -> dict:
    """Fetches one URL without following redirects so chains stay visible."""
    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        resp = _OPENER.open(req, timeout=TIMEOUT_S)
        status, hdrs, body = resp.status, dict(resp.headers), resp.read(MAX_BYTES)
    except urllib.error.HTTPError as err:
        status, hdrs = err.code, dict(err.headers or {})
        body = err.read(MAX_BYTES) if err.fp else b""
    except Exception as err:  # network failures are reported as data, not raised
        return {"url": url, "status": 0, "error": str(err)[:200], "headers": {}, "body": b"",
                "ms": int((time.time() - start) * 1000)}
    headers = {k.lower(): v for k, v in hdrs.items()}
    if headers.get("content-encoding", "").lower() == "gzip":
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    return {"url": url, "status": status, "headers": headers, "body": body,
            "ms": int((time.time() - start) * 1000)}


def follow(url: str, limit: int = 6) -> tuple[dict, list[str]]:
    chain = [url]
    res = fetch(url)
    while res.get("status") in (301, 302, 303, 307, 308) and len(chain) <= limit:
        nxt = urllib.parse.urljoin(chain[-1], res["headers"].get("location", ""))
        if nxt in chain:
            break
        chain.append(nxt)
        res = fetch(nxt)
    return res, chain


def norm(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))


def decode(body: bytes, headers: dict) -> str:
    m = re.search(r"charset=([\w-]+)", headers.get("content-type", ""))
    try:
        return body.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def schema_types(blocks: list[str]) -> tuple[list[str], int]:
    types: list[str] = []
    invalid = 0

    def walk(o):
        if isinstance(o, dict):
            t = o.get("@type")
            if t:
                types.extend(t if isinstance(t, list) else [t])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for raw in blocks:
        try:
            walk(json.loads(raw))
        except ValueError:
            invalid += 1
    return sorted(set(map(str, types))), invalid


def analyse_page(url: str, res: dict, chain: list[str], host: str) -> dict:
    page = {"url": url, "final_url": chain[-1], "status": res.get("status"), "ms": res.get("ms"),
            "redirects": len(chain) - 1, "error": res.get("error")}
    if res.get("status") != 200 or "html" not in res["headers"].get("content-type", ""):
        return page
    html = decode(res["body"], res["headers"])
    p = PageParser()
    try:
        p.feed(html)
    except Exception as err:
        page["error"] = f"parse: {err}"[:200]
        return page
    internal, external, nofollow = set(), set(), 0
    for link in p.links:
        href = (link["href"] or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absu = urllib.parse.urldefrag(urllib.parse.urljoin(chain[-1], href))[0]
        if "nofollow" in link["rel"]:
            nofollow += 1
        (internal if urllib.parse.urlsplit(absu).netloc.lower() == host else external).add(absu)
    types, bad_schema = schema_types(p.jsonld)
    robots_meta = (p.meta.get("robots", "") + " " + res["headers"].get("x-robots-tag", "")).lower().strip()
    page.update({
        "title": re.sub(r"\s+", " ", p.title).strip(),
        "meta_description": p.meta.get("description", "").strip(),
        "h1": p.headings.get("h1", []),
        "h2": p.headings.get("h2", [])[:15],
        "canonical": urllib.parse.urljoin(chain[-1], p.canonical) if p.canonical else "",
        "robots": robots_meta,
        "noindex": "noindex" in robots_meta,
        "lang": p.lang,
        "hreflang": p.hreflang,
        "og_title": p.meta.get("og:title", ""),
        "og_image": p.meta.get("og:image", ""),
        "viewport": bool(p.meta.get("viewport")),
        "word_count": len(re.findall(r"\b\w+\b", " ".join(p.text))),
        "images": len(p.images),
        "images_missing_alt": sum(1 for i in p.images if i["alt"] is None or not i["alt"].strip()),
        "internal_links": sorted(internal),
        "external_links": len(external),
        "nofollow_links": nofollow,
        "schema_types": types,
        "schema_invalid_blocks": bad_schema,
        "html_kb": round(len(res["body"]) / 1024, 1),
        "has_date": bool(re.search(r"(datePublished|dateModified|<time\b|article:modified_time)", html)),
        "has_author": bool(re.search(r'("author"|rel="author"|class="[^"]*author)', html, re.I)),
    })
    return page


def site_signals(origin: str) -> tuple[dict, urllib.robotparser.RobotFileParser]:
    sig: dict = {}
    robots = fetch(urllib.parse.urljoin(origin, "/robots.txt"))
    txt = decode(robots["body"], robots["headers"]) if robots.get("status") == 200 else ""
    sig["robots_txt"] = {"status": robots.get("status"), "bytes": len(txt)}
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(txt.splitlines())
    if robots.get("status") == 0:
        sig["ai_crawler_access"] = {bot: None for bot in AI_CRAWLERS}  # unknown: robots.txt unreachable
    else:
        sig["ai_crawler_access"] = {bot: rp.can_fetch(bot, origin + "/") for bot in AI_CRAWLERS}
    sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", txt) or [urllib.parse.urljoin(origin, "/sitemap.xml")]
    sig["sitemaps"] = []
    for sm in sitemaps[:5]:
        sm = urllib.parse.urljoin(origin + "/", sm)  # robots.txt may use relative paths
        r, sm_chain = follow(sm)
        body = decode(r["body"], r["headers"]) if r.get("status") == 200 else ""
        sig["sitemaps"].append({"url": sm, "final_url": sm_chain[-1], "status": r.get("status"),
                                "urls": body.count("<loc>")})
    llms = fetch(urllib.parse.urljoin(origin, "/llms.txt"))
    sig["llms_txt"] = llms.get("status") == 200 and "html" not in llms["headers"].get("content-type", "")
    host = urllib.parse.urlsplit(origin).netloc
    _, http_chain = follow(f"http://{host}/")
    sig["http_redirect_chain"] = http_chain
    sig["http_to_https"] = len(http_chain) > 1 and http_chain[-1].startswith("https://")
    alt_host = host[4:] if host.startswith("www.") else "www." + host
    alt_res, alt_chain = follow(f"https://{alt_host}/")
    if alt_res.get("status") == 0 and len(alt_chain) == 1:
        sig["www_consolidated"] = None  # alternate host does not resolve: fine
    else:
        sig["www_consolidated"] = urllib.parse.urlsplit(alt_chain[-1]).netloc == host
    not_found = fetch(urllib.parse.urljoin(origin, "/this-page-should-404-ai-seo-audit"))
    sig["soft_404"] = not_found.get("status") == 200
    return sig, rp


def crawl(start: str, max_pages: int, delay: float) -> dict:
    first, chain = follow(start)
    if first.get("status") == 0:
        raise SystemExit(f"Cannot reach {start}: {first.get('error')}")
    parts = urllib.parse.urlsplit(chain[-1])
    origin, host = f"{parts.scheme}://{parts.netloc}", parts.netloc.lower()
    signals, rp = site_signals(origin)
    seen: set[str] = set()
    pages: list[dict] = []
    inlinks: Counter = Counter()
    queue = deque([(norm(chain[-1]), 0)])
    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        if not rp.can_fetch("*", url):
            pages.append({"url": url, "status": "blocked_by_robots", "depth": depth})
            continue
        res, ch = follow(url)
        page = analyse_page(url, res, ch, host)
        page["depth"] = depth
        pages.append(page)
        for link in page.get("internal_links", []):
            n = norm(link)
            inlinks[n] += 1
            if n not in seen and not SKIP_EXT.search(urllib.parse.urlsplit(n).path):
                queue.append((n, depth + 1))
        time.sleep(delay)
    for p in pages:
        p["inlinks"] = inlinks.get(norm(p["url"]), 0)
        p["internal_link_count"] = len(p.pop("internal_links", []))
    return {"start": start, "origin": origin, "crawled": len(pages), "signals": signals, "pages": pages}


def check(level: str, area: str, name: str, detail: str, urls: list[str] | None = None) -> dict:
    return {"level": level, "area": area, "check": name, "detail": detail, "urls": (urls or [])[:15]}


def technical_checks(audit: dict, pages: list[dict]) -> list[dict]:
    s, out = audit["signals"], []
    if None in s["ai_crawler_access"].values():
        out.append(check("fail", "technical", "robots.txt reachable", "Could not fetch robots.txt (network/TLS error)"))
    blocked = [b for b, ok in s["ai_crawler_access"].items() if ok is False]
    level = "fail" if {"Googlebot", "Bingbot"} & set(blocked) else ("warn" if blocked else "pass")
    out.append(check(level, "technical", "Search + AI crawler access (robots.txt)",
                     "Blocked: " + (", ".join(blocked) or "none")))
    out.append(check("pass" if s["http_to_https"] else "fail", "technical", "HTTP redirects to HTTPS",
                     " -> ".join(s["http_redirect_chain"])))
    if s["www_consolidated"] is False:
        out.append(check("warn", "technical", "www / non-www consolidation",
                         "Alternate host serves content without redirecting to the canonical host"))
    good_sm = [x for x in s["sitemaps"] if x["status"] == 200 and x["urls"]]
    out.append(check("pass" if good_sm else "fail", "technical", "XML sitemap reachable",
                     "; ".join(f"{x['url']} -> {x.get('final_url')} ({x['status']}, {x['urls']} urls)"
                               for x in s["sitemaps"])))
    if s["soft_404"]:
        out.append(check("fail", "technical", "Soft 404", "A non-existent URL returns HTTP 200"))
    errors = [p["url"] for p in audit["pages"] if isinstance(p.get("status"), int) and p["status"] >= 400]
    out.append(check("fail" if errors else "pass", "technical", "Broken internal pages (4xx/5xx)",
                     f"{len(errors)} found", errors))
    unreachable = [p["url"] for p in audit["pages"] if p.get("status") == 0]
    if unreachable:
        out.append(check("fail", "technical", "Unreachable pages (network error)", f"{len(unreachable)}", unreachable))
    chains = [p["url"] for p in audit["pages"] if p.get("redirects", 0) > 1]
    if chains:
        out.append(check("warn", "technical", "Redirect chains (>1 hop)", f"{len(chains)} pages", chains))
    slow = [p["url"] for p in pages if (p.get("ms") or 0) > SLOW_MS]
    out.append(check("warn" if slow else "pass", "technical", f"Server response under {SLOW_MS} ms",
                     f"{len(slow)} slow pages", slow))
    heavy = [p["url"] for p in pages if p.get("html_kb", 0) > HEAVY_HTML_KB]
    if heavy:
        out.append(check("warn", "technical", f"HTML under {HEAVY_HTML_KB} KB", f"{len(heavy)} heavy pages", heavy))
    noindex = [p["url"] for p in pages if p.get("noindex")]
    if noindex:
        out.append(check("warn", "technical", "noindex pages (confirm intentional)", f"{len(noindex)}", noindex))
    no_canon = [p["url"] for p in pages if not p.get("canonical")]
    out.append(check("warn" if no_canon else "pass", "technical", "Canonical tag present",
                     f"{len(no_canon)} missing", no_canon))
    canon_off = [p["url"] for p in pages if p.get("canonical") and norm(p["canonical"]) != norm(p["final_url"])]
    if canon_off:
        out.append(check("warn", "technical", "Canonical points to another URL",
                         f"{len(canon_off)} pages (confirm duplicates are intended)", canon_off))
    no_vp = [p["url"] for p in pages if not p.get("viewport")]
    if no_vp:
        out.append(check("fail", "technical", "Mobile viewport meta", f"{len(no_vp)} missing", no_vp))
    no_lang = [p["url"] for p in pages if not p.get("lang")]
    if no_lang:
        out.append(check("warn", "technical", "<html lang> attribute", f"{len(no_lang)} missing", no_lang))
    return out


def rendering_checks(pages: list[dict]) -> list[dict]:
    """Flags pages whose server HTML is nearly empty: content likely needs JavaScript to render."""
    js_only = [p["url"] for p in pages if p["word_count"] < 150 and p.get("internal_link_count", 0) < 3]
    if not js_only:
        return [check("pass", "technical", "Content present in server HTML (no JS needed)", "OK")]
    homepage_hit = any(p.get("depth", 1) == 0 for p in pages if p["url"] in js_only)
    level = "fail" if homepage_hit or len(js_only) > len(pages) / 2 else "warn"
    return [check(level, "technical", "Content present in server HTML (no JS needed)",
                  f"{len(js_only)} pages serve almost no text/links without JavaScript. AI crawlers (GPTBot, "
                  "ClaudeBot, PerplexityBot) do not run JS and Google renders it late: use SSR/SSG or prerendering.",
                  js_only)]


def onpage_checks(pages: list[dict]) -> list[dict]:
    out = []
    titles = Counter(p["title"] for p in pages if p["title"])
    missing_t = [p["url"] for p in pages if not p["title"]]
    bad_t = [p["url"] for p in pages if p["title"] and not TITLE_RANGE[0] <= len(p["title"]) <= TITLE_RANGE[1]]
    dup_t = [p["url"] for p in pages if p["title"] and titles[p["title"]] > 1]
    out.append(check("fail" if missing_t else "pass", "on-page", "Title tag present", f"{len(missing_t)} missing", missing_t))
    out.append(check("warn" if bad_t else "pass", "on-page", f"Title length {TITLE_RANGE[0]}-{TITLE_RANGE[1]} chars",
                     f"{len(bad_t)} outside range", bad_t))
    out.append(check("warn" if dup_t else "pass", "on-page", "Unique title tags", f"{len(dup_t)} duplicated", dup_t))
    descs = Counter(p["meta_description"] for p in pages if p["meta_description"])
    missing_d = [p["url"] for p in pages if not p["meta_description"]]
    bad_d = [p["url"] for p in pages
             if p["meta_description"] and not DESC_RANGE[0] <= len(p["meta_description"]) <= DESC_RANGE[1]]
    dup_d = [p["url"] for p in pages if p["meta_description"] and descs[p["meta_description"]] > 1]
    out.append(check("warn" if missing_d else "pass", "on-page", "Meta description present",
                     f"{len(missing_d)} missing", missing_d))
    if bad_d:
        out.append(check("warn", "on-page", f"Meta description {DESC_RANGE[0]}-{DESC_RANGE[1]} chars",
                         f"{len(bad_d)} outside range", bad_d))
    if dup_d:
        out.append(check("warn", "on-page", "Unique meta descriptions", f"{len(dup_d)} duplicated", dup_d))
    no_h1 = [p["url"] for p in pages if not p["h1"]]
    multi_h1 = [p["url"] for p in pages if len(p["h1"]) > 1]
    out.append(check("fail" if no_h1 else ("warn" if multi_h1 else "pass"), "on-page", "Exactly one H1",
                     f"{len(no_h1)} missing, {len(multi_h1)} multiple", no_h1 + multi_h1))
    thin = [p["url"] for p in pages if p["word_count"] < THIN_WORDS and p.get("depth", 0) > 0]
    out.append(check("warn" if thin else "pass", "on-page", f"Thin content (under {THIN_WORDS} words)",
                     f"{len(thin)} pages", thin))
    alt = [p["url"] for p in pages if p.get("images_missing_alt")]
    out.append(check("warn" if alt else "pass", "on-page", "Image alt text",
                     f"{sum(p['images_missing_alt'] for p in pages)} images missing alt on {len(alt)} pages", alt))
    no_og = [p["url"] for p in pages if not (p.get("og_title") and p.get("og_image"))]
    if no_og:
        out.append(check("warn", "on-page", "Open Graph title + image", f"{len(no_og)} pages incomplete", no_og))
    weak = [p["url"] for p in pages if p.get("inlinks", 0) == 0 and p.get("depth", 0) > 0]
    if weak:
        out.append(check("warn", "on-page", "Weak internal linking (0 crawled inlinks)", f"{len(weak)} pages", weak))
    deep = [p["url"] for p in pages if p.get("depth", 0) > MAX_DEPTH_OK]
    if deep:
        out.append(check("warn", "on-page", f"Click depth over {MAX_DEPTH_OK}", f"{len(deep)} pages", deep))
    return out


def ai_search_checks(audit: dict, pages: list[dict]) -> list[dict]:
    out = []
    out.append(check("pass" if audit["signals"]["llms_txt"] else "warn", "ai-search", "llms.txt present",
                     "Optional. Google ignores it; some AI tools read it. Low priority."))
    no_schema = [p["url"] for p in pages if not p.get("schema_types")]
    out.append(check("warn" if no_schema else "pass", "ai-search", "JSON-LD structured data",
                     f"{len(no_schema)} pages without schema", no_schema))
    bad = [p["url"] for p in pages if p.get("schema_invalid_blocks")]
    if bad:
        out.append(check("fail", "ai-search", "Valid JSON-LD", f"{len(bad)} pages with unparsable JSON-LD", bad))
    types = {t for p in pages for t in p.get("schema_types", [])}
    entity = types & {"Organization", "LocalBusiness", "Corporation", "Person", "WebSite", "ProfessionalService"}
    out.append(check("pass" if entity else "warn", "ai-search", "Entity schema (Organization / Person / WebSite)",
                     "Found: " + (", ".join(sorted(entity)) or "none")))
    undated = [p["url"] for p in pages if not p.get("has_date") and p["word_count"] > LONG_CONTENT_WORDS]
    if undated:
        out.append(check("warn", "ai-search", "Published / updated date on long content", f"{len(undated)} pages", undated))
    no_author = [p["url"] for p in pages if not p.get("has_author") and p["word_count"] > LONG_CONTENT_WORDS]
    if no_author:
        out.append(check("warn", "ai-search", "Author byline (E-E-A-T) on long content", f"{len(no_author)} pages", no_author))
    return out


def score(audit: dict) -> list[dict]:
    pages = [p for p in audit["pages"] if "word_count" in p]
    checks = technical_checks(audit, pages)
    if pages:
        checks += rendering_checks(pages) + onpage_checks(pages) + ai_search_checks(audit, pages)
    order = {"fail": 0, "warn": 1, "pass": 2}
    return sorted(checks, key=lambda c: (order[c["level"]], c["area"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Crawl a site and score technical, on-page and AI-search checks.")
    ap.add_argument("url")
    ap.add_argument("--max-pages", type=int, default=50)
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between page requests")
    ap.add_argument("--out", default="", help="write the full JSON audit here")
    args = ap.parse_args()
    url = args.url if re.match(r"^https?://", args.url) else "https://" + args.url
    audit = crawl(url, max(1, min(args.max_pages, 500)), max(0.0, args.delay))
    audit["checks"] = score(audit)
    counts = Counter(c["level"] for c in audit["checks"])
    total = max(1, sum(counts.values()))
    audit["summary"] = {"fail": counts["fail"], "warn": counts["warn"], "pass": counts["pass"],
                        "health_score": round(100 * (counts["pass"] + 0.5 * counts["warn"]) / total)}
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(audit, fh, indent=2, default=str)
    print(json.dumps({"origin": audit["origin"], "crawled": audit["crawled"], "summary": audit["summary"],
                      "checks": [{k: c[k] for k in ("level", "area", "check", "detail")} for c in audit["checks"]]},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
