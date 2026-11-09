"""schedule_checks plans a round that the next measurement accepts without warnings.

The AI Brand Monitor Actor has no repeat setting and takes at most 20 questions per platform per run, so repeats are
the same run added to the schedule several times and a long question list is split into runs of at most 20.
Google AI Overviews and Google AI Mode give one answer per search, so they run once. The cost uses the worst-case
numbers of quote_cost, and the site comes from the saved project when the user does not type it.
"""
import asyncio
import importlib.util
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import history as hist  # noqa: E402
import runner  # noqa: E402
import storage as stg  # noqa: E402
import tools  # noqa: E402

HAVE = all(importlib.util.find_spec(m) for m in ("mcp", "pydantic"))
MONITOR, AIO, MODE = ("khadinakbar/ai-search-brand-monitor", "khadinakbar/google-ai-overviews-scraper",
                      "khadinakbar/google-ai-mode-scraper")
ASSISTANTS = ["perplexity", "chatgpt", "gemini"]
BRAND = {"name": "Fixturely", "domain": "fixturely.example", "competitors": ["Rival One", "Rival Two"]}
PER_MONTH = {"daily": 30, "weekly": 4.33, "monthly": 1}

# 30 questions like the ai_check pack: 20 buying, 5 control, 5 brand-name
PANEL = (
    [{"prompt_id": f"a{n:02d}", "prompt": f"best invoicing tool for freelancers number {n}", "type": "awareness"}
     for n in range(1, 11)]
    + [{"prompt_id": f"c{n:02d}", "prompt": f"which invoicing app should a small studio pick {n}", "type": "consideration"}
       for n in range(1, 11)]
    + [{"prompt_id": f"x{n:02d}", "prompt": f"how do I bake sourdough bread {n}", "type": "control"} for n in range(1, 6)]
    + [{"prompt_id": f"b{n:02d}", "prompt": f"is Fixturely any good {n}", "type": "brand"} for n in range(1, 6)]
)
BUYING = [p["prompt"] for p in PANEL if p["type"] in ("awareness", "consideration")]
ALL = [p["prompt"] for p in PANEL]
FIVE_ENGINES = ASSISTANTS + ["google-aio", "google-aimode"]


def plan_for(panel=PANEL, **kwargs):
    url = kwargs.pop("url", "https://fixturely.example")
    frequency = kwargs.pop("frequency", "monthly")
    return tools.schedule_plan("fixturely-site", url, frequency, panel=panel, brand=BRAND, **kwargs)


def entries(plan, job):
    return [e for e in plan["ai_checks"]["runs"] if e["job"] == job]


def cost_of(job, units):
    quote = tools.quote_cost([{"job": job, "units": units, "requests": 1}])
    return quote["total_usd"], quote["suggested_cap_usd"]


class AssistantRunTests(unittest.TestCase):
    def test_repeats_default_to_three_and_the_same_run_is_added_that_many_times(self):
        ai = plan_for()["ai_checks"]
        self.assertEqual(ai["repeats"], 3)
        monitor = [e for e in ai["runs"] if e["actor"] == MONITOR]
        self.assertTrue(monitor)
        for entry in monitor:
            self.assertEqual(entry["times"], 3)
            self.assertEqual(entry["input"]["platforms"], ASSISTANTS)
            self.assertEqual(entry["input"]["querySelectionMode"], "custom_only")
            self.assertNotIn("repeats", entry["input"])  # the Actor has no such setting: the run is added several times

    def test_a_long_question_list_is_split_into_runs_the_actor_accepts(self):
        monitor = entries(plan_for(), "ai_brand_check")
        self.assertEqual(len(monitor), 2)  # 30 questions: the Actor takes at most 20 per platform per run
        sizes = [len(e["input"]["customQueries"]) for e in monitor]
        self.assertEqual(sizes, [15, 15])
        for entry in monitor:
            self.assertLessEqual(len(entry["input"]["customQueries"]), 20)
            self.assertEqual(entry["input"]["maxQueriesPerPlatform"], len(entry["input"]["customQueries"]))
            self.assertEqual(entry["checks_per_run"], len(entry["input"]["customQueries"]) * 3)
        self.assertEqual([q for e in monitor for q in e["input"]["customQueries"]], ALL)  # exact text, in order

    def test_twenty_questions_or_fewer_stay_in_one_run(self):
        monitor = entries(plan_for(PANEL[:20]), "ai_brand_check")
        self.assertEqual(len(monitor), 1)
        self.assertEqual(monitor[0]["input"]["maxQueriesPerPlatform"], 20)

    def test_brand_details_are_passed_to_the_actor(self):
        entry = entries(plan_for(), "ai_brand_check")[0]
        self.assertEqual(entry["input"]["brandName"], "Fixturely")
        self.assertEqual(entry["input"]["brandDomain"], "fixturely.example")
        self.assertEqual(entry["input"]["competitors"], ["Rival One", "Rival Two"])

    def test_aliases_are_passed_when_the_project_has_them(self):
        plan = tools.schedule_plan("p", "acme.com", "monthly", panel=PANEL[:6],
                                   brand={"name": "Acme", "aliases": ["AcmePay"]})
        self.assertEqual(entries(plan, "ai_brand_check")[0]["input"]["brandAliases"], ["AcmePay"])

    def test_repeats_can_be_changed_from_one_to_five(self):
        for repeats in (1, 2, 5):
            ai = plan_for(repeats=repeats)["ai_checks"]
            self.assertEqual(ai["repeats"], repeats)
            self.assertTrue(all(e["times"] == repeats for e in ai["runs"] if e["actor"] == MONITOR))

    def test_repeats_outside_one_to_five_are_refused_in_plain_words(self):
        for bad in (0, 6, -1, 2.5, "3", True):
            with self.assertRaises(ValueError, msg=repr(bad)) as caught:
                plan_for(repeats=bad)
            self.assertIn("repeats", str(caught.exception))
            self.assertIn("1 to 5", str(caught.exception))


class SingleAnswerRunTests(unittest.TestCase):
    def test_google_ai_overviews_is_planned_once_for_the_buying_questions(self):
        (entry,) = entries(plan_for(), "ai_overview")
        self.assertEqual(entry["actor"], AIO)
        self.assertEqual(entry["times"], 1)  # one answer per search: no repeats
        self.assertEqual(entry["input"]["queries"], BUYING)
        self.assertEqual(entry["checks_per_run"], len(BUYING))
        self.assertEqual(entry["input"]["targetDomain"], "fixturely.example")
        self.assertEqual({k: entry["input"][k] for k in ("countryCode", "languageCode", "device")},
                         {"countryCode": "us", "languageCode": "en", "device": "desktop"})

    def test_google_ai_mode_is_planned_once_when_asked_for(self):
        plan = plan_for(platforms=FIVE_ENGINES)
        (entry,) = entries(plan, "ai_mode")
        self.assertEqual(entry["actor"], MODE)
        self.assertEqual(entry["times"], 1)
        self.assertEqual(entry["input"]["queries"], BUYING)
        self.assertEqual({k: entry["input"][k] for k in ("countryCode", "languageCode", "device")},
                         {"countryCode": "us", "languageCode": "en", "device": "desktop"})
        self.assertEqual(entries(plan, "ai_overview")[0]["input"]["queries"], BUYING)

    def test_without_a_choice_the_engines_are_the_ones_the_ai_check_pack_buys(self):
        ai = plan_for()["ai_checks"]
        self.assertEqual(ai["engines"], ASSISTANTS + ["google-aio"])
        self.assertEqual(entries(plan_for(), "ai_mode"), [])

    def test_the_checks_in_a_round_add_up(self):
        ai = plan_for()["ai_checks"]
        self.assertEqual(ai["checks_per_round"], 30 * 3 * 3 + 20)  # the same 290 answers the pack buys
        five = plan_for(platforms=FIVE_ENGINES)["ai_checks"]
        self.assertEqual(five["checks_per_round"], 290 + 20)

    def test_a_panel_without_types_is_sent_to_the_google_engines_whole(self):
        panel = [{"prompt_id": "p1", "prompt": "first question"}, {"prompt_id": "p2", "prompt": "second question"}]
        plan = tools.schedule_plan("p", "acme.com", "monthly", panel=panel, brand={"name": "Acme"})
        self.assertEqual(entries(plan, "ai_overview")[0]["input"]["queries"], ["first question", "second question"])

    def test_no_aio_target_domain_when_the_brand_has_no_domain(self):
        plan = tools.schedule_plan("p", "acme.com", "monthly", panel=PANEL[:6], brand={"name": "Acme"})
        self.assertNotIn("targetDomain", entries(plan, "ai_overview")[0]["input"])


class EngineChoiceTests(unittest.TestCase):
    def test_platform_names_are_checked_with_the_valid_ones_listed(self):
        with self.assertRaises(ValueError) as caught:
            plan_for(platforms=["bing"])
        message = str(caught.exception)
        for name in FIVE_ENGINES + ["claude"]:
            self.assertIn(name, message)
        self.assertNotIn("Traceback", message)

    def test_other_spellings_of_the_google_engines_are_understood(self):
        ai = plan_for(platforms=["ChatGPT", "google-ai-overviews", "Google_AI_Mode", "chatgpt"])["ai_checks"]
        self.assertEqual(ai["engines"], ["chatgpt", "google-aio", "google-aimode"])

    def test_claude_is_an_assistant(self):
        entry = entries(plan_for(platforms=["claude", "chatgpt"]), "ai_brand_check")[0]
        self.assertEqual(entry["input"]["platforms"], ["claude", "chatgpt"])

    def test_google_only_plans_have_no_assistant_runs(self):
        plan = plan_for(platforms=["google-aio"])
        self.assertEqual(entries(plan, "ai_brand_check"), [])
        self.assertEqual(len(entries(plan, "ai_overview")), 1)

    def test_the_first_round_engines_are_followed_when_nothing_is_chosen(self):
        plan = plan_for(baseline_engines=["chatgpt", "gemini", "google-aimode", "perplexity"])
        self.assertEqual(plan["ai_checks"]["engines"], ["perplexity", "chatgpt", "gemini", "google-aimode"])

    def test_an_explicit_choice_beats_the_first_round(self):
        plan = plan_for(platforms=["chatgpt"], baseline_engines=FIVE_ENGINES)
        self.assertEqual(plan["ai_checks"]["engines"], ["chatgpt"])

    def test_engines_that_cannot_be_planned_are_named_and_left_out(self):
        plan = plan_for(baseline_engines=["chatgpt", "copilot"])
        self.assertEqual(plan["ai_checks"]["engines"], ["chatgpt"])
        self.assertTrue(any("copilot" in note.lower() for note in plan["ai_checks"]["notes"]))


class CostTests(unittest.TestCase):
    def test_each_run_is_priced_with_quote_cost(self):
        for entry in plan_for(platforms=FIVE_ENGINES)["ai_checks"]["runs"]:
            total, cap = cost_of(entry["job"], entry["checks_per_run"])
            self.assertEqual(entry["cost_per_run_usd"], round(total, 4))
            self.assertEqual(entry["suggested_max_cost_usd"], cap)
            self.assertGreaterEqual(entry["suggested_max_cost_usd"], entry["cost_per_run_usd"])

    def test_the_overview_run_is_priced_at_the_worst_case_not_the_headline_price(self):
        (entry,) = entries(plan_for(), "ai_overview")
        self.assertGreaterEqual(entry["cost_per_run_usd"], 20 * 0.10)  # the $0.10 fallback every sampled run used

    def test_a_round_costs_every_run_times_how_often_it_is_added(self):
        ai = plan_for(platforms=FIVE_ENGINES)["ai_checks"]
        expected = sum(e["cost_per_run_usd"] * e["times"] for e in ai["runs"])
        self.assertAlmostEqual(ai["cost_per_round_usd"], expected, places=2)
        self.assertGreater(ai["cost_per_round_usd"], 23.6)  # at least what the ai_check pack quotes for a baseline

    def test_the_monthly_estimate_follows_the_frequency(self):
        for frequency, rounds in PER_MONTH.items():
            ai = plan_for(frequency=frequency)["ai_checks"]
            self.assertAlmostEqual(ai["estimated_cost_per_month_usd"], round(ai["cost_per_round_usd"] * rounds, 2), places=2)
            caps = sum(e["suggested_max_cost_usd"] * e["times"] for e in ai["runs"])
            self.assertAlmostEqual(ai["max_cost_per_month_usd"], round(caps * rounds, 2), places=2)
            self.assertGreaterEqual(ai["max_cost_per_month_usd"], ai["estimated_cost_per_month_usd"])

    def test_the_cost_note_says_worst_case_and_includes_the_amount(self):
        ai = plan_for(frequency="weekly")["ai_checks"]
        note = ai["cost_note"]
        self.assertIn(f"${ai['estimated_cost_per_month_usd']:,.2f}", note)
        self.assertIn("highest", note.lower())
        self.assertIn("running costs", note.lower())
        self.assertIn(tools.PRICES["read_on"], note)

    def test_more_repeats_cost_more(self):
        cheap, dear = plan_for(repeats=1)["ai_checks"], plan_for(repeats=5)["ai_checks"]
        self.assertLess(cheap["cost_per_round_usd"], dear["cost_per_round_usd"])


class PlanTextTests(unittest.TestCase):
    def test_one_plain_line_tells_the_user_to_pass_country_language_and_device(self):
        steps = plan_for()["steps"]
        lines = [s for s in steps if "import_ai_results" in s and "context" in s]
        self.assertEqual(len(lines), 1, steps)
        for word in ("country", "language", "device", "AI Mode"):
            self.assertIn(word, lines[0])
        for value in ("us", "en", "desktop"):
            self.assertIn(value, lines[0])

    def test_the_context_values_are_in_the_plan_as_data_too(self):
        context = plan_for()["ai_checks"]["import_context"]
        self.assertEqual(context, {"country": "us", "language": "en", "device": "desktop"})

    def test_the_steps_tell_the_user_to_add_repeated_runs_that_many_times(self):
        text = " ".join(plan_for(repeats=4)["steps"])
        self.assertIn("4 times", text)

    def test_the_site_only_plan_has_no_ai_steps_and_no_context_line(self):
        plan = tools.schedule_plan("acme-site", "acme.com", "weekly")
        self.assertIsNone(plan["ai_checks"])
        self.assertFalse([s for s in plan["steps"] if "import_ai_results" in s])
        self.assertIn("question list", plan["note"])

    def test_the_import_hint_says_to_import_all_runs_of_a_round_together(self):
        self.assertIn("together", plan_for()["ai_checks"]["after_it_runs"])


class SiteAddressTests(unittest.TestCase):
    def test_url_is_optional_when_the_brand_has_a_site(self):
        plan = tools.schedule_plan("p", None, "weekly", panel=PANEL, brand={**BRAND, "site": "https://www.fixturely.example"})
        self.assertEqual(plan["free_site_check"]["input"]["arguments"]["url"], "https://www.fixturely.example")

    def test_the_saved_site_wins_over_the_domain_and_the_domain_is_the_fallback(self):
        both = tools.schedule_plan("p", "", brand={**BRAND, "site": "https://www.fixturely.example"})
        self.assertEqual(both["free_site_check"]["input"]["arguments"]["url"], "https://www.fixturely.example")
        only_domain = tools.schedule_plan("p", None, brand=BRAND)
        self.assertEqual(only_domain["free_site_check"]["input"]["arguments"]["url"], "https://fixturely.example")

    def test_a_typed_url_always_wins(self):
        plan = tools.schedule_plan("p", "other.example", brand={**BRAND, "site": "https://www.fixturely.example"})
        self.assertEqual(plan["free_site_check"]["input"]["arguments"]["url"], "https://other.example")

    def test_neither_gives_a_plain_error(self):
        for brand in (None, {"name": "Acme"}):
            with self.assertRaises(ValueError) as caught:
                tools.schedule_plan("p", None, brand=brand)
            message = str(caught.exception)
            self.assertIn("website address", message)
            self.assertNotIn("Traceback", message)


def run(coro):
    return asyncio.run(coro)


def rows(snapshot, platforms, repeats):
    out = []
    for p in PANEL:
        for platform in platforms:
            reps = 1 if platform.startswith("google") else repeats
            for r in range(1, reps + 1):
                out.append({"snapshot": snapshot, "prompt_id": p["prompt_id"], "platform": platform, "repeat": r,
                            "recommended": False})
    return out


class SavedProjectTests(unittest.TestCase):
    def setUp(self):
        self.backend = stg.MemoryBackend()
        stg.set_backend(self.backend)
        self.addCleanup(stg.set_backend, None)

    def save(self, brand=BRAND, platforms=("chatgpt", "perplexity", "gemini", "google-aio")):
        run(hist.save_results("fixturely-site", rows("baseline", platforms, 3), PANEL, brand=brand))

    def test_url_comes_from_the_saved_domain_when_omitted(self):
        self.save()
        plan = run(runner.run_tool("schedule_checks", {"project": "fixturely-site"}))
        self.assertEqual(plan["free_site_check"]["input"]["arguments"]["url"], "https://fixturely.example")

    def test_url_comes_from_the_saved_site_check_when_there_is_one(self):
        self.save()
        run(hist.save_audit("fixturely-site", {"site": "https://www.fixturely.example", "health_score": 70,
                                               "subscores": {}, "counts": {}, "pages_checked": 3, "problems": []}))
        plan = run(runner.run_tool("schedule_checks", {"project": "fixturely-site"}))
        self.assertEqual(plan["free_site_check"]["input"]["arguments"]["url"], "https://www.fixturely.example")

    def test_no_url_and_no_saved_site_is_a_plain_error(self):
        self.save(brand={"name": "Fixturely"})
        with self.assertRaises(ValueError) as caught:
            run(runner.run_tool("schedule_checks", {"project": "fixturely-site"}))
        self.assertIn("website address", str(caught.exception))
        with self.assertRaises(ValueError) as unknown:
            run(runner.run_tool("schedule_checks", {"project": "never-saved"}))
        self.assertIn("website address", str(unknown.exception))

    def test_the_engines_of_the_first_round_are_followed(self):
        self.save(platforms=("chatgpt", "perplexity", "gemini", "google-aio", "google-aimode"))
        plan = run(runner.run_tool("schedule_checks", {"project": "fixturely-site"}))
        self.assertEqual(plan["ai_checks"]["engines"], ASSISTANTS + ["google-aio", "google-aimode"])

    def test_a_project_with_assistants_only_gets_no_google_runs(self):
        self.save(platforms=("chatgpt", "perplexity", "gemini"))
        plan = run(runner.run_tool("schedule_checks", {"project": "fixturely-site"}))
        self.assertEqual([e["job"] for e in plan["ai_checks"]["runs"]], ["ai_brand_check"] * 2)

    def test_a_project_with_no_rounds_yet_uses_the_pack_engines(self):
        run(hist.save_results("fixturely-site", [], PANEL, brand=BRAND))
        plan = run(runner.run_tool("schedule_checks", {"project": "fixturely-site"}))
        self.assertEqual(plan["ai_checks"]["engines"], ASSISTANTS + ["google-aio"])

    def test_repeats_and_platforms_pass_through_the_runner(self):
        self.save()
        plan = run(runner.run_tool("schedule_checks", {"project": "fixturely-site", "repeats": 2,
                                                       "platforms": ["chatgpt"], "frequency": "weekly"}))
        self.assertEqual(plan["ai_checks"]["repeats"], 2)
        self.assertEqual(plan["ai_checks"]["engines"], ["chatgpt"])

    def test_bad_repeats_through_the_runner_is_a_plain_error(self):
        self.save()
        with self.assertRaises(ValueError) as caught:
            run(runner.run_tool("schedule_checks", {"project": "fixturely-site", "repeats": 9}))
        self.assertIn("1 to 5", str(caught.exception))

    def test_the_plan_is_json_ready(self):
        self.save()
        json.dumps(run(runner.run_tool("schedule_checks", {"project": "fixturely-site"})))


@unittest.skipUnless(HAVE, "mcp and pydantic are not installed")
class ServedToolTests(unittest.TestCase):
    def setUp(self):
        import server
        self.mcp = server.build_server()

    def schema(self):
        tool = next(t for t in run(self.mcp.list_tools()) if t.name == "schedule_checks")
        return tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema

    def test_only_the_project_is_required(self):
        self.assertEqual(self.schema()["required"], ["project"])

    def test_repeats_is_a_bounded_whole_number_with_a_default_of_three(self):
        repeats = self.schema()["properties"]["repeats"]
        self.assertEqual((repeats["type"], repeats["minimum"], repeats["maximum"], repeats["default"]),
                         ("integer", 1, 5, 3))
        self.assertIn("assistants", repeats["description"])

    def test_url_says_it_defaults_to_the_saved_site(self):
        url = self.schema()["properties"]["url"]
        self.assertIn("saved", url["description"].lower())

    def test_runner_accepts_exactly_the_served_arguments(self):
        self.assertEqual(set(self.schema()["properties"]), runner.ALLOWED_ARGS["schedule_checks"])
        self.assertIn("repeats", runner.ALLOWED_ARGS["schedule_checks"])


if __name__ == "__main__":
    unittest.main()
