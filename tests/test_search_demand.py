import asyncio
import os
import unittest

os.environ["CITEBASE_ALLOW_MEMORY"] = "1"
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "connector"))
import runner  # noqa: E402
import search_demand as sd  # noqa: E402
import storage as stg  # noqa: E402

CSV = """Top queries,Clicks,Impressions,CTR,Position
best payroll software for small business,3,900,0.3%,14.2
acme payroll login,120,300,40%,1.1
how to run payroll in the uk,10,400,2.5%,6.0
payroll,5,5000,0.1%,30
acme pricing,8,50,16%,2.0
what is the cheapest payroll tool for startups,0,60,0%,22.5
"""


class SearchDemandTests(unittest.TestCase):
    def setUp(self):
        stg.set_backend(stg.MemoryBackend())

    def test_summary_finds_gaps_and_test_questions(self):
        out = sd.summarise_search_demand(sd.parse_gsc_csv(CSV), ("acme",))
        self.assertEqual(out["kind"], "queries")
        self.assertEqual(out["impressions"], 6710)
        self.assertEqual(out["gaps"][0]["query"], "best payroll software for small business")
        self.assertIn("what is the cheapest payroll tool for startups", out["test_in_ai"])
        self.assertTrue(all("acme" not in q for q in out["test_in_ai"]))
        self.assertTrue(any("Google searches only" in f for f in out["findings"]))

    def test_without_brand_says_so(self):
        out = sd.summarise_search_demand(sd.parse_gsc_csv(CSV))
        self.assertTrue(any("brand name was not known" in f for f in out["findings"]))

    def test_pages_tab_is_recognised(self):
        out = sd.summarise_search_demand(sd.parse_gsc_csv("Top pages,Clicks,Impressions,CTR,Position\nhttps://a.com/x?y=1,4,100,4%,9\n"))
        self.assertEqual(out["kind"], "pages")
        self.assertNotIn("?", out["top_pages"][0]["page"])

    def test_no_known_columns_is_refused(self):
        with self.assertRaises(ValueError):
            sd.summarise_search_demand(sd.parse_gsc_csv("a,b\n1,2\n"))
        with self.assertRaises(ValueError):
            sd.parse_gsc_csv("")

    def test_save_keeps_summary_not_rows_and_history_shows_it(self):
        out = asyncio.run(runner.save("acme-site", None, None, None, {"name": "Acme", "domain": "acme.com"}, None, gsc_csv=CSV))
        self.assertEqual(out["search_demand"]["gaps"][0]["impressions"], 900)
        self.assertNotIn("rows", out["search_demand"])
        h = asyncio.run(runner.run_tool("get_history", {"project": "acme-site"}))
        self.assertEqual(h["search_demand"]["impressions"], 6710)
        self.assertIn("Search Console export", h["markdown"])
        again = asyncio.run(runner.save("acme-site", None, None, None, None, None, gsc_csv=CSV))
        self.assertIsNotNone(again["search_demand"]["previous"] or again["search_demand"])

    def test_check_only_stores_nothing(self):
        out = asyncio.run(runner.save("acme-site", None, None, None, {"name": "Acme"}, None, check_only=True, gsc_csv=CSV))
        self.assertTrue(out["checked_only"])
        self.assertIsNotNone(out["search_demand"])
        self.assertEqual(asyncio.run(stg.get_backend()).data, {})


if __name__ == "__main__":
    unittest.main()
