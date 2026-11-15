"""The guided journey: amounts are never volunteered, every result ends with a next step, recurring checks are
offered with a clear yes and a way to stop, and the first AI check is built from the saved project."""
import asyncio
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import history as hist  # noqa: E402
import runner  # noqa: E402
import storage as stg  # noqa: E402
import tools  # noqa: E402

AMOUNT = re.compile(r"[$€£]\s?\d|\b\d+(\.\d+)?\s?(usd|dollars?)\b", re.I)
TYPES = ["awareness"] * 10 + ["consideration"] * 10 + ["control"] * 5 + ["brand"] * 5
PANEL = [{"prompt_id": f"p{i:03d}", "prompt": f"question number {i}", "type": t} for i, t in enumerate(TYPES, 1)]
BRAND = {"name": "Acme", "domain": "acme.com", "site": "https://acme.com", "competitors": ["Rival"]}
AUDIT = {"site": "https://acme.com", "health_score": 70, "subscores": {}, "counts": {}, "pages_checked": 3,
         "status": "ok", "problems": [{"level": "fail", "area": "technical", "check": "XML sitemap", "detail": "none"}],
         "passed": []}


def run(coro):
    return asyncio.run(coro)


def rows(snapshot, repeats=3):
    return [{"snapshot": snapshot, "prompt_id": p["prompt_id"], "platform": "chatgpt", "repeat": r,
             "recommended": p["prompt_id"] in ("p001", "p002")} for p in PANEL for r in range(1, repeats + 1)]


class Base(unittest.TestCase):
    def setUp(self):
        self.backend = stg.MemoryBackend()
        stg.set_backend(self.backend)

    def tearDown(self):
        stg.set_backend(None)


# ---------------------------------------------------------------- amounts are never volunteered
class NoVolunteeredAmountsTests(Base):
    def assert_no_amount(self, text, where):
        found = AMOUNT.search(text or "")
        self.assertIsNone(found, f"{where} states an amount: {found.group(0) if found else ''!r}")

    def test_the_server_instructions_carry_the_rule_and_no_amount(self):
        import server
        self.assertIn(tools.PRICE_RULE, server.INSTRUCTIONS)
        self.assert_no_amount(server.INSTRUCTIONS, "INSTRUCTIONS")

    def test_the_web_note_and_the_journey_state_no_amount(self):
        self.assertIn(tools.PRICE_RULE, tools.WEB_NOTE)
        self.assert_no_amount(tools.WEB_NOTE, "WEB_NOTE")
        for step in tools.JOURNEY:
            self.assert_no_amount(step["do"], f"journey step {step['step']}")

    def test_tool_descriptions_state_no_amount(self):
        import server
        for name, (_title, description) in server.TOOL_TEXT.items():
            self.assert_no_amount(description, name)

    def test_next_steps_state_no_amount(self):
        for out in (tools.next_steps(), tools.next_steps(AUDIT), tools.next_steps(AUDIT, None, 10)):
            self.assert_no_amount(out["tip"], "tip")
            for step in out["steps"]:
                self.assert_no_amount(step["step"] + " " + step["why"], step["step"])

    def test_saved_results_and_history_hints_state_no_amount(self):
        saved = run(runner.save("acme-site", rows("baseline"), PANEL, None, BRAND, None))
        measured = run(runner.measure("acme-site", None, None))
        listing = run(hist.history(None))
        one = run(hist.history("acme-site"))
        for name, text in (("save", saved["next"]), ("measure", measured["next"]), ("list", listing["next"]),
                           ("history", one["next"])):
            self.assert_no_amount(text, name)

    def test_the_schedule_plan_talks_about_paid_runs_without_amounts_in_its_guidance(self):
        run(hist.save_results("acme-site", rows("baseline"), PANEL, brand=BRAND))
        plan = run(runner.schedule("acme-site"))
        for key in ("before_you_set_it_up", "how_to_stop", "who_creates_it", "next"):
            self.assert_no_amount(plan[key], key)
        for step in plan["steps"]:
            self.assert_no_amount(step, "step")
        self.assertIn("amounts only if they ask", plan["before_you_set_it_up"])

    def test_no_text_field_of_a_quote_or_a_plan_carries_an_amount(self):
        run(hist.save_results("acme-site", rows("baseline"), PANEL, brand=BRAND))
        plan = run(runner.schedule("acme-site"))
        for q in (tools.quote_cost(pack="ai_check"), tools.quote_cost(pack="starter"),
                  run(runner.quote(None, "ai_check_pilot", "acme-site"))):
            for key in ("how_to_run", "compute_note", "heads_up", "pack_about", "after_the_runs"):
                text = re.sub(r"maxTotalChargeUsd = [\d.]+", "", q.get(key) or "")  # the cap setting is not a price
                self.assert_no_amount(text, key)
                self.assertIsNone(re.search(r"\b\d+\.\d{2}\b", text), f"{key} carries a bare amount: {text}")
            for warning in q["warnings"]:
                self.assert_no_amount(warning, "warning")
        ai = plan["ai_checks"]
        for text in (ai["cost_note"], ai["after_it_runs"], *ai["notes"]):
            self.assert_no_amount(text, "ai_checks")
            self.assertIsNone(re.search(r"\b\d+\.\d{2}\b", text), text)

    def test_the_price_is_still_there_for_a_user_who_asks(self):
        q = tools.quote_cost(pack="ai_check")
        self.assertGreater(q["total_usd"], 0)
        self.assertIn("only if they ask", q["how_to_run"])
        self.assertIn("paid check", q["how_to_run"])

    def test_every_quote_says_to_ask_before_running(self):
        for q in (tools.quote_cost(pack="starter"), tools.quote_cost(pack="ai_check_pilot"),
                  tools.quote_cost([{"job": "serp_page", "units": 1}])):
            self.assertIn("wait for a yes", q["how_to_run"])


# ---------------------------------------------------------------- every result ends with a next step
class NextStepEverywhereTests(Base):
    def setUp(self):
        super().setUp()
        run(hist.save_results("acme-site", rows("baseline"), PANEL, brand=BRAND))
        run(hist.save_audit("acme-site", AUDIT))

    def test_report_schedule_history_and_import_all_say_what_to_do_next(self):
        self.assertTrue(run(runner.run_tool("make_report", {"project": "acme-site"}))["next"])
        self.assertTrue(run(runner.run_tool("schedule_checks", {"project": "acme-site"}))["next"])
        self.assertTrue(run(runner.run_tool("get_history", {"project": "acme-site"}))["next"])
        self.assertTrue(run(runner.run_tool("get_history", {}))["next"])

    def test_the_typed_results_declare_a_next_field(self):
        import models as m
        for model in (m.AuditResult, m.MeasureResult, m.SaveResult, m.HistoryResult, m.ReportLinkResult,
                      m.ImportResult, m.SchedulePlanResult, m.OutreachResult, m.AiContentResult):
            self.assertIn("next", model.model_fields, model.__name__)

    def test_a_saved_measurement_offers_one_fix_and_a_re_check(self):
        nxt = run(runner.measure("acme-site", None, None))["next"]
        self.assertIn("next_steps", nxt)
        self.assertIn("schedule_checks", nxt)

    def test_a_first_look_with_one_repeat_explains_how_to_reach_a_baseline(self):
        run(hist.save_results("pilot-site", rows("baseline", repeats=1), PANEL, brand=BRAND))
        nxt = run(runner.measure("pilot-site", None, None))["next"]
        self.assertIn("First look", nxt)
        self.assertIn("append=true", nxt)
        self.assertIn("nothing is paid twice", nxt)

    def test_the_report_offers_a_monthly_re_check(self):
        self.assertIn("schedule_checks", run(runner.make_report("acme-site"))["next"])

    def test_a_saved_site_check_offers_the_ai_check_and_a_re_check(self):
        from unittest import mock
        result = {**AUDIT, "headline": "h", "limits": "l", "next": "n", "counts": {"fail": 1, "warn": 0, "pass": 0}}
        with mock.patch.object(tools, "run_audit", return_value=result):
            nxt = run(runner.audit("https://acme.com", 3, "acme-site"))["next"]
        self.assertIn("paid AI recommend check", nxt)
        self.assertIn("schedule_checks", nxt)


# ---------------------------------------------------------------- the journey does not stop at measuring
class JourneyTests(unittest.TestCase):
    def test_the_journey_goes_on_to_one_fix_a_log_and_a_re_check(self):
        steps = tools.get_playbook()["journey"]
        self.assertEqual([s["step"] for s in steps], [1, 2, 3, 4, 5, 6, 7])
        text = " ".join(s["do"] for s in steps)
        for needle in ("audit_site", "next_steps", "ai_check_pilot", "import_ai_results", "measure_recommendation_share",
                       "ONE fix", "save_results", "schedule_checks"):
            self.assertIn(needle, text, needle)

    def test_the_closing_step_mentions_the_monthly_setup(self):
        last = tools.next_steps(AUDIT)["steps"][-1]
        self.assertEqual(last["step"], "Check again in 30 days")
        self.assertIn("schedule_checks", last["why"])


# ---------------------------------------------------------------- recurring checks: consent, who, how to stop
class RecurringCheckRulesTests(Base):
    def plan(self, **kw):
        run(hist.save_results("acme-site", rows("baseline"), PANEL, brand=BRAND))
        return run(runner.schedule("acme-site", **kw))

    def test_the_plan_requires_a_clear_yes_and_says_the_checks_are_paid(self):
        text = self.plan()["before_you_set_it_up"]
        self.assertIn("clear yes", text)
        self.assertIn("paid runs on their own Apify account", text)
        self.assertIn("max cost", text)

    def test_the_plan_says_how_to_stop(self):
        text = self.plan()["how_to_stop"]
        self.assertIn("switch the schedule off", text)
        self.assertIn("Nothing runs after that", text)

    def test_citebase_never_creates_the_schedule_itself(self):
        text = self.plan()["who_creates_it"]
        self.assertIn("The user creates the schedule", text)
        self.assertIn("Citebase itself never creates schedules", text)
        self.assertIn("switched off", text)

    def test_every_planned_run_still_carries_its_own_max_cost(self):
        for entry in self.plan()["ai_checks"]["runs"]:
            self.assertGreater(entry["suggested_max_cost_usd"], 0)

    def test_the_wording_carries_no_pressure(self):
        plan = self.plan()
        blob = " ".join([plan["before_you_set_it_up"], plan["how_to_stop"], plan["who_creates_it"], plan["next"],
                         tools.RECHECK_OFFER, *plan["steps"]]).lower()
        for word in ("hurry", "limited time", "act now", "don't miss", "last chance", "guarantee", "urgent"):
            self.assertNotIn(word, blob)


# ---------------------------------------------------------------- the first look, built from the project
class FirstLookPackTests(Base):
    def test_the_first_look_is_one_repeat_of_the_full_check(self):
        pilot, full = tools.quote_cost(pack="ai_check_pilot"), tools.quote_cost(pack="ai_check")
        by_job = {c["job"]: c for c in pilot["run_caps"]}
        self.assertEqual(by_job["ai_brand_check"]["runs"], 2)
        self.assertEqual(by_job["ai_brand_check"]["units_per_run"], 45)  # same batches as the full check
        self.assertEqual(by_job["ai_overview"]["units_per_run"], 20)
        self.assertLess(pilot["total_usd"], full["total_usd"] / 2)

    def test_three_first_looks_cost_about_one_full_check(self):
        pilot = next(ln for ln in tools.quote_cost(pack="ai_check_pilot")["lines"] if ln["job"] == "ai_brand_check")
        full = next(ln for ln in tools.quote_cost(pack="ai_check")["lines"] if ln["job"] == "ai_brand_check")
        self.assertAlmostEqual(3 * pilot["cost_usd"], full["cost_usd"], places=2)

    def test_a_quote_for_a_project_returns_the_exact_runs_to_start(self):
        run(hist.save_results("acme-site", [], PANEL, brand=BRAND))
        q = run(runner.run_tool("quote_cost", {"pack": "ai_check_pilot", "project": "acme-site"}))
        self.assertEqual(q["project"], "acme-site")
        monitor = [r for r in q["ready_runs"] if r["actor"].endswith("ai-search-brand-monitor")]
        self.assertEqual(len(monitor), 2)
        asked = [text for r in monitor for text in r["input"]["customQueries"]]
        self.assertEqual(asked, [p["prompt"] for p in PANEL])  # the saved questions, word for word
        self.assertEqual(monitor[0]["input"]["brandName"], "Acme")
        self.assertTrue(all(r["times"] == 1 and r["max_cost_per_run_usd"] > 0 for r in q["ready_runs"]))
        self.assertIn("dataset_ids", q["after_the_runs"])

    def test_the_full_check_for_a_project_asks_each_question_three_times(self):
        run(hist.save_results("acme-site", [], PANEL, brand=BRAND))
        q = run(runner.quote(None, "ai_check", "acme-site"))
        monitor = [r for r in q["ready_runs"] if r["actor"].endswith("ai-search-brand-monitor")]
        self.assertTrue(all(r["times"] == 3 for r in monitor))
        self.assertAlmostEqual(q["total_usd"], tools.quote_cost(pack="ai_check")["total_usd"], delta=0.05)

    def test_after_a_first_look_the_full_check_only_adds_the_missing_repeats(self):
        run(hist.save_results("acme-site", rows("baseline", repeats=1), PANEL, brand=BRAND))
        q = run(runner.quote(None, "ai_check", "acme-site"))
        self.assertTrue(all(r["times"] == 2 for r in q["ready_runs"]), q["ready_runs"])
        self.assertFalse(any("overviews" in r["actor"] for r in q["ready_runs"]))
        fresh = tools.quote_cost(pack="ai_check")["total_usd"]
        self.assertLess(q["total_usd"], fresh * 0.7)  # two of three repeats, and no Google runs
        self.assertIn("round name 'baseline' and append=true", q["after_the_runs"])
        self.assertTrue(any("Nothing already saved is bought again" in w for w in q["warnings"]))

    def test_a_finished_baseline_gets_a_whole_new_round(self):
        run(hist.save_results("acme-site", rows("baseline", repeats=3), PANEL, brand=BRAND))
        q = run(runner.quote(None, "ai_check", "acme-site"))
        self.assertTrue(all(r["times"] == 3 for r in q["ready_runs"]))
        self.assertIn("one new round name", q["after_the_runs"])

    def test_the_caps_in_ready_runs_are_the_caps_of_the_quote(self):
        run(hist.save_results("acme-site", [], PANEL, brand=BRAND))
        for pack_name in ("ai_check_pilot", "ai_check"):
            q = run(runner.quote(None, pack_name, "acme-site"))
            self.assertEqual([r["max_cost_per_run_usd"] for r in q["ready_runs"]],
                             [c["max_cost_per_run_usd"] for c in q["run_caps"]])
            self.assertEqual([r["times"] for r in q["ready_runs"]], [c["runs"] for c in q["run_caps"]])

    def test_a_long_question_list_is_split_into_runs_that_cover_every_question_once(self):
        long_panel = PANEL + [{"prompt_id": f"x{i:03d}", "prompt": f"extra question {i}", "type": "awareness"}
                              for i in range(25)]
        run(hist.save_results("big-site", [], long_panel, brand=BRAND))
        q = run(runner.quote(None, "ai_check_pilot", "big-site"))
        monitor = [r for r in q["ready_runs"] if r["actor"].endswith("ai-search-brand-monitor")]
        asked = [text for r in monitor for text in r["input"]["customQueries"]]
        self.assertEqual(sorted(asked), sorted(p["prompt"] for p in long_panel))
        self.assertTrue(all(len(r["input"]["customQueries"]) <= tools.MONITOR_MAX_QUERIES for r in monitor))
        self.assertIn("55 saved questions", q["pack_about"])

    def test_a_project_measured_on_other_engines_is_described_as_it_is(self):
        only_chatgpt = [dict(r, platform="chatgpt") for r in rows("baseline", repeats=3)]
        run(hist.save_results("acme-site", only_chatgpt, PANEL, brand=BRAND))
        q = run(runner.quote(None, "ai_check", "acme-site"))
        self.assertIn("ChatGPT", q["pack_about"])
        self.assertNotIn("Perplexity", q["pack_about"])
        self.assertEqual({p for r in q["ready_runs"] for p in r["input"].get("platforms", [])}, {"chatgpt"})

    def test_a_first_look_hint_needs_exactly_one_repeat(self):
        run(hist.save_results("two-site", rows("baseline", repeats=2), PANEL, brand=BRAND))
        self.assertNotIn("First look", run(runner.measure("two-site", None, None))["next"])

    def test_the_quote_uses_the_projects_saved_country(self):
        run(hist.save_results("acme-site", [], PANEL, brand=BRAND, settings={"country": "gb"}))
        q = run(runner.quote(None, "ai_check_pilot", "acme-site"))
        google = next(r for r in q["ready_runs"] if "overviews" in r["actor"])
        self.assertEqual(google["input"]["countryCode"], "gb")

    def test_a_project_without_questions_is_told_what_to_save_first(self):
        run(hist.save_results("acme-site", [], brand=BRAND))
        with self.assertRaises(ValueError) as caught:
            run(runner.quote(None, "ai_check_pilot", "acme-site"))
        self.assertIn("question list", str(caught.exception))

    def test_project_with_another_pack_is_refused_in_plain_words(self):
        run(hist.save_results("acme-site", [], PANEL, brand=BRAND))
        with self.assertRaises(ValueError) as caught:
            run(runner.quote(None, "starter", "acme-site"))
        self.assertIn("ai_check", str(caught.exception))

    def test_without_a_project_the_quote_is_unchanged(self):
        q = run(runner.run_tool("quote_cost", {"pack": "starter", "project": ""}))
        self.assertEqual(q["pack"], "starter")
        self.assertNotIn("ready_runs", q)


if __name__ == "__main__":
    unittest.main()
