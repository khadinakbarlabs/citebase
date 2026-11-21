"""Product context, context-based buyer questions, question edits and the SEO plan."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))
import storage
import work_onboarding as onboarding
import work_plan

PAGES = [
    {"url": "https://shop.example.co.uk/", "title": "Shop | Handmade boots", "h1": ["Handmade leather boots"],
     "h2": ["Boots for hikers and farmers"], "description": "Handmade leather boots for small businesses across the UK."},
    {"url": "https://shop.example.co.uk/trade", "title": "Trade accounts", "h1": ["Workwear for contractors"], "h2": [],
     "description": ""},
]


class ProfileTests(unittest.TestCase):
    def test_profile_names_summary_buyer_groups_and_markets_with_sources(self):
        profile = onboarding.profile(PAGES, {"settings": {"country": "Ireland"}}, "https://shop.example.co.uk/")
        self.assertEqual(profile["summary"], "Handmade leather boots for small businesses across the UK.")
        self.assertEqual(profile["summary_url"], "https://shop.example.co.uk/")
        names = [a["name"] for a in profile["audiences"]]
        self.assertIn("small businesses", names)
        self.assertIn("contractors", names)
        self.assertTrue(all(a["url"].startswith("https://shop.example.co.uk/") for a in profile["audiences"]))
        markets = {m["name"]: m["source"] for m in profile["markets"]}
        self.assertEqual(markets, {"UK": "website", "Ireland": "project", "United Kingdom": "domain"})

    def test_profile_is_empty_but_valid_without_pages(self):
        profile = onboarding.profile([], {}, "")
        self.assertEqual(profile, {"summary": "", "summary_url": None, "audiences": [], "markets": [], "language": "en"})

    def test_question_ideas_use_context_and_never_name_the_brand(self):
        context = {"audiences": [{"name": "small businesses"}], "markets": [{"name": "United States"}]}
        ideas = onboarding.question_ideas(["payroll software"], ["Gusto"], context)
        prompts = [q["prompt"] for q in ideas]
        self.assertIn("What is the best payroll software in the United States?", prompts)
        self.assertIn("Which payroll software would you recommend for small businesses?", prompts)
        self.assertIn("How do I choose the right payroll software?", prompts)
        self.assertIn("What are the best alternatives to Gusto?", prompts)
        self.assertTrue(all(q["type"] in ("awareness", "consideration") for q in ideas))
        self.assertEqual(len({q["prompt_id"] for q in ideas}), len(ideas))

    def test_question_ideas_without_market_or_audience(self):
        prompts = [q["prompt"] for q in onboarding.question_ideas(["boots"], [], {})]
        self.assertEqual(prompts, ["What is the best boots?", "How do I choose the right boots?"])


class EditQuestionTests(unittest.TestCase):
    base = [{"prompt": "Which boots last longest?", "prompt_id": "a", "type": "consideration", "topic": "boots"},
            {"prompt": "Best boots for farmers?", "prompt_id": "b", "type": "consideration", "topic": "boots"}]

    def test_add_and_remove(self):
        result = onboarding.edit_questions(self.base, {"remove": ["a"], "add": ["Where can I buy work boots?",
                                                                               {"prompt": "Is Shop any good?", "type": "brand"}]})
        self.assertEqual([q["prompt_id"] for q in result][0], "b")
        self.assertEqual([q["prompt"] for q in result][1:], ["Where can I buy work boots?", "Is Shop any good?"])
        self.assertEqual(result[2]["type"], "brand")

    def test_duplicates_are_ignored_and_bad_input_is_refused(self):
        self.assertEqual(onboarding.edit_questions(self.base, {"add": ["which boots last longest?"]}), self.base)
        for bad in ({"remove": ["missing"]}, {"add": ["short"]}, {}, {"remove": ["a", "b"]},
                    {"add": [{"prompt": "A valid question here?", "type": "other"}]}, {"add": ["x" * 9], "extra": 1}):
            with self.assertRaises(ValueError, msg=bad):
                onboarding.edit_questions(self.base, bad)


class QuestionsUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = storage.MemoryBackend()
        storage.set_backend(self.backend)
        self.addCleanup(storage.set_backend, None)
        await self.backend.set(storage.key("shop", "meta"), {"brand": {"name": "Shop", "domain": "shop.example"}})

    async def test_edits_before_the_baseline_become_the_baseline(self):
        state = await onboarding.execute("shop", "questions_update", {"revision": 0, "add": ["Where can I buy work boots?"]})
        self.assertEqual([q["prompt"] for q in state["questions"]], ["Where can I buy work boots?"])
        self.assertIsNone(await self.backend.get(storage.key("shop", "panel")))
        await onboarding.execute("shop", "onboarding_save", {"revision": 1, "step": "competitors", "competitors": []})
        ready = await onboarding.execute("shop", "onboarding_save", {"revision": 2, "step": "terms", "terms": ["boots"]})
        self.assertEqual([q["prompt"] for q in ready["questions"]], ["Where can I buy work boots?"])
        self.assertEqual(await self.backend.get(storage.key("shop", "panel")), ready["questions"])

    async def test_edits_after_the_baseline_update_the_live_list_and_retry_safely(self):
        panel = [{"prompt": "Which boots last longest?", "prompt_id": "a", "type": "consideration", "topic": "boots"},
                 {"prompt": "Best boots for farmers?", "prompt_id": "b", "type": "consideration", "topic": "boots"}]
        await self.backend.set(storage.key("shop", "panel"), panel)
        data = {"revision": 0, "remove": ["a"], "add": ["Where can I buy work boots?"]}
        first = await onboarding.execute("shop", "questions_update", data)
        live = await self.backend.get(storage.key("shop", "panel"))
        self.assertEqual([q["prompt_id"] for q in live][0], "b")
        self.assertEqual(live, first["questions"])
        # A repeated request with the same revision returns the same result instead of failing.
        self.assertEqual((await onboarding.execute("shop", "questions_update", data))["questions"], live)
        # A stale revision is refused.
        with self.assertRaises(ValueError):
            await onboarding.execute("shop", "questions_update", {"revision": 0, "add": ["Another question here?"]})


class SeoPlanTests(unittest.TestCase):
    def data(self, audits=(), runs=(), panel=()):
        return {"slug": "shop", "audits": list(audits), "runs": list(runs), "panel": list(panel),
                "meta": {"brand": {"name": "Shop"}, "snapshots": {}}}

    def test_empty_project_explains_what_is_missing(self):
        plan = work_plan.build("shop", self.data(), None)
        areas = {s["area"]: s for s in plan["sections"]}
        self.assertEqual(list(areas), ["on_page", "off_page", "technical"])
        self.assertEqual(areas["technical"]["missing_evidence"], "Run the site audit to find these.")
        self.assertEqual(areas["off_page"]["missing_evidence"], "Run an AI check to see which sites answers cite.")
        self.assertTrue(all(s["guidelines"] and s["items"] == [] for s in plan["sections"]))

    def test_audit_findings_split_into_on_page_and_technical_by_priority(self):
        audit = {"date": "2026-11-20", "problems": [
            {"check": "Unique meta descriptions", "area": "on-page", "level": "warn", "detail": "3 pages share one.",
             "example_urls": ["https://shop.example/a"]},
            {"check": "robots.txt reachable", "area": "technical", "level": "fail", "detail": "Returns 500.",
             "example_urls": []},
            {"check": "Published / updated date on long content", "area": "ai-search", "level": "fail", "detail": "Missing.",
             "example_urls": []}]}
        plan = work_plan.build("shop", self.data(audits=[audit]),
                               {"date": "2026-11-18", "gaps": [{"query": "work boots", "impressions": 900}]})
        areas = {s["area"]: s for s in plan["sections"]}
        self.assertEqual([i["title"] for i in areas["technical"]["items"]], ["robots.txt reachable"])
        self.assertEqual(areas["technical"]["items"][0]["priority"], "high")
        on_page = [i["title"] for i in areas["on_page"]["items"]]
        self.assertEqual(on_page[0], "Published / updated date on long content")
        self.assertIn("Unique meta descriptions", on_page)
        self.assertIn("Improve the result for “work boots”", on_page)
        self.assertEqual(areas["on_page"]["items"][1]["pages"], ["https://shop.example/a"])
        self.assertEqual(plan["sources"]["audit_date"], "2026-11-20")
        self.assertEqual(len({i["id"] for s in plan["sections"] for i in s["items"]}),
                         sum(len(s["items"]) for s in plan["sections"]))


if __name__ == "__main__":
    unittest.main()
