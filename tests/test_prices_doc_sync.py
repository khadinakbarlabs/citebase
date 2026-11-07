"""The price table in references/tools-and-apis.md must say the same as connector/prices.json.

The table is what the Claude Code plugin quotes from; prices.json is what the connector's quote_cost uses. If they
drift apart a user is quoted two different prices for the same job. This test reads the table and checks every
priced job against it (and every table row whose Actor is priced against the job list).
"""
import json
import os
import re
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


if __name__ == "__main__":
    unittest.main()
