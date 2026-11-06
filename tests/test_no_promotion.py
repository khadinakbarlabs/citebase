"""Citebase never sells, ranks or recommends outside products or services, and the Store text has no off-platform links."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVED = ["skills", "references", "agents", ".actor", "connector", "README.md"]
# outside commercial products/services that must not be named, sold or recommended anywhere we ship
BANNED = [r"reachinbox", r"\binstantly\b", r"smartlead", r"zapmail", r"qwoted", r"featured\.com",
          r"source of sources", r"help a b2b writer", r"\bprnow\b", r"insert\.?link", r"\bmailshake\b", r"\blemlist\b"]
OFF_PLATFORM_OK = ("apify.com", "example.com", "example.org", "json-schema.org", "localhost", "127.0.0.1",
                   "github.com/khadinakbarlabs")


def files():
    for entry in SERVED:
        path = os.path.join(ROOT, entry)
        if os.path.isfile(path):
            yield path
            continue
        for base, _dirs, names in os.walk(path):
            if "__pycache__" in base:
                continue
            for name in names:
                if name.endswith((".md", ".json", ".py", ".txt")):
                    yield os.path.join(base, name)


class NoPromotionTests(unittest.TestCase):
    def test_no_outside_product_names(self):
        pattern = re.compile("|".join(BANNED), re.I)
        hits = []
        for path in files():
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if pattern.search(line):
                        hits.append(f"{os.path.relpath(path, ROOT)}:{n}")
        self.assertEqual(hits, [], "outside products are named here")

    def test_store_text_has_no_off_platform_links(self):
        for rel in (".actor/ACTOR_README.md", ".actor/actor.json", ".actor/CHANGELOG.md"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for url in re.findall(r"https?://[^\s)\"'`\\]+", text):
                self.assertTrue(any(ok in url for ok in OFF_PLATFORM_OK), f"{rel}: {url}")

    def test_playbooks_say_citebase_does_not_sell_anything(self):
        with open(os.path.join(ROOT, "references", "outreach-playbook.md"), encoding="utf-8") as fh:
            self.assertIn("does not sell", fh.read())
        with open(os.path.join(ROOT, "skills", "link-building", "SKILL.md"), encoding="utf-8") as fh:
            self.assertIn("does not sell", fh.read())


if __name__ == "__main__":
    unittest.main()
