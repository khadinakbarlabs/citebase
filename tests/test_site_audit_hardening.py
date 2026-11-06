"""Regression tests for the security review of the crawler (findings 1, 2, 10, 11, 12, 14)."""
import http.server
import os
import sys
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import site_audit as sa  # noqa: E402


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, body=b"", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/robots.txt":
            self.send(301, headers={"Location": "/real-robots"})
        elif self.path == "/real-robots":
            self.send(200, b"User-agent: *\nDisallow: /\n", {"Content-Type": "text/plain"})
        elif self.path == "/badloc":
            self.send(302, headers={"Location": "http://[::1"})
        elif self.path == "/drip":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "1000000")
            self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.3)
            except OSError:
                pass
        else:
            self.send(404, b"nope", {"Content-Type": "text/html"})


def html_response(body: str) -> dict:
    return {"status": 200, "headers": {"content-type": "text/html"}, "body": body.encode(), "ms": 1}


class ParserRobustnessTests(unittest.TestCase):
    def analyse(self, body):
        return sa.analyse_page("http://h/", html_response(body), ["http://h/"], "h")

    def test_hostile_div_soup_is_linear_time(self):
        for body in ("<div a" * 30000, '<div id="root"><noscript>' * 8000):
            start = time.time()
            self.analyse(body)
            self.assertLess(time.time() - start, 3.0)

    def test_malformed_urls_do_not_abort_the_page(self):
        page = self.analyse('<html><head><link rel="canonical" href="http://[x"></head>'
                            '<body><h1>Hi</h1><a href="http://[::1">bad</a><a href="/ok">ok</a></body></html>')
        self.assertEqual(page["h1"], ["Hi"])
        self.assertEqual(page["status"], 200)

    def test_decode_survives_unusable_charsets(self):
        for charset in ("undefined", "idna", "no-such-charset"):
            self.assertIsInstance(sa.decode(b"hello", {"content-type": f"text/html; charset={charset}"}), str)

    def test_deeply_nested_json_ld_does_not_crash(self):
        types, bad = sa.schema_types(["[" * 100000 + "]" * 100000])
        self.assertEqual(types, [])
        self.assertEqual(bad, 1)

    def test_empty_app_shell_detection_is_structural(self):
        shell = self.analyse('<html><body><div id="root"></div><script src="a.js"></script></body></html>')
        rendered = self.analyse('<html><body><div id="root"><h1>Real</h1><p>Server rendered text.</p></div></body></html>')
        noscript = self.analyse('<html><body><div id="app"><noscript>Enable JS</noscript></div></body></html>')
        self.assertTrue(shell["empty_shell"])
        self.assertFalse(rendered["empty_shell"])
        self.assertTrue(noscript["empty_shell"])

    def test_link_collection_is_capped(self):
        links = "".join(f'<a href="/p{i}">x</a>' for i in range(sa.MAX_LINKS_PER_PAGE + 3000))
        page = self.analyse(f"<html><body>{links}</body></html>")
        self.assertLessEqual(len(page["internal_links"]), sa.MAX_LINKS_PER_PAGE)


class AddressTests(unittest.TestCase):
    def test_embedded_and_special_ipv6_forms_are_not_public(self):
        for ip in ("::127.0.0.1", "64:ff9b::7f00:1", "224.0.0.1", "ff02::1", "2002:7f00:1::", "2002:0a00:0001::"):
            self.assertFalse(sa.host_is_public(ip), ip)

    def test_percent_encoded_hosts_are_refused_before_any_connection(self):
        sa.ALLOW_PRIVATE = False
        with mock.patch.object(sa._OPENER, "open") as opener:
            res = sa.fetch("https://localhost%2e:9/")
        self.assertEqual(res["status"], 0)
        self.assertTrue(res["error"].startswith("blocked"))
        opener.assert_not_called()


class NetworkBehaviourTests(unittest.TestCase):
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
        self.addCleanup(setattr, sa, "ALLOW_PRIVATE", False)
        patcher = mock.patch.object(sa, "TIMEOUT_S", 3)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_bad_location_header_does_not_raise(self):
        res, chain = sa.follow(self.base + "/badloc")
        self.assertIn(res["status"], (0, 302))  # urllib may reject the bad Location itself; either way no crash
        self.assertEqual(len(chain), 1)

    def test_robots_txt_redirect_is_followed(self):
        sig, _ = sa.site_signals(self.base)
        self.assertEqual(sig["robots_txt"]["status"], 200)
        self.assertFalse(sig["ai_crawler_access"]["GPTBot"])

    def test_slow_drip_response_hits_total_deadline(self):
        with mock.patch.object(sa, "TOTAL_TIMEOUT_S", 1.0):
            start = time.time()
            res = sa.fetch(self.base + "/drip")
        self.assertLess(time.time() - start, 4.0)
        self.assertEqual(res["status"], 0)
        self.assertIn("deadline", res["error"])


if __name__ == "__main__":
    unittest.main()
