"""Local AI-writing lint: script + connector wrapper. No network.

Callers: CI via `python3 -m unittest discover tests`. Covers scripts/ai_content_lint.py
and tools.check_ai_content / DISPATCH / playbooks. No data files.
User: improve product MCP with AI detection, humanize, SEO/EEAT, Apify-compliant.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "connector"))

import ai_content_lint as acl  # noqa: E402
import tools  # noqa: E402

SLOP = (
    "In today's digital age, it is important to note that experts say leveraging "
    "a robust tapestry of insights can foster transformative results. Additionally, "
    "studies show that a seamless paradigm is pivotal. Moreover, this underscores "
    "the crucial interplay that nestled solutions utilize."
)


class LintScriptTests(unittest.TestCase):
    def test_clean_prose_is_under_threshold(self):
        text = ("We shipped the update on Tuesday. Customers, partners, and support confirmed it. "
                "Overall, the release went well. Monday, Tuesday, and Wednesday were quiet.")
        hits, words = acl.lint_text(text)
        self.assertGreater(words, 20)
        self.assertEqual(hits, [])

    def test_stock_ai_phrases_are_flagged(self):
        hits, _words = acl.lint_text(SLOP)
        patterns = {h["pattern"] for h in hits}
        self.assertTrue(patterns & {"P14", "P15", "P35", "P36"})

    def test_phrase_boundaries_do_not_hit_longer_words(self):
        hits, _ = acl.lint_text("Booked as an airline for the trip. She was profiled indoors later.")
        self.assertEqual(hits, [])
        hits, _ = acl.lint_text("As an AI I cannot browse. She was profiled in Nature last year.")
        patterns = {h["pattern"] for h in hits}
        self.assertIn("P25", patterns)
        self.assertIn("P37", patterns)

    def test_not_only_but_also_counts_once(self):
        hits, _ = acl.lint_text("It is not only a notebook but also a planner for busy teams.")
        self.assertEqual(sum(1 for h in hits if h["pattern"] in ("P1", "P2")), 1)

    def test_adjective_triple_still_flags(self):
        hits, _ = acl.lint_text("Our stack is innovative, efficient, and scalable for every team.")
        self.assertTrue(any(h["pattern"] == "P3" for h in hits))


class CheckAiContentToolTests(unittest.TestCase):
    def test_pass_and_fail(self):
        clean = tools.check_ai_content("We fixed the bug. Customers confirmed it in chat.")
        self.assertTrue(clean["pass"])
        self.assertEqual(clean["hit_count"], 0)
        dirty = tools.check_ai_content(SLOP, threshold=5)
        self.assertFalse(dirty["pass"])
        self.assertGreater(dirty["hit_count"], 0)
        self.assertTrue(dirty["by_pattern"])

    def test_empty_and_bad_threshold(self):
        with self.assertRaises(ValueError):
            tools.check_ai_content("   ")
        with self.assertRaises(ValueError):
            tools.check_ai_content("hello world again", threshold=0)
        with self.assertRaises(ValueError):
            tools.check_ai_content("hello world again", threshold=101)

    def test_dispatch_and_playbooks(self):
        out = tools.dispatch("check_ai_content", {"text": SLOP})
        self.assertIn("density_per_1000_words", out)
        names = {p["name"] for p in tools.get_playbook()["playbooks"]}
        for skill in ("ai-content-check", "humanize-content", "eeat-audit", "content-optimize"):
            self.assertIn(skill, names)
        start = tools.get_playbook("start")["text"]
        self.assertIn("ai-content-check", start)
        self.assertIn("check_ai_content", start)


if __name__ == "__main__":
    unittest.main()
