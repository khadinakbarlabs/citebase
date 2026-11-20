"""Build the public pages and their same-origin sign-in service."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402


class LandingElements(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.elements = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def attributes(self, tag):
        return [attrs for name, attrs in self.elements if name == tag]


class SiteBuildTests(unittest.TestCase):
    def test_existing_project_storage_recovery(self):
        subprocess.run(["node", "--test", "tests/browser/project_storage.test.cjs"], cwd=ROOT,
                       text=True, capture_output=True, check=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        build_site.build("https://citebase.example/", self.out)

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_landing_dashboard_and_sign_in_identity(self):
        for rel in ("index.html", "landing.css", "landing.js", "favicon.svg", "app/index.html", "app/app.js", "app/core.js", "app/demo.js", "app/app.css",
                    "app/config.js", "app/session.js", "api/session.js", "api/actor.js", "oauth-client.json", "vercel.json"):
            self.assertTrue((self.out / rel).is_file(), rel)
        client = json.loads((self.out / "oauth-client.json").read_text())
        self.assertEqual(client["client_id"], "https://citebase.example/oauth-client.json")
        self.assertEqual(client["redirect_uris"], ["https://citebase.example/app/"])
        self.assertEqual(client["token_endpoint_auth_method"], "none")
        config = json.loads((self.out / "app/config.js").read_text().split("=", 1)[1].rstrip(";\n"))
        self.assertEqual(config["oauth"]["clientId"], client["client_id"])
        self.assertIs(config["oauth"]["session"], True)
        hosting = json.loads((self.out / "vercel.json").read_text())
        self.assertIn({"source": "/landing.html", "destination": "/", "permanent": True}, hosting.get("redirects", []))
        self.assertEqual(hosting["functions"]["api/actor.js"]["maxDuration"], 300)
        self.assertEqual(config["api"], "https://khadinakbar--citebase.apify.actor")

    def test_build_for_published_history_api_keeps_the_production_oauth_identity(self):
        build_site.build("https://citebase.example", self.out, history_only=True)
        config = json.loads((self.out / "app/config.js").read_text().split("=", 1)[1].rstrip(";\n"))
        self.assertIs(config["projectWork"], False)
        self.assertFalse((self.out / "api/actor.js").exists())
        self.assertNotIn("functions", json.loads((self.out / "vercel.json").read_text()))
        self.assertEqual(config["oauth"]["redirectUri"], "https://citebase.example/app/")

    def test_pages_carry_a_strict_policy_and_no_inline_script(self):
        for rel in ("index.html", "app/index.html"):
            html = (self.out / rel).read_text()
            self.assertIn("Content-Security-Policy", html)
            self.assertNotIn("unsafe-inline", html)
            self.assertNotIn("__SITE__", html)
            self.assertNotIn("<script>", html)  # scripts only by src
            self.assertNotIn(" style=", html)

    def test_landing_only_contacts_its_first_party_session_service(self):
        page = LandingElements((self.out / "index.html").read_text())
        self.assertEqual([script["src"] for script in page.attributes("script")], ["appearance.js", "app/session.js", "landing.js"])
        policy = next(meta["content"] for meta in page.attributes("meta")
                      if meta.get("http-equiv") == "Content-Security-Policy")
        directives = {parts[0]: parts[1:] for rule in policy.split(";") if (parts := rule.split())}
        self.assertEqual(directives["default-src"], ["'none'"])
        self.assertEqual(directives["script-src"], ["'self'"])
        self.assertEqual(directives["connect-src"], ["'self'"])
        auth_links = [link for link in page.attributes("a") if "data-account-link" in link]
        self.assertEqual([link["href"] for link in auth_links], ["/api/session/?start"] * 2)

        links = {link["href"] for link in page.attributes("a")}
        anchors = {attrs["id"] for _, attrs in page.elements if "id" in attrs}
        self.assertTrue({link[1:] for link in links if link.startswith("#")} <= anchors)
        self.assertTrue({"#examples", "#install", "/api/session/?start"} <= links)
        self.assertNotIn("app/", links)
        self.assertTrue({
            "app/?demo=1#/p/northwind-cafe/answers", "app/?demo=1#/p/northwind-cafe/todo?record=sample-0",
            "app/?demo=1#/p/acme-payroll/questions", "app/?demo=1#/p/acme-payroll/answers",
            "app/?demo=1#/p/acme-payroll/todo?record=sample-2",
        } <= links)
        # Without JavaScript, every story is readable and the install commands can be selected.
        panels = [attrs for attrs in page.attributes("section") if "data-stage" in attrs]
        self.assertCountEqual([p["data-stage"] for p in panels], ["question", "evidence", "action"] * 2)
        self.assertTrue(all("hidden" not in p for p in panels))
        self.assertIn("claude plugin install citebase@citebase", (self.out / "index.html").read_text())

    def test_shared_appearance_is_served_from_the_site_on_both_pages(self):
        for path, prefix in (("index.html", ""), ("app/index.html", "../")):
            page = LandingElements((self.out / path).read_text())
            self.assertIn(prefix + "appearance.css", [link["href"] for link in page.attributes("link")])
            self.assertIn(prefix + "appearance.js", [script["src"] for script in page.attributes("script")])
            self.assertTrue(any("data-theme-toggle" in button for button in page.attributes("button")))
            policy = next(m["content"] for m in page.attributes("meta") if m.get("http-equiv") == "Content-Security-Policy")
            self.assertIn("font-src 'self'", policy.split("; "))
        for name in ("geist-latin.woff2", "manrope-latin.woff2"):
            self.assertEqual((self.out / "assets" / name).read_bytes()[:4], b"wOF2")
        self.assertIn('id="moon"', (self.out / "assets" / "icons.svg").read_text())

    def test_landing_readings_match_the_dashboard_samples(self):
        fixture = """
            global.window = {};
            require('./site/app/demo.js');
            const history = project => window.CB_DEMO.call('get_history', {project});
            console.log(JSON.stringify([history('northwind-cafe'), history('acme-payroll')]));
        """
        cafe, payroll = json.loads(subprocess.check_output(
            ["node", "-e", fixture], cwd=ROOT, text=True, timeout=10,
        ))
        page = (self.out / "index.html").read_text()
        meters = LandingElements(page).attributes("meter")
        baseline = cafe["snapshots"][0]
        question = next(q for q in payroll["questions"] if q["prompt_id"] == "q1")
        self.assertIn(question["question"].casefold(), page.casefold())
        self.assertIn(f'First round · {baseline["prompts"]} questions · {len(baseline["engines"])} engines', page)
        self.assertEqual([(int(m["value"]), int(m["max"])) for m in meters], [
            (round(100 * baseline["recommendation_share"]), 100),
            (round(100 * baseline["by_engine"]["chatgpt"]["recommendation_share"]), 10),
            (round(100 * baseline["by_engine"]["google-aio"]["recommendation_share"]), 10),
            (question["recommended"], question["answers"]),
        ])
        source = next(s for s in payroll["citation_gap"]["sites"] if s["site"] == "capterra.com")
        for key in ("answers_citing_it", "answers_for_rivals_without_you"):
            self.assertIn(f'<dd>{source[key]}</dd>', page)

    def test_dashboard_never_uses_inner_html(self):
        for path in (ROOT / "site/app").glob("*.js"):
            js = path.read_text()
            self.assertNotIn("innerHTML", js, path.name)
            self.assertNotIn("eval(", js, path.name)
            if path.name == "session.js":
                self.assertEqual(re.findall(r"localStorage\.[^(]+\('([^']+)'", js), ["cb.session-event"] * 2)
            else:
                self.assertNotIn("localStorage", js, path.name)

    def test_no_prices_on_the_site(self):
        for path in (ROOT / "site").rglob("*"):
            if path.suffix in (".html", ".js", ".css"):
                self.assertIsNone(re.search(r"\$\s?\d", path.read_text()), f"price in {path.name}")

    def test_refuses_a_plain_http_site(self):
        for site in ("http://citebase.example", "http://localhost.elsewhere.test", "https://user@citebase.example",
                     "https://citebase.example/untrusted", "https://citebase.example?site=elsewhere"):
            with self.subTest(site=site), self.assertRaises(SystemExit):
                build_site.build(site, self.out)

    def test_tab_only_oauth_is_explicit_and_limited_to_loopback_hosts(self):
        with self.assertRaises(SystemExit):
            build_site.build("https://citebase.example", self.out, local_static=True)
        build_site.build("http://127.0.0.1:9876", self.out, local_static=True)
        self.assertFalse((self.out / "api/session.js").exists())
        self.assertFalse((self.out / "api/actor.js").exists())
        page = LandingElements((self.out / "index.html").read_text())
        self.assertEqual([link["href"] for link in page.attributes("a") if "data-account-link" in link], ["app/?signin=1"] * 2)

    def test_session_lifecycle(self):
        result = subprocess.run(["node", "--test", "tests/browser/site_session.test.cjs"], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()


class PageScriptsTests(unittest.TestCase):
    def test_every_script_the_page_loads_exists(self):
        html = (ROOT / "site/app/index.html").read_text()
        for name in re.findall(r'<script src="([^"]+)"', html):
            if name != "config.js":  # written by the build
                self.assertTrue((ROOT / "site/app" / name).is_file(), name)
