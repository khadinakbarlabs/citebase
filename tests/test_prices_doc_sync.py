"""No document states a price (owner rule 2026-11-14, extended 2026-11-15).

Prices live in one place: connector/prices.json, which quote_cost reads. The Store page, README.md, the playbooks,
the agent prompts and references/tools-and-apis.md carry no amounts; the assistant gets a number from quote_cost only
when the user asks what a task costs. The only dollar figures allowed in documents are the two spending-limit
defaults (`daily_spend_usd` and `max_run_usd`), which are settings, not prices.
"""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "references", "tools-and-apis.md")
AMOUNT = re.compile(r"[$€£]\s?\d")
SETTING_DEFAULTS = ("`daily_spend_usd` (default $40)", "`max_run_usd` (default $2)")


def read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def without_setting_defaults(text: str) -> str:
    for phrase in SETTING_DEFAULTS:
        text = text.replace(phrase, "")
    return text


def load_prices() -> dict:
    return json.loads(read("connector", "prices.json"))


class NoDocumentStatesAPrice(unittest.TestCase):
    def test_store_page_and_readme_state_no_amounts(self):
        for parts in ((".actor", "ACTOR_README.md"), ("README.md",)):
            self.assertIsNone(AMOUNT.search(read(*parts)), "/".join(parts))
        self.assertIn("Each job is priced before it runs", read(".actor", "ACTOR_README.md"))

    def test_playbooks_agents_and_references_state_no_amounts(self):
        for rel in ("skills", "agents", "references"):
            for base, _dirs, names in os.walk(os.path.join(ROOT, rel)):
                for name in sorted(names):
                    if not name.endswith(".md"):
                        continue
                    path = os.path.relpath(os.path.join(base, name), ROOT)
                    found = AMOUNT.search(without_setting_defaults(read(path)))
                    self.assertIsNone(found, f"{path} states an amount: {found.group(0) if found else ''}")

    def test_the_reference_says_where_numbers_come_from(self):
        text = read("references", "tools-and-apis.md")
        self.assertIn("This file holds no prices", text)
        self.assertIn("quote_cost", text)
        self.assertNotIn("Price (USD)", text)


class EveryPricedJobIsListed(unittest.TestCase):
    """quote_cost can price a job only if the reference tells the assistant which Actor runs it."""

    def test_every_priced_actor_is_named_in_the_reference_and_the_store_page(self):
        reference, store = read("references", "tools-and-apis.md"), read(".actor", "ACTOR_README.md")
        for job, spec in load_prices()["jobs"].items():
            slug = spec["actor"].split("/")[1]
            self.assertIn(spec["actor"], reference, f"{job}: {spec['actor']} missing from the reference")
            self.assertIn(f"https://apify.com/khadinakbar/{slug})", store, f"{job}: not linked on the Store page")

    def test_the_date_stamps_of_jobs_that_cannot_run_yet_are_in_the_reference(self):
        for spec in load_prices()["jobs"].values():
            if "effective_from" in spec:
                self.assertIn(spec["effective_from"], read("references", "tools-and-apis.md"))


class WordingStaysHonest(unittest.TestCase):
    def test_no_doc_calls_the_extra_charges_tiny_or_small_platform_charges(self):
        for parts in (("README.md",), (".actor", "ACTOR_README.md"), ("references", "tools-and-apis.md"),
                      ("connector", "tools.py"), ("connector", "models.py")):
            text = read(*parts).lower()
            self.assertNotIn("tiny start fee", text, "/".join(parts))
            self.assertNotIn("small platform charges", text, "/".join(parts))
            self.assertNotIn("platform usage separately", text, "/".join(parts))

    def test_the_honest_compute_sentence_is_in_the_user_facing_docs(self):
        sentence = "Apify also bills a small amount of compute on some jobs; it is included in the quote."
        for parts in (("README.md",), (".actor", "ACTOR_README.md"), ("references", "tools-and-apis.md")):
            self.assertIn(sentence, read(*parts), "/".join(parts))

    def test_the_cap_is_described_as_thirty_percent_everywhere(self):
        sys.path.insert(0, os.path.join(ROOT, "connector"))
        import tools
        self.assertEqual(tools.CAP_MULTIPLIER, 1.3)
        for parts in (("README.md",), (".actor", "ACTOR_README.md"), ("references", "tools-and-apis.md"),
                      ("skills", "start", "SKILL.md")):
            self.assertNotRegex(read(*parts), r"(?i)\b20 ?(%|percent)\s+(above|more|over|on top)", "/".join(parts))


if __name__ == "__main__":
    unittest.main()
