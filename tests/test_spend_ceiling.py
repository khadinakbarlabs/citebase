"""The default daily spend ceiling must let the documented baseline (the ai_check pack) run.

The ai_check pack quotes a suggested cap of about $30.82 at the worst case. A default ceiling below that would make the
plugin deny the very first measurement it recommends, so the default is $40. The per-run limit stays $2: a run above it
still asks first, and a missing or invalid cap is still denied.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import approval_gate  # noqa: E402
import cb_state  # noqa: E402
import tools  # noqa: E402
from test_approval_gate import APIFY, GateCase  # noqa: E402

DEFAULT_CEILING = 40


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class DefaultCeilingValueTests(unittest.TestCase):
    def test_the_code_default_is_forty_and_shared(self):
        self.assertEqual(approval_gate.DEFAULT_DAILY_SPEND_USD, DEFAULT_CEILING)
        self.assertEqual(cb_state.DEFAULT_DAILY_SPEND_USD, DEFAULT_CEILING)

    def test_the_plugin_setting_defaults_match(self):
        cfg = json.loads(read(".claude-plugin", "plugin.json"))["userConfig"]
        self.assertEqual(cfg["daily_spend_usd"]["default"], DEFAULT_CEILING)
        self.assertEqual(cfg["max_run_usd"]["default"], 2)  # unchanged: bigger runs still ask first
        self.assertGreaterEqual(cfg["daily_spend_usd"]["max"], DEFAULT_CEILING)

    def test_the_per_run_limit_default_is_still_two_dollars(self):
        self.assertEqual(approval_gate.DEFAULT_MAX_RUN_USD, 2.0)

    def test_the_readme_table_and_references_say_forty(self):
        row = next(line for line in read("README.md").splitlines() if line.startswith("| `daily_spend_usd`"))
        self.assertRegex(row, r"\|\s*40\s*\|")
        refs = read("references", "tools-and-apis.md")
        self.assertIn("`daily_spend_usd` (default $40)", refs)
        self.assertIn("`max_run_usd` (default $2)", refs)

    def test_no_document_still_names_the_old_default(self):
        for parts in (("README.md",), ("references", "tools-and-apis.md"), (".claude-plugin", "plugin.json")):
            self.assertNotRegex(read(*parts), r"(?i)daily[^\n]{0,80}\$25\b|daily_spend_usd[^\n]{0,40}\b25\b")

    def test_the_ledger_status_line_uses_the_shared_default(self):
        source = read("scripts", "outreach_ledger.py")
        self.assertNotIn("25.0", source)
        self.assertIn("DEFAULT_DAILY_SPEND_USD", source)


class BaselineFitsTests(unittest.TestCase):
    def test_the_ai_check_cap_fits_under_the_default_daily_ceiling(self):
        cap = tools.quote_cost(pack="ai_check")["suggested_cap_usd"]
        self.assertGreater(cap, 30)  # the worst case really is this large
        self.assertLessEqual(cap, approval_gate.DEFAULT_DAILY_SPEND_USD)

    def test_the_baseline_plus_two_other_first_look_packs_still_fits_one_day(self):
        caps = sum(tools.quote_cost(pack=p)["suggested_cap_usd"] for p in ("ai_check", "starter", "competitors"))
        self.assertLessEqual(caps, approval_gate.DEFAULT_DAILY_SPEND_USD)


class GateWithDefaultSettingsTests(GateCase):
    """Runs the real hook with no plugin options set, so the built-in defaults apply."""

    def test_the_documented_baseline_is_not_denied_on_a_fresh_day(self):
        cap = tools.quote_cost(pack="ai_check")["suggested_cap_usd"]
        _, decision, out = self.run_gate("pre", APIFY, self.actor(name="khadinakbar/ai-search-brand-monitor", cap=cap))
        self.assertEqual(decision, "ask", out)  # above the $2 per-run limit: asks first, never denies

    def test_a_run_over_the_per_run_limit_still_asks_first(self):
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=2.5))
        self.assertEqual(decision, "ask")

    def test_a_run_inside_the_limit_passes(self):
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=1.5))
        self.assertIsNone(decision)

    def test_a_missing_cap_is_still_denied(self):
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=None))
        self.assertEqual(decision, "deny")

    def test_a_cap_above_the_new_ceiling_is_still_denied(self):
        _, decision, out = self.run_gate("pre", APIFY, self.actor(cap=41))
        self.assertEqual(decision, "deny")
        self.assertIn("$40.00", out)

    def test_spend_already_committed_counts_against_the_forty_dollar_ceiling(self):
        self.run_gate("post", APIFY, self.actor(cap=30.82))
        _, decision, out = self.run_gate("pre", APIFY, self.actor(cap=10))
        self.assertEqual(decision, "deny")
        self.assertIn("daily", out.lower())

    def test_a_ceiling_set_by_the_user_still_wins(self):
        self.opts["CLAUDE_PLUGIN_OPTION_DAILY_SPEND_USD"] = "10"
        self.opts["CLAUDE_PLUGIN_OPTION_MAX_RUN_USD"] = "50"
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=12))
        self.assertEqual(decision, "deny")


if __name__ == "__main__":
    unittest.main()
