"""Only the owner's own Actors (khadinakbar/*) are ever used or recommended."""
import asyncio
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import runner  # noqa: E402
import storage as stg  # noqa: E402
import tools  # noqa: E402
import server  # noqa: E402


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class PriceListIsOwnActorsOnly(unittest.TestCase):
    def test_every_job_and_fallback_is_a_khadinakbar_actor(self):
        for job, spec in tools.PRICES["jobs"].items():
            self.assertTrue(spec["actor"].startswith("khadinakbar/"), f"{job}: {spec['actor']}")

    def test_no_document_or_playbook_names_another_creators_actor(self):
        pattern = re.compile(r"apify\.com/(?!v2|storage|docs|store|api|contact|change-log|about|pricing|console)"
                             r"([a-z0-9_.-]+)/[a-z0-9_.-]+")
        for rel in ("skills", "agents", "references", ".actor", "docs"):
            for base, _d, names in os.walk(os.path.join(ROOT, rel)):
                for name in names:
                    if not name.endswith((".md", ".json")):
                        continue
                    for owner in pattern.findall(read(os.path.relpath(os.path.join(base, name), ROOT))):
                        self.assertEqual(owner, "khadinakbar", f"{name} links another owner: {owner}")
        for owner in pattern.findall(read("README.md")):
            self.assertEqual(owner, "khadinakbar")

    def test_the_rule_is_in_the_server_instructions_and_every_quote(self):
        self.assertIn(tools.OWN_ACTORS, server.INSTRUCTIONS)
        for pack in ("starter", "ai_check_pilot"):
            self.assertIn(tools.OWN_ACTORS, tools.quote_cost(pack=pack)["how_to_run"])


class ImportedResultsMustComeFromOwnActors(unittest.TestCase):
    def setUp(self):
        self.be = stg.MemoryBackend()
        stg.set_backend(self.be)
        self.be.datasets["ownDataset123"] = [{"a": 1}]
        self.be.datasets["otherDataset123"] = [{"a": 1}]
        self.be.datasets["handMade12345"] = [{"a": 1}]
        self.be.dataset_sources["ownDataset123"] = "khadinakbar/ai-search-brand-monitor"
        self.be.dataset_sources["otherDataset123"] = "someone/else-scraper"

    def tearDown(self):
        stg.set_backend(None)

    def test_own_and_hand_made_datasets_are_read(self):
        items, ids = asyncio.run(runner.fetch_datasets(["ownDataset123", "handMade12345"], []))
        self.assertEqual(len(items), 2)
        self.assertEqual(ids, ["ownDataset123", "handMade12345"])

    def test_another_creators_dataset_is_refused_before_anything_is_read(self):
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(runner.fetch_datasets(["ownDataset123", "otherDataset123"], []))
        self.assertIn("someone/else-scraper", str(ctx.exception))
        self.assertIn("Nothing was imported", str(ctx.exception))

    def test_unidentifiable_source_is_refused(self):
        self.be.dataset_sources["otherDataset123"] = None
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(runner.fetch_datasets(["ownDataset123", "otherDataset123"], []))
        self.assertIn("Could not tell which Actor", str(ctx.exception))
        self.assertIn("Nothing was imported", str(ctx.exception))

    def test_lookalike_owner_is_refused(self):
        self.be.dataset_sources["otherDataset123"] = "khadinakbar-evil/x"
        with self.assertRaises(ValueError):
            asyncio.run(runner.fetch_datasets(["otherDataset123"], []))


if __name__ == "__main__":
    unittest.main()


class AuditFixes(unittest.TestCase):
    def test_zero_requests_still_quotes_the_request_fee(self):
        base = tools.quote_cost([{"job": "keyword_ideas", "units": 100, "requests": 1}])
        zero = tools.quote_cost([{"job": "keyword_ideas", "units": 100, "requests": 0}])
        self.assertEqual(zero["suggested_cap_usd"], base["suggested_cap_usd"])

    def test_gate_sees_a_send_with_a_recipient_under_any_name(self):
        import approval_gate as gate
        body = {"to": "a@example.com", "subject": "hi", "body": "text"}
        for name in ("send", "gmail_send", "gmail_users_messages_send", "email_send", "send_bulk",
                     "check_and_send_email", "compose_and_send"):
            self.assertEqual(gate.classify(f"mcp__mail__{name}", body), "send", name)

    def test_gate_leaves_a_send_without_a_recipient_alone(self):
        import approval_gate as gate
        self.assertIsNone(gate.classify("mcp__chat__send", {"text": "hello"}))
        self.assertIsNone(gate.classify("mcp__mail__list_messages", {"to": "a@example.com"}))
