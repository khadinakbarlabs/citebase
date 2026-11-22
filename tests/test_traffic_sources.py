"""The dashboard's copy of the traffic source lists must match the server's (connector/signals.py)."""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "connector"))
import signals  # noqa: E402

SCRIPT = (ROOT / "site" / "app" / "traffic-sources.js").read_text()


def js_object(name):
    body = re.search(r"var " + name + r" = \{(.*?)\};", SCRIPT, re.S).group(1)
    return dict(re.findall(r"'?([\w./-]+)'?\s*:\s*'([^']+)'", body))


class TrafficSourceListTests(unittest.TestCase):
    def test_lists_match_the_server(self):
        self.assertEqual(js_object("AI_REFERRERS"), signals.AI_REFERRERS)
        self.assertEqual(js_object("BARE_NAMES"), signals.BARE_NAMES)
        self.assertEqual(js_object("RETURN_HOSTS"), signals.RETURN_HOSTS)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_page_labels_sources_like_the_server(self):
        sources = ["chatgpt.com", "chatgpt.com / referral", "https://www.perplexity.ai/search", "claude",
                   "checkout.stripe.com", "accounts.google.com / referral", "www.paypal.com", "google",
                   "(direct)", "stripe.com", "notchatgpt.com.evil.io", "accounts.google.com.evil.io", "", "mychatgpt.community"]
        program = ("global.window={CB:{}};eval(require('fs').readFileSync(process.argv[1],'utf8'));"
                   "const t=window.CB.trafficSources;"
                   "console.log(JSON.stringify(JSON.parse(process.argv[2]).map(s=>[t.aiSource(s),t.returnSource(s)])))")
        out = subprocess.run(["node", "-e", program, str(ROOT / "site" / "app" / "traffic-sources.js"), json.dumps(sources)],
                             capture_output=True, text=True, check=True).stdout
        expected = [[signals.ai_source(s), signals.return_source(s)] for s in sources]
        self.assertEqual(json.loads(out), expected)


if __name__ == "__main__":
    unittest.main()
