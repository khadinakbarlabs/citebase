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
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from collections import Counter, defaultdict, deque
from html.parser import HTMLParser

UA_TEMPLATE = "Mozilla/5.0 (compatible; CitebaseAudit/{version}; +https://github.com/khadinakbarlabs/citebase)"
FALLBACK_VERSION = "unknown"  # used when the plugin manifest is not next to this script (for example in the connector)
PLUGIN_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".claude-plugin", "plugin.json")
VERSION_TOKEN = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,31}")  # fullmatch only: safe inside a User-Agent header


def plugin_version(path: str = PLUGIN_JSON) -> str:
    """The plugin version from its manifest, or FALLBACK_VERSION when it is missing or not a plain token."""
    try:
        with open(path, encoding="utf-8") as fh:
            version = json.load(fh).get("version")
    except (OSError, ValueError, AttributeError):
        return FALLBACK_VERSION
    return version if isinstance(version, str) and VERSION_TOKEN.fullmatch(version) else FALLBACK_VERSION


UA = UA_TEMPLATE.format(version=plugin_version())
TIMEOUT_S = 15
MAX_BYTES = 3_000_000
ALLOW_PRIVATE = False  # set by --allow-private (local development and tests only)
NOT_FOUND_PROBE = "/citebase-audit-should-404"
TOTAL_TIMEOUT_S = 30.0  # wall-clock limit for one response, however slowly it trickles in
MAX_LINKS_PER_PAGE = 5000
MAX_QUEUE = 20000
# Bots that fetch pages to ANSWER people (search and assistants). Blocking these can hide a site from AI answers.
ANSWER_BOTS = ["Googlebot", "Bingbot", "OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "Perplexity-User", "Claude-SearchBot",
                "Claude-User"]
# Bots that collect training data only. Blocking these is a choice about training; it does not remove a site from answers.
TRAINING_BOTS = ["GPTBot", "ClaudeBot", "Google-Extended", "CCBot", "Applebot-Extended"]
AI_CRAWLERS = ANSWER_BOTS + TRAINING_BOTS
TITLE_RANGE = (15, 100)  # only flag titles that are clearly too short or absurdly long; longer is fine if it states the topic
MONEY_PAGE = re.compile(r"/(pricing|prices?|plans|vs|versus|alternatives?|compare|comparison|best)(\b|[-_/])", re.I)
MIN_PAGES_FOR_MONEY_CHECK = 10
MONEY_PAGE_MIN_INLINKS = 5
DESC_RANGE = (70, 160)
THIN_WORDS = 300
LONG_CONTENT_WORDS = 600
SLOW_MS = 1500
HEAVY_HTML_KB = 500
MAX_DEPTH_OK = 3
ROOT_IDS = {"root", "app", "__next", "__nuxt", "___gatsby"}
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|avif|svg|zip|mp4|mp3|css|js|xml|json|ico)$", re.I)


class PageParser(HTMLParser):
    """Collects the SEO-relevant parts of one HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.title_done = False
        self.scripts = 0
        self.root_depth = 0  # >0 while inside a #root/#app container (client-side app shell detection)
        self.root_found = False
        self.root_content = False
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
        if self.root_depth:
            if tag == "div":
                self.root_depth += 1
            if not self._skip and tag not in ("script", "style", "noscript"):
                self.root_content = True
        elif tag == "div" and not self.root_found and a.get("id", "").lower() in ROOT_IDS:
            self.root_depth, self.root_found = 1, True
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title" and not self._skip and not self.title_done:
            self._in_title = True  # first real <title> only; SVG <title> elements are skipped
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
            if len(self.images) < MAX_LINKS_PER_PAGE:
                self.images.append({"src": a.get("src", ""), "alt": attrs_get(attrs, "alt")})
        elif tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in_jsonld, self._jsonld_buf = True, []
        elif tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
            if tag == "script" and a.get("src"):
                self.scripts += 1

    @property
    def empty_shell(self) -> bool:
        return self.root_found and not self.root_content

    def handle_endtag(self, tag):
        if tag == "div" and self.root_depth:
            self.root_depth -= 1
        if tag == "title" and self._in_title:
            self._in_title, self.title_done = False, True
        elif tag == "a" and self._a_href is not None:
            if len(self.links) < MAX_LINKS_PER_PAGE:
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
        if self.root_depth and data.strip():
            self.root_content = True
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


def is_public_ip(ip: "ipaddress.IPv4Address | ipaddress.IPv6Address") -> bool:
    """Global unicast only. IPv6 forms that embed an IPv4 address (mapped, ::a.b.c.d, NAT64, 6to4) must embed a public one."""
    if ip.version == 6:
        packed = ip.packed
        embedded = ip.ipv4_mapped
        if embedded is None and packed[:12] == bytes(12):
            embedded = ipaddress.IPv4Address(packed[12:])
        elif embedded is None and packed[:12] == bytes.fromhex("0064ff9b0000000000000000"):
            embedded = ipaddress.IPv4Address(packed[12:])
        elif embedded is None and packed[:2] == b"\x20\x02":
            embedded = ipaddress.IPv4Address(packed[2:6])
        if embedded is not None and not is_public_ip(embedded):
            return False
    return ip.is_global and not ip.is_multicast


def host_is_public(host: str) -> bool:
    """False when the host is, or resolves to, a private, loopback, link-local or otherwise non-global address.

    Unresolvable names pass: the connection then fails with an ordinary network error."""
    host = host.strip("[]")
    try:
        return is_public_ip(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    return all(is_public_ip(ipaddress.ip_address(i[4][0].split("%")[0])) for i in infos)


def _check_peer(sock, host: str) -> None:
    """Re-checks the address actually connected to, which closes the DNS-rebinding gap after the name check."""
    if ALLOW_PRIVATE:
        return
    peer = sock.getpeername()[0].split("%")[0]
    if not is_public_ip(ipaddress.ip_address(peer)):
        sock.close()
        raise OSError(f"blocked: {host} connected to non-public address {peer}")


class _GuardedHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        super().connect()
        _check_peer(self.sock, self.host)


class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        http.client.HTTPConnection.connect(self)  # plain TCP first: verify the peer before any TLS bytes are sent
        _check_peer(self.sock, self.host)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_GuardedHTTPConnection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_GuardedHTTPSConnection, req, context=self._context)


def _build_opener() -> urllib.request.OpenerDirector:
    """http(s) only: no file://, ftp://, data: or environment proxies."""
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.UnknownHandler(), urllib.request.HTTPDefaultErrorHandler(), _NoRedirect(),
                    urllib.request.HTTPErrorProcessor(), _HTTPHandler(), _HTTPSHandler(context=_ssl_context())):
        opener.add_handler(handler)
    return opener


_OPENER = _build_opener()


def _blocked(url: str, why: str, start: float) -> dict:
    return {"url": url, "status": 0, "error": f"blocked: {why}", "headers": {}, "body": b"",
            "ms": int((time.time() - start) * 1000)}


def read_body(resp, headers: dict, deadline: float) -> tuple[bytes, bool]:
    """Reads at most MAX_BYTES of the decoded body before `deadline` (monotonic), so neither a gzip bomb
    nor a slow-drip server can exhaust memory or time."""
    reader = getattr(resp, "read1", resp.read)
    chunks, total = [], 0
    while total < MAX_BYTES:
        if time.monotonic() > deadline:
            raise TimeoutError("total deadline exceeded")
        chunk = reader(min(65536, MAX_BYTES - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    raw = b"".join(chunks)
    if headers.get("content-encoding", "").lower() != "gzip":
        return raw, len(raw) >= MAX_BYTES
    try:
        dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
        body = dec.decompress(raw, MAX_BYTES)
        return body, bool(dec.unconsumed_tail) or len(body) >= MAX_BYTES
    except zlib.error:
        return raw, False


def fetch(url: str) -> dict:
    """Fetches one http(s) URL without following redirects so chains stay visible."""
    start = time.time()
    deadline = time.monotonic() + TOTAL_TIMEOUT_S
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        return _blocked(url, "invalid URL", start)
    if parts.scheme not in ("http", "https") or not host or "%" in parts.netloc:
        return _blocked(url, "only plain http(s) URLs are fetched", start)
    if not ALLOW_PRIVATE and not host_is_public(host):
        return _blocked(url, "private or local address (use --allow-private for local development)", start)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        resp = _OPENER.open(req, timeout=TIMEOUT_S)
        status, hdrs = resp.status, dict(resp.headers)
    except urllib.error.HTTPError as err:
        status, hdrs, resp = err.code, dict(err.headers or {}), err
    except Exception as err:  # network failures are reported as data, not raised
        return {"url": url, "status": 0, "error": str(err)[:200], "headers": {}, "body": b"",
                "ms": int((time.time() - start) * 1000)}
    headers = {k.lower(): v for k, v in hdrs.items()}
    try:
        body, truncated = read_body(resp, headers, deadline) if getattr(resp, "fp", True) else (b"", False)
    except Exception as err:
        return {"url": url, "status": 0, "error": f"read: {err}"[:200], "headers": headers, "body": b"",
                "ms": int((time.time() - start) * 1000)}
    return {"url": url, "status": status, "headers": headers, "body": body, "truncated": truncated,
            "ms": int((time.time() - start) * 1000)}


def follow(url: str, limit: int = 6) -> tuple[dict, list[str]]:
    chain = [url]
    res = fetch(url)
    while res.get("status") in (301, 302, 303, 307, 308) and len(chain) <= limit:
        try:
            nxt = urllib.parse.urljoin(chain[-1], res["headers"].get("location", ""))
        except ValueError:
            break
        if nxt in chain:
            break
        chain.append(nxt)
        res = fetch(nxt)
    return res, chain


def norm(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))


def safe_norm(url: str) -> str | None:
    """norm() that returns None for malformed URLs (for example an unclosed IPv6 bracket) instead of raising."""
    try:
        return norm(url)
    except ValueError:
        return None


def safe_join(base: str, ref: str) -> str:
    try:
        return urllib.parse.urljoin(base, ref) if ref else ""
    except ValueError:
        return ""


def decode(body: bytes, headers: dict) -> str:
    m = re.search(r"charset=([\w-]+)", headers.get("content-type", ""))
    try:
        return body.decode(m.group(1) if m else "utf-8", errors="replace")
    except Exception:  # unknown or unusable charset names (LookupError, UnicodeError, ...)
        return body.decode("utf-8", errors="replace")


def schema_types(blocks: list[str]) -> tuple[list[str], int]:
    types: list[str] = []
    invalid = 0
    for raw in blocks:
        try:
            stack = [json.loads(raw)]
        except (ValueError, RecursionError):
            invalid += 1
            continue
        while stack:  # iterative, so deeply nested JSON-LD cannot overflow the stack
            o = stack.pop()
            if isinstance(o, dict):
                t = o.get("@type")
                if t:
                    types.extend(t if isinstance(t, list) else [t])
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
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
        try:
            absu = urllib.parse.urldefrag(urllib.parse.urljoin(chain[-1], href))[0]
            is_internal = urllib.parse.urlsplit(absu).netloc.lower() == host
        except ValueError:
            continue  # malformed href (for example an unclosed IPv6 bracket from a template placeholder)
        if "nofollow" in link["rel"]:
            nofollow += 1
        (internal if is_internal else external).add(absu)
    types, bad_schema = schema_types(p.jsonld)
    robots_meta = (p.meta.get("robots", "") + " " + res["headers"].get("x-robots-tag", "")).lower().strip()
    page.update({
        "title": re.sub(r"\s+", " ", p.title).strip(),
        "meta_description": p.meta.get("description", "").strip(),
        "h1": p.headings.get("h1", []),
        "h2": p.headings.get("h2", [])[:15],
        "canonical": safe_join(chain[-1], p.canonical),
        "robots": robots_meta,
        "noindex": "noindex" in robots_meta,
        "lang": p.lang,
        "hreflang": p.hreflang,
        "og_title": p.meta.get("og:title", ""),
        "og_image": p.meta.get("og:image", ""),
        "viewport": bool(p.meta.get("viewport")),
        "word_count": len(re.findall(r"\b\w+\b", " ".join(p.text))),
        "images": len(p.images),
        "images_missing_alt": sum(1 for i in p.images if i["alt"] is None),  # alt="" is valid for decorative images
        "scripts": p.scripts,
        "empty_shell": p.empty_shell,
        "truncated": bool(res.get("truncated")),
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
    robots, _ = follow(urllib.parse.urljoin(origin, "/robots.txt"))
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
        is_index = "<sitemapindex" in body
        locs = body.count("<loc>")
        sig["sitemaps"].append({"url": sm, "final_url": sm_chain[-1], "status": r.get("status"), "index": is_index,
                                "urls": 0 if is_index else locs, "children": locs if is_index else 0})
    llms, _ = follow(urllib.parse.urljoin(origin, "/llms.txt"))
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
    not_found = fetch(urllib.parse.urljoin(origin, NOT_FOUND_PROBE))
    sig["soft_404"] = not_found.get("status") == 200
    return sig, rp


def crawl(start: str, max_pages: int, delay: float, time_budget: float | None = None) -> dict:
    """Crawls up to max_pages; stops starting new pages once time_budget seconds have passed (if given)."""
    began = time.monotonic()
    first, chain = follow(start)
    if first.get("status") == 0:
        raise SystemExit(f"Cannot reach {start}: {first.get('error')}")
    parts = urllib.parse.urlsplit(chain[-1])
    origin, host = f"{parts.scheme}://{parts.netloc}", parts.netloc.lower()
    signals, rp = site_signals(origin)
    seen: set[str] = set()
    pages: list[dict] = []
    inlinks: Counter = Counter()
    start_url = norm(chain[-1])
    queue, queued = deque([(start_url, 0)]), {start_url}
    while queue and len(pages) < max_pages:
        if time_budget is not None and time.monotonic() - began > time_budget:
            break
        url, depth = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        if not rp.can_fetch("*", url):
            pages.append({"url": url, "status": "blocked_by_robots", "depth": depth})
            continue
        res, ch = follow(url)
        try:
            page = analyse_page(url, res, ch, host)
        except Exception as err:  # one hostile page must not abort the whole audit
            page = {"url": url, "final_url": ch[-1], "status": res.get("status"), "ms": res.get("ms"),
                    "redirects": len(ch) - 1, "error": f"analyse: {type(err).__name__}"}
        page["depth"] = depth
        pages.append(page)
        for link in page.get("internal_links", []):
            n = safe_norm(link)
            if n is None:
                continue
            inlinks[n] += 1
            if n not in seen and n not in queued and len(queued) < MAX_QUEUE \
                    and not SKIP_EXT.search(urllib.parse.urlsplit(n).path):
                queued.add(n)
                queue.append((n, depth + 1))
        time.sleep(delay)
    for p in pages:
        p["inlinks"] = inlinks.get(norm(p["url"]), 0)
        p["internal_link_count"] = len(p.pop("internal_links", []))
    return {"start": start, "origin": origin, "crawled": len(pages), "signals": signals, "pages": pages}


HIGH_WEIGHT = ("Search + AI crawler access", "robots.txt reachable", "HTTP redirects to HTTPS", "Broken internal pages",
               "Unreachable pages", "Title tag present", "Content present in server HTML")
MED_WEIGHT = ("XML sitemap", "Soft 404", "Mobile viewport", "Canonical tag present", "Exactly one H1", "Unique title",
              "Server response under", "Redirect chains")  # meta description and schema are hygiene: weight 1
POINTS = {"pass": 1.0, "warn": 0.5, "fail": 0.0}


def weight_of(name: str) -> int:
    return 3 if name.startswith(HIGH_WEIGHT) else (2 if name.startswith(MED_WEIGHT) else 1)


def check(level: str, area: str, name: str, detail: str, urls: list[str] | None = None) -> dict:
    return {"level": level, "area": area, "check": name, "detail": detail, "urls": (urls or [])[:15],
            "weight": weight_of(name)}


def weighted_score(checks: list[dict]) -> int | None:
    total = sum(c["weight"] for c in checks)
    if not total:
        return None
    return round(100 * sum(c["weight"] * POINTS[c["level"]] for c in checks) / total)


def technical_checks(audit: dict, pages: list[dict]) -> list[dict]:
    s, out = audit["signals"], []
    if None in s["ai_crawler_access"].values():
        out.append(check("fail", "technical", "robots.txt reachable", "Could not fetch robots.txt (network/TLS error)"))
    blocked = [b for b, ok in s["ai_crawler_access"].items() if ok is False]
    answer_blocked = [b for b in blocked if b in ANSWER_BOTS]
    training_blocked = [b for b in blocked if b in TRAINING_BOTS]
    level = "fail" if {"Googlebot", "Bingbot"} & set(answer_blocked) else ("warn" if answer_blocked else "pass")
    detail = "Search and answer bots blocked: " + (", ".join(answer_blocked) or "none")
    if training_blocked:
        detail += (". Training-only bots blocked (" + ", ".join(training_blocked) + "): your choice; this does not "
                   "remove you from search or AI answers")
    out.append(check(level, "ai-search", "Search + AI crawler access (robots.txt)", detail))
    out.append(check("pass" if s["http_to_https"] else "fail", "technical", "HTTP redirects to HTTPS",
                     " -> ".join(s["http_redirect_chain"])))
    if s["www_consolidated"] is False:
        out.append(check("warn", "technical", "www / non-www consolidation",
                         "Alternate host serves content without redirecting to the canonical host"))
    good_sm = [x for x in s["sitemaps"] if x["status"] == 200 and (x["urls"] or x["children"])]
    out.append(check("pass" if good_sm else "fail", "technical", "XML sitemap reachable",
                     "; ".join(f"{x['url']} -> {x.get('final_url')} ({x['status']}, "
                               + (f"index of {x['children']} sitemaps" if x["index"] else f"{x['urls']} urls") + ")"
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
    """Heuristic only (no browser runs here): flags server HTML that looks like an empty JavaScript app shell."""
    likely = [p["url"] for p in pages if p.get("empty_shell") and p["word_count"] < 80]
    possible = [p["url"] for p in pages if p["url"] not in likely and p["word_count"] < 60
                and p.get("scripts", 0) >= 5 and p.get("internal_link_count", 0) < 3]
    name = "Content present in server HTML (heuristic)"
    if not likely and not possible:
        return [check("pass", "ai-search", name, "No empty app shells detected in the server HTML")]
    home_hit = any(p.get("depth", 1) == 0 for p in pages if p["url"] in likely)
    level = "fail" if home_hit or len(likely) > len(pages) / 2 else "warn"
    return [check(level, "ai-search", name,
                  f"{len(likely)} pages look like an empty app shell and {len(possible)} serve very little text with "
                  "many scripts. This is a heuristic, not a render: confirm with curl or view-source. If true, "
                  "crawlers that do not run JavaScript (reported for GPTBot, ClaudeBot, PerplexityBot) see little: "
                  "use SSR/SSG or prerendering.", likely + possible)]


def onpage_checks(pages: list[dict]) -> list[dict]:
    out = []
    titles = Counter(p["title"] for p in pages if p["title"])
    missing_t = [p["url"] for p in pages if not p["title"]]
    bad_t = [p["url"] for p in pages if p["title"] and not TITLE_RANGE[0] <= len(p["title"]) <= TITLE_RANGE[1]]
    dup_t = [p["url"] for p in pages if p["title"] and titles[p["title"]] > 1]
    out.append(check("fail" if missing_t else "pass", "on-page", "Title tag present", f"{len(missing_t)} missing", missing_t))
    out.append(check("warn" if bad_t else "pass", "on-page", f"Title length {TITLE_RANGE[0]}-{TITLE_RANGE[1]} chars",
                     f"{len(bad_t)} clearly too short or too long (a longer title is fine if it states the topic)", bad_t))
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


def money_page_checks(pages: list[dict]) -> list[dict]:
    """Pages AI assistants and buyers lean on (pricing, comparison, alternatives): present, and linked from enough pages."""
    if len(pages) < MIN_PAGES_FOR_MONEY_CHECK:
        return []
    money = [p for p in pages if MONEY_PAGE.search(urllib.parse.urlsplit(p["url"]).path + "/")]
    if not money:
        return [check("warn", "ai-search", "Pricing or comparison pages found",
                      "None of the pages read look like a pricing, comparison or alternatives page. Pages that state "
                      "prices and compare options are the ones assistants lean on when people ask what to buy")]
    weak = [p["url"] for p in money if p.get("inlinks", 0) < MONEY_PAGE_MIN_INLINKS]
    return [check("warn" if weak else "pass", "on-page", f"Money pages linked from {MONEY_PAGE_MIN_INLINKS}+ pages",
                  f"{len(weak)} of {len(money)} pricing/comparison pages have fewer links in from your own pages", weak)]


NO_SNIPPET = re.compile(r"(?<![\w-])nosnippet(?![\w-])|max-snippet\s*:\s*0+(?![\d.])", re.I)


def snippet_blocked(robots) -> bool:
    """True when a robots directive string (meta robots plus X-Robots-Tag) forbids text snippets."""
    return isinstance(robots, str) and bool(NO_SNIPPET.search(robots))


def snippet_check(pages: list[dict]) -> dict:
    """One aggregated check: pages that forbid snippets cannot be quoted in results or by Google's AI features."""
    blocked = [p["url"] for p in pages if snippet_blocked(p.get("robots"))]
    if not blocked:
        return check("pass", "ai-search", "Snippets allowed (no nosnippet / max-snippet:0)", "0 pages block snippets")
    return check("warn", "ai-search", "Snippets allowed (no nosnippet / max-snippet:0)",
                 f"{len(blocked)} pages forbid text snippets (nosnippet or max-snippet:0). Google's own documentation says "
                 "these controls also limit what its AI features can quote. Remove them from pages you want cited", blocked)


def ai_search_checks(audit: dict, pages: list[dict]) -> list[dict]:
    out = [snippet_check(pages)]
    # llms.txt is recorded in signals but not scored: no evidence it changes citations.
    no_schema = [p["url"] for p in pages if not p.get("schema_types")]
    out.append(check("warn" if no_schema else "pass", "on-page", "JSON-LD structured data",
                     f"{len(no_schema)} pages without schema (helps rich-result eligibility; "
                     "a controlled test found no AI-citation lift from adding it)", no_schema))
    bad = [p["url"] for p in pages if p.get("schema_invalid_blocks")]
    if bad:
        out.append(check("fail", "on-page", "Valid JSON-LD", f"{len(bad)} pages with unparsable JSON-LD", bad))
    types = {t for p in pages for t in p.get("schema_types", [])}
    entity = types & {"Organization", "LocalBusiness", "Corporation", "Person", "WebSite", "ProfessionalService"}
    out.append(check("pass" if entity else "warn", "on-page", "Entity schema (Organization / Person / WebSite)",
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
        checks += rendering_checks(pages) + onpage_checks(pages) + ai_search_checks(audit, pages) + money_page_checks(pages)
    order = {"fail": 0, "warn": 1, "pass": 2}
    return sorted(checks, key=lambda c: (order[c["level"]], c["area"]))


def summarise(checks: list[dict]) -> dict:
    counts = Counter(c["level"] for c in checks)
    areas = sorted({c["area"] for c in checks})
    return {"fail": counts["fail"], "warn": counts["warn"], "pass": counts["pass"],
            "health_score": weighted_score(checks),
            "subscores": {a: weighted_score([c for c in checks if c["area"] == a]) for a in areas},
            "scoring": "weighted: critical checks x3, important x2, others x1; pass=1, warn=0.5, fail=0"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Crawl a site and score technical, on-page and AI-search checks.")
    ap.add_argument("url")
    ap.add_argument("--max-pages", type=int, default=50)
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between page requests")
    ap.add_argument("--out", default="", help="write the full JSON audit here")
    ap.add_argument("--allow-private", action="store_true",
                    help="allow localhost/private addresses (local development only; blocked by default)")
    args = ap.parse_args()
    global ALLOW_PRIVATE
    ALLOW_PRIVATE = args.allow_private
    url = args.url if re.match(r"^https?://", args.url) else "https://" + args.url
    if args.out:  # create the folder first so a bad path fails now, not after a full crawl
        try:
            os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        except OSError as err:
            print(f"Cannot create the output folder for {args.out}: {err}", file=sys.stderr)
            return 2
    audit = crawl(url, max(1, min(args.max_pages, 500)), max(0.0, args.delay))
    audit["checks"] = score(audit)
    audit["summary"] = summarise(audit["checks"])
    status = 0
    if args.out:
        try:
            with open(args.out, "w") as fh:
                json.dump(audit, fh, indent=2, default=str)
        except OSError as err:
            print(f"Could not write {args.out}: {err}. The crawl result is printed below.", file=sys.stderr)
            status = 1
    print(json.dumps({"origin": audit["origin"], "crawled": audit["crawled"], "summary": audit["summary"],
                      "checks": [{k: c[k] for k in ("level", "area", "check", "detail")} for c in audit["checks"]]},
                     indent=2))
    return status


if __name__ == "__main__":
    sys.exit(main())
