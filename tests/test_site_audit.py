"""Tests for scripts/site_audit.py using a local fixture server (no real network traffic)."""
import gzip
import http.server
import json
import os
import subprocess
import sys
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "site_audit.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import site_audit as sa  # noqa: E402

WORDS = " ".join(f"word{i}" for i in range(400))
HOME = f"""<!doctype html><html lang="en"><head><title>Citebase fixture home page for testing</title>
<meta name="description" content="A fixture page used to test the Citebase crawler and its on-page checks properly.">
<meta name="viewport" content="width=device-width"><link rel="canonical" href="/">
<script type="application/ld+json">{{"@type": "Organization", "name": "Fixture"}}</script></head>
<body><h1>Fixture home</h1><p>{WORDS}</p><a href="/about">About us</a> <a href="/spa">App</a>
<img src="a.png"><img src="b.png" alt=""><img src="c.png" alt="A real description"></body></html>"""
ABOUT = """<!doctype html><html lang="en"><head><title>About the fixture company and team</title>
<meta name="viewport" content="width=device-width"></head><body>
<svg><title>Decorative icon title</title><path d="M0 0"/></svg><h1>About</h1><p>Short but real page.</p>
<a href="/">Home</a></body></html>"""
SPA = """<!doctype html><html lang="en"><head><title>App shell fixture page title here</title>
<meta name="viewport" content="width=device-width"></head><body><div id="root"></div>
<script src="/a.js"></script><script src="/b.js"></script></body></html>"""
BOMB = gzip.compress(b"\0" * 20_000_000)
SITEMAP = "<urlset><url><loc>http://x/</loc></url><url><loc>http://x/about</loc></url></urlset>"
INDEX = "<sitemapindex><sitemap><loc>http://x/s1.xml</loc></sitemap><sitemap><loc>http://x/s2.xml</loc></sitemap></sitemapindex>"
ROUTES = {
    "/": (200, "text/html", HOME, {}), "/about": (200, "text/html", ABOUT, {}), "/spa": (200, "text/html", SPA, {}),
    "/robots.txt": (200, "text/plain", "User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n", {}),
    "/sitemap.xml": (200, "application/xml", SITEMAP, {}), "/index.xml": (200, "application/xml", INDEX, {}),
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/bomb":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(BOMB)))
            self.end_headers()
            self.wfile.write(BOMB)
            return
        status, ctype, body, extra = ROUTES.get(self.path, (404, "text/html", "<h1>nope</h1>", {}))
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        sa.ALLOW_PRIVATE = True
        patcher = mock.patch.object(sa, "TIMEOUT_S", 3)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, sa, "ALLOW_PRIVATE", False)


class SafetyTests(ServerCase):
    def test_host_is_public_literals(self):
        for ip in ("127.0.0.1", "10.1.2.3", "192.168.0.9", "169.254.169.254", "::1", "100.64.0.1", "0.0.0.0",
                   "::ffff:10.0.0.1", "fd00::1"):
            self.assertFalse(sa.host_is_public(ip), ip)
        for ip in ("93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"):
            self.assertTrue(sa.host_is_public(ip), ip)

    def test_non_http_schemes_are_refused(self):
        for url in ("file:///etc/passwd", "ftp://example.com/x", "data:text/html,hi", "gopher://x"):
            res = sa.fetch(url)
            self.assertEqual(res["status"], 0, url)
            self.assertIn("blocked", res["error"])

    def test_private_hosts_blocked_by_default(self):
        sa.ALLOW_PRIVATE = False
        res = sa.fetch(self.base + "/")
        self.assertEqual(res["status"], 0)
        self.assertIn("blocked", res["error"])
        self.assertEqual(sa.fetch("http://169.254.169.254/latest/meta-data/")["status"], 0)

    def test_peer_guard_catches_dns_rebinding(self):
        sa.ALLOW_PRIVATE = False
        with mock.patch.object(sa, "host_is_public", return_value=True):
            res = sa.fetch(self.base + "/")
        self.assertEqual(res["status"], 0)
        self.assertIn("blocked", res["error"])

    def test_gzip_bomb_is_bounded(self):
        res = sa.fetch(self.base + "/bomb")
        self.assertEqual(res["status"], 200)
        self.assertLessEqual(len(res["body"]), sa.MAX_BYTES)
        self.assertTrue(res["truncated"])

    def test_normal_page_not_marked_truncated(self):
        self.assertFalse(sa.fetch(self.base + "/about")["truncated"])


class ParsingTests(ServerCase):
    def page(self, path):
        res, chain = sa.follow(self.base + path)
        return sa.analyse_page(self.base + path, res, chain, f"127.0.0.1:{self.server.server_address[1]}")

    def test_title_ignores_svg_title(self):
        self.assertEqual(self.page("/about")["title"], "About the fixture company and team")

    def test_alt_text_empty_alt_is_decorative_not_missing(self):
        page = self.page("/")
        self.assertEqual(page["images"], 3)
        self.assertEqual(page["images_missing_alt"], 1)

    def test_headings_and_schema(self):
        page = self.page("/")
        self.assertEqual(page["h1"], ["Fixture home"])
        self.assertIn("Organization", page["schema_types"])

    def test_app_shell_detected_and_short_static_page_is_not(self):
        spa, about = self.page("/spa"), self.page("/about")
        self.assertTrue(spa["empty_shell"])
        self.assertFalse(about["empty_shell"])
        spa["depth"], about["depth"] = 0, 1
        spa["internal_link_count"] = about["internal_link_count"] = 0
        flagged = sa.rendering_checks([spa, about])[0]
        self.assertEqual(flagged["level"], "fail")
        self.assertEqual(flagged["urls"], [self.base + "/spa"])
        self.assertEqual(sa.rendering_checks([about])[0]["level"], "pass")


class ScoringTests(unittest.TestCase):
    def test_critical_failure_costs_more_than_minor_failure(self):
        crit = sa.check("fail", "technical", "HTTP redirects to HTTPS", "x")
        minor = sa.check("fail", "on-page", "Open Graph title + image", "x")
        ok = sa.check("pass", "technical", "XML sitemap reachable", "x")
        self.assertEqual(crit["weight"], 3)
        self.assertEqual(minor["weight"], 1)
        self.assertLess(sa.weighted_score([crit, ok]), sa.weighted_score([minor, ok]))

    def test_summary_has_subscores_per_area(self):
        s = sa.summarise([sa.check("pass", "technical", "XML sitemap reachable", ""),
                          sa.check("fail", "on-page", "Exactly one H1", "")])
        self.assertEqual(s["subscores"], {"on-page": 0, "technical": 100})
        self.assertEqual(s["health_score"], 50)


class CrawlTests(ServerCase):
    def test_sitemap_index_counts_children(self):
        sig, _ = sa.site_signals(self.base)
        self.assertFalse(sig["sitemaps"][0]["index"])
        self.assertEqual(sig["sitemaps"][0]["urls"], 2)

    def test_end_to_end_cli(self):
        proc = subprocess.run([sys.executable, SCRIPT, self.base, "--allow-private", "--max-pages", "5",
                               "--delay", "0"], capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["crawled"], 3)
        self.assertIn("technical", out["summary"]["subscores"])
        names = {c["check"] for c in out["checks"]}
        self.assertIn("Content present in server HTML (heuristic)", names)
        self.assertNotIn("llms.txt present", names)

    def test_cli_refuses_localhost_without_flag(self):
        proc = subprocess.run([sys.executable, SCRIPT, self.base, "--delay", "0"], capture_output=True, text=True,
                              timeout=60)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("blocked", proc.stderr + proc.stdout)


class ReauditScoringTests(unittest.TestCase):
    """Fixes from the transcript re-audit: answer bots vs training bots, schema and meta weights, title length."""

    def audit_with_blocked(self, blocked):
        access = {bot: (bot not in blocked) for bot in sa.AI_CRAWLERS}
        audit = {"signals": {"ai_crawler_access": access, "http_to_https": True, "http_redirect_chain": [],
                             "www_consolidated": True, "sitemaps": [], "soft_404": False}, "pages": []}
        return [c for c in sa.technical_checks(audit, []) if c["check"].startswith("Search + AI crawler")][0]

    def test_blocking_training_bots_is_not_a_problem(self):
        c = self.audit_with_blocked({"GPTBot", "CCBot", "Google-Extended"})
        self.assertEqual(c["level"], "pass")
        self.assertIn("your choice", c["detail"])
        self.assertEqual(c["area"], "ai-search")

    def test_blocking_an_answer_bot_warns_and_blocking_search_fails(self):
        self.assertEqual(self.audit_with_blocked({"OAI-SearchBot"})["level"], "warn")
        self.assertEqual(self.audit_with_blocked({"PerplexityBot"})["level"], "warn")
        self.assertEqual(self.audit_with_blocked({"Googlebot"})["level"], "fail")

    def test_schema_and_meta_are_hygiene_not_heavy(self):
        for name in ("JSON-LD structured data", "Valid JSON-LD", "Entity schema (Organization / Person / WebSite)",
                     "Meta description present"):
            self.assertEqual(sa.weight_of(name), 1, name)
        self.assertEqual(sa.weight_of("Content present in server HTML (heuristic)"), 3)

    def test_long_titles_are_allowed_but_tiny_ones_are_not(self):
        self.assertEqual(sa.TITLE_RANGE[0], 15)
        self.assertGreaterEqual(sa.TITLE_RANGE[1], 90)

    def test_money_page_check_needs_enough_pages_and_finds_pricing(self):
        pages = [{"url": f"https://x.example/p{i}", "inlinks": 9} for i in range(12)]
        names = [c["check"] for c in sa.money_page_checks(pages)]
        self.assertEqual(names, ["Pricing or comparison pages found"])
        pages.append({"url": "https://x.example/pricing", "inlinks": 1})
        out = sa.money_page_checks(pages)
        self.assertEqual(out[0]["level"], "warn")
        self.assertEqual(out[0]["urls"], ["https://x.example/pricing"])
        self.assertEqual(sa.money_page_checks(pages[:3]), [])  # tiny crawls are not judged


if __name__ == "__main__":
    unittest.main()
