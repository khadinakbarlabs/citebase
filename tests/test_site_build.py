"""The website build: landing page + dashboard, static files only, safe by default."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402


class SiteBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        build_site.build("https://citebase.example/", self.out)

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_landing_dashboard_and_sign_in_identity(self):
        for rel in ("index.html", "landing.css", "favicon.svg", "app/index.html", "app/app.js", "app/core.js", "app/demo.js", "app/app.css",
                    "app/config.js", "oauth-client.json", "vercel.json"):
            self.assertTrue((self.out / rel).is_file(), rel)
        client = json.loads((self.out / "oauth-client.json").read_text())
        self.assertEqual(client["client_id"], "https://citebase.example/oauth-client.json")
        self.assertEqual(client["redirect_uris"], ["https://citebase.example/app/"])
        self.assertEqual(client["token_endpoint_auth_method"], "none")
        config = json.loads((self.out / "app/config.js").read_text().split("=", 1)[1].rstrip(";\n"))
        self.assertEqual(config["oauth"]["clientId"], client["client_id"])
        self.assertEqual(config["api"], "https://khadinakbar--citebase.apify.actor")

    def test_pages_carry_a_strict_policy_and_no_inline_script(self):
        for rel in ("index.html", "app/index.html"):
            html = (self.out / rel).read_text()
            self.assertIn("Content-Security-Policy", html)
            self.assertNotIn("unsafe-inline", html)
            self.assertNotIn("__SITE__", html)
            self.assertNotIn("<script>", html)  # scripts only by src
            self.assertNotIn(" style=", html)

    def test_dashboard_never_uses_inner_html(self):
        for path in (ROOT / "site/app").glob("*.js"):
            js = path.read_text()
            self.assertNotIn("innerHTML", js, path.name)
            self.assertNotIn("eval(", js, path.name)
            self.assertNotIn("localStorage", js, path.name)  # the sign-in token stays in this tab only

    def test_no_prices_on_the_site(self):
        for path in (ROOT / "site").rglob("*"):
            if path.suffix in (".html", ".js", ".css"):
                self.assertIsNone(re.search(r"\$\s?\d", path.read_text()), f"price in {path.name}")

    def test_refuses_a_plain_http_site(self):
        with self.assertRaises(SystemExit):
            build_site.build("http://citebase.example", self.out)


if __name__ == "__main__":
    unittest.main()


class PageScriptsTests(unittest.TestCase):
    def test_every_script_the_page_loads_exists(self):
        html = (ROOT / "site/app/index.html").read_text()
        for name in re.findall(r'<script src="([^"]+)"', html):
            if name != "config.js":  # written by the build
                self.assertTrue((ROOT / "site/app" / name).is_file(), name)
