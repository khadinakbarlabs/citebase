"""The price table in references/tools-and-apis.md must say the same as connector/prices.json.

The table is what the Claude Code plugin quotes from; prices.json is what the connector's quote_cost uses. If they
drift apart a user is quoted two different prices for the same job. This test reads the table and checks every
priced job against it (and every table row whose Actor is priced against the job list).
"""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "references", "tools-and-apis.md")
PRICES = os.path.join(ROOT, "connector", "prices.json")
REQUEST_UNITS = {"request", "run"}  # a fee charged once per run, not per result


def load_prices() -> dict:
    with open(PRICES, encoding="utf-8") as fh:
        return json.load(fh)


def table_rows() -> list[list[str]]:
    with open(REF, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## Jobs"))
    rows = []
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        if ln.startswith("|") and not set(ln) <= set("|- "):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if cells[0] != "Job":
                rows.append(cells)
    return rows


def parse_price(cell: str) -> dict:
    """Primary Actor's own price: the part of the cell before the first ' · ' or '(' note, as per_unit/per_request."""
    head = re.split(r"\s·\s|\s\(", cell.replace("**", ""), maxsplit=1)[0]
    out = {"per_unit": 0.0, "per_request": 0.0}
    for amount, unit in re.findall(r"\$([\d.]+)\s*(?:/|per)\s*([a-z]+)", head):
        key = "per_request" if unit in REQUEST_UNITS else "per_unit"
        if not out[key]:
            out[key] = float(amount)
    return out


def parse_rows() -> list[dict]:
    parsed = []
    for cells in table_rows():
        actor = re.search(r"`(khadinakbar/[a-z0-9-]+)`", cells[1])
        if not actor:
            continue
        parsed.append({"job": cells[0], "actor": actor.group(1), **parse_price(cells[3])})
        # a fallback Actor that states its own price in brackets, like `owner/name` ($0.03 / snapshot)
        for name, price in re.findall(r"`(khadinakbar/[a-z0-9-]+)`[^()|]*\((\$[^)]*)\)", cells[2]):
            parsed.append({"job": f"{cells[0]} (fallback)", "actor": name, **parse_price(price)})
    return parsed


class PriceTableParsing(unittest.TestCase):
    def test_the_table_is_found_and_parsed(self):
        rows = parse_rows()
        self.assertGreater(len(rows), 30)
        by_job = {r["job"]: r for r in rows}
        keyword_ideas = by_job["Keyword ideas"]
        self.assertEqual((keyword_ideas["per_request"], keyword_ideas["per_unit"]), (0.20, 0.01))
        serp = by_job["SERP (organic, PAA, features)"]
        self.assertEqual((serp["per_request"], serp["per_unit"]), (0.0, 0.0018))

    def test_run_fee_is_a_request_fee(self):
        self.assertEqual(parse_price("$0.02 / run + $0.005 / brief"), {"per_unit": 0.005, "per_request": 0.02})

    def test_fallback_and_note_prices_are_ignored(self):
        self.assertEqual(parse_price("$0.0018 / page · fallback $0.003 (browser)")["per_unit"], 0.0018)
        self.assertEqual(parse_price("$0.015 / query (+ $0.005 when matched)")["per_unit"], 0.015)


class PricesMatchTheDocs(unittest.TestCase):
    def setUp(self):
        self.rows = parse_rows()
        self.prices = load_prices()

    def test_every_priced_job_is_in_the_table_with_the_same_price(self):
        for job, spec in self.prices["jobs"].items():
            rows = [r for r in self.rows if r["actor"] == spec["actor"]]
            self.assertTrue(rows, f"{job}: Actor {spec['actor']} is not a primary Actor in the table")
            wanted = (spec["per_unit"], spec["per_request"])
            found = [(r["per_unit"], r["per_request"]) for r in rows]
            self.assertIn(wanted, found, f"{job}: prices.json says {wanted}, the table says {found}")

    def test_every_table_row_for_a_priced_actor_matches_a_job(self):
        priced_actors = {spec["actor"] for spec in self.prices["jobs"].values()}
        for row in self.rows:
            if row["actor"] not in priced_actors:
                continue
            candidates = [(s["per_unit"], s["per_request"]) for s in self.prices["jobs"].values()
                          if s["actor"] == row["actor"]]
            self.assertIn((row["per_unit"], row["per_request"]), candidates,
                          f"{row['job']}: table price does not match any prices.json job for {row['actor']}")

    def test_the_doc_says_the_start_fee_prices_json_uses(self):
        with open(REF, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(self.prices["start_fee_usd"], 0.00005)
        self.assertIn("$0.00005", text)


def read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class DocNumbersFollowTheQuote(unittest.TestCase):
    """Every pack total written in the docs is the total quote_cost gives today, so a price change cannot leave old numbers behind."""

    @classmethod
    def setUpClass(cls):
        import datetime as dt
        sys.path.insert(0, os.path.join(ROOT, "connector"))
        import tools
        cls.tools = tools
        cls.totals = {name: f"${tools.quote_cost(None, name, dt.date(2026, 11, 8))['total_usd']:.2f}"
                      for name in tools.PRICES["packs"]}

    def test_reference_pack_line(self):
        text = read("references", "tools-and-apis.md")
        for name, amount in self.totals.items():
            self.assertIn(f"`{name}` (about {amount})", text, name)

    def test_store_page_pack_table(self):
        text = read(".actor", "ACTOR_README.md")
        for name, amount in self.totals.items():
            row = next((ln for ln in text.splitlines() if ln.startswith(f"| `{name}` |")), None)
            self.assertIsNotNone(row, name)
            self.assertTrue(row.rstrip().endswith(f"| {amount} |"), f"{name}: {row} should end with {amount}")

    def test_the_ai_check_baseline_is_the_same_everywhere(self):
        amount = self.totals["ai_check"]
        for parts in (("README.md",), (".actor", "ACTOR_README.md"), ("references", "tools-and-apis.md"),
                      ("skills", "start", "SKILL.md"), ("docs", "competitor-scorecard.md")):
            self.assertIn(amount, read(*parts), "/".join(parts))

    def test_the_quick_audit_is_the_starter_pack_everywhere(self):
        amount = self.totals["starter"]
        for parts in (("README.md",), (".actor", "ACTOR_README.md"), ("references", "tools-and-apis.md"),
                      ("skills", "start", "SKILL.md")):
            self.assertIn(amount, read(*parts), "/".join(parts))

    def test_the_date_the_prices_were_read_matches_the_docs(self):
        read_on = self.tools.PRICES["read_on"]
        for parts in (("README.md",), (".actor", "ACTOR_README.md"), ("references", "tools-and-apis.md")):
            self.assertIn(read_on, read(*parts), "/".join(parts))
            self.assertNotIn("2026-11-07", read(*parts), "/".join(parts))

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
        self.assertEqual(self.tools.CAP_MULTIPLIER, 1.3)
        for parts in (("README.md",), (".actor", "ACTOR_README.md"), ("references", "tools-and-apis.md"),
                      ("skills", "start", "SKILL.md")):
            self.assertNotRegex(read(*parts), r"(?i)\b20 ?(%|percent)\s+(above|more|over|on top)", "/".join(parts))

    def test_jobs_that_cannot_run_yet_say_so_in_the_docs(self):
        dated = {spec["effective_from"] for spec in load_prices()["jobs"].values() if "effective_from" in spec}
        for stamp in dated:
            self.assertIn(stamp, read("references", "tools-and-apis.md"))
            self.assertIn(stamp, read(".actor", "ACTOR_README.md"))


if __name__ == "__main__":
    unittest.main()
