"""Saved projects: history, trends, frozen question list, reports, importer, schedule plans, runner routing."""
import asyncio
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import history as hist  # noqa: E402
import importer  # noqa: E402
import report  # noqa: E402
import runner  # noqa: E402
import storage as stg  # noqa: E402
import tools  # noqa: E402

PANEL = [{"prompt_id": f"p{i}", "prompt": f"question {i}", "type": t}
         for i, t in enumerate(["awareness", "awareness", "consideration", "consideration", "control", "control"], 1)]
AUDIT = {"site": "https://acme.com", "health_score": 70, "subscores": {"technical": 70}, "counts": {"fail": 1},
         "pages_checked": 5, "problems": [{"check": "Sitemap", "detail": "missing"}]}


def runs(snapshot, rec_ids, repeats=3, platform="chatgpt"):
    return [{"snapshot": snapshot, "prompt_id": p["prompt_id"], "platform": platform, "repeat": r,
             "recommended": p["prompt_id"] in rec_ids} for p in PANEL for r in range(1, repeats + 1)]


def run(coro):
    return asyncio.run(coro)


class Base(unittest.TestCase):
    def setUp(self):
        self.backend = stg.MemoryBackend()
        stg.set_backend(self.backend)

    def tearDown(self):
        stg.set_backend(None)


class BrandAliasTests(Base):
    PANEL = [{"prompt_id": "p1", "prompt": "is AcmePay good for invoices", "type": "consideration"}] + PANEL[1:]

    def save(self, brand):
        return run(hist.save_results("acme-site", [dict(r, prompt_id=r["prompt_id"]) for r in runs("baseline", {"p2"})],
                                     self.PANEL, brand=brand))

    def test_aliases_are_saved_with_the_project(self):
        self.save({"name": "Acme", "aliases": ["AcmePay", "Acme Pay"]})
        meta = run(hist.history("acme-site"))["brand"]
        self.assertEqual(meta["aliases"], ["AcmePay", "Acme Pay"])

    def test_saved_aliases_trigger_the_brand_name_warning(self):
        result = self.save({"name": "Acme", "aliases": ["AcmePay"]})
        self.assertTrue(any("p1" in w or "name" in w.lower() for w in result["warnings"]), result["warnings"])

    def test_without_aliases_the_alias_question_is_not_flagged(self):
        result = self.save({"name": "Acme"})
        self.assertEqual(result["warnings"], [])

    def test_alias_list_is_bounded_and_cleaned(self):
        self.save({"name": "Acme", "aliases": [f"alias{i}" for i in range(50)] + [None]})
        meta = run(hist.history("acme-site"))["brand"]
        self.assertLessEqual(len(meta["aliases"]), 20)


class SlugTests(unittest.TestCase):
    def test_clean_slug_accepts_normal_names(self):
        self.assertEqual(stg.clean_slug("Acme Site!"), "acme-site")

    def test_clean_slug_rejects_short_and_long(self):
        for bad in ("a", "", "x" * 41, "!!!"):
            with self.assertRaises(ValueError):
                stg.clean_slug(bad)

    def test_clean_part_blocks_dots_so_keys_stay_unambiguous(self):
        self.assertNotIn(".", stg.clean_part("2026.12.01"))


class SaveAndLoad(Base):
    def test_first_save_needs_panel(self):
        with self.assertRaises(ValueError) as e:
            run(hist.save_results("acme-site", runs("baseline", {"p1"})))
        self.assertIn("question list", str(e.exception))

    def test_save_then_history_shows_both_rounds(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL, brand={"name": "Acme", "domain": "acme.com"}))
        run(hist.save_results("acme-site", runs("2026-12", {"p1", "p2", "p3"})))
        h = run(hist.history("acme-site"))
        self.assertEqual([s["snapshot"] for s in h["snapshots"]], ["baseline", "2026-12"])
        self.assertGreater(h["snapshots"][1]["recommendation_share"], h["snapshots"][0]["recommendation_share"])
        self.assertEqual(h["brand"]["name"], "Acme")
        self.assertIn("| baseline |", h["markdown"])

    def test_duplicate_snapshot_refused_unless_replace_or_append(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        with self.assertRaises(ValueError) as e:
            run(hist.save_results("acme-site", runs("baseline", {"p2"})))
        self.assertIn("append=true", str(e.exception))
        out = run(hist.save_results("acme-site", runs("baseline", {"p2"}), replace=True))
        self.assertEqual(out["snapshots_saved"]["baseline"], 18)

    def test_append_renumbers_repeats(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        out = run(hist.save_results("acme-site", runs("baseline", {"p1"}, repeats=2), append=True))
        self.assertEqual(out["snapshots_saved"]["baseline"], 30)
        data = run(hist.load_project("acme-site"))
        self.assertEqual(sorted(r["repeat"] for r in data["runs"] if r["prompt_id"] == "p1"), [1, 2, 3, 4, 5])

    def test_changed_panel_is_refused(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        changed = [dict(p) for p in PANEL]
        changed[0]["prompt"] = "a different question"
        with self.assertRaises(ValueError) as e:
            run(hist.save_results("acme-site", runs("2026-12", {"p1"}), changed))
        self.assertIn("frozen", str(e.exception))

    def test_unknown_project_names_known_ones(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        with self.assertRaises(ValueError) as e:
            run(hist.history("other-site"))
        self.assertIn("acme-site", str(e.exception))

    def test_project_limit(self):
        with mock.patch.object(stg, "MAX_PROJECTS", 1):
            run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
            with self.assertRaises(ValueError):
                run(hist.save_results("beta-site", runs("baseline", {"p1"}), PANEL))

    def test_experiments_are_saved_and_deduplicated(self):
        exp = [{"action": "Joined two lists", "mechanism": "listicle", "target_prompt_ids": "p1", "date": "2026-11-01"}]
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL, experiments=exp))
        run(hist.save_results("acme-site", runs("2026-12", {"p1", "p2"}), experiments=exp))
        self.assertEqual(len(run(hist.load_project("acme-site"))["experiments"]), 1)

    def test_measure_project_uses_saved_rounds(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        run(hist.save_results("acme-site", runs("2026-12", {"p1", "p2", "p3"})))
        rep = run(hist.measure_project("acme-site"))
        self.assertEqual((rep["baseline"], rep["current"]), ("baseline", "2026-12"))

    def test_projects_do_not_see_each_other(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        run(hist.save_results("beta-site", runs("baseline", {"p2"}), PANEL))
        self.assertEqual(run(hist.list_projects()), ["acme-site", "beta-site"])
        self.assertEqual(len(run(hist.load_project("beta-site"))["runs"]), 18)


class ReviewFixes(Base):
    def test_a_failed_multi_round_save_writes_nothing(self):
        run(hist.save_results("acme-site", runs("old", {"p1"}), PANEL))
        mixed = runs("fresh", {"p1"}) + runs("old", {"p2"})
        with self.assertRaises(ValueError) as e:
            run(hist.save_results("acme-site", mixed))
        self.assertIn("Nothing was saved", str(e.exception))
        self.assertEqual(sorted(run(hist.load_project("acme-site"))["meta"]["snapshots"]), ["old"])

    def test_rounds_are_found_even_if_meta_lost_them(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        run(hist.save_results("acme-site", runs("later", {"p1"})))
        meta = self.backend.data["p.acme-site.meta"]
        meta["snapshots"].pop("later")
        self.assertEqual(len(run(hist.history("acme-site"))["snapshots"]), 2)

    def test_round_names_that_clean_to_the_same_name_are_not_double_counted(self):
        with self.assertRaises(ValueError):
            run(hist.save_results("acme-site", runs("2026 12", {"p1"}) + runs("2026-12", {"p1"}), PANEL))

    def test_appending_keeps_the_original_round_date_and_order(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        run(hist.save_results("acme-site", runs("later", {"p1"})))
        with mock.patch.object(hist, "today", return_value="2099-01-01"):
            run(hist.save_results("acme-site", runs("baseline", {"p1"}, repeats=1), append=True))
        order = [s["snapshot"] for s in run(hist.history("acme-site"))["snapshots"]]
        self.assertEqual(order, ["baseline", "later"])

    def test_bad_audit_is_refused_before_anything_is_written(self):
        for bad in ({"health_score": "abc"}, {"health_score": 500}, {"health_score": True}, "text", None):
            with self.assertRaises(ValueError):
                run(hist.save_audit("acme-site", bad))
        self.assertEqual(self.backend.data, {})

    def test_odd_audit_fields_are_coerced_so_reports_still_work(self):
        weird = {"health_score": 50, "problems": ["x", {"check": "A", "detail": "d" * 5000}], "subscores": "no", "counts": {"fail": "many"}}
        run(hist.save_audit("acme-site", weird))
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        run(report.make_report("acme-site"))  # must not raise
        saved = run(hist.load_project("acme-site"))["audits"][0]
        self.assertEqual(len(saved["problems"]), 1)
        self.assertLessEqual(len(saved["problems"][0]["detail"]), hist.MAX_TEXT)

    def test_old_audits_are_pruned(self):
        with mock.patch.object(hist, "MAX_AUDITS", 3):
            for day in range(1, 7):
                with mock.patch.object(hist, "today", return_value=f"2099-01-0{day}"):
                    run(hist.save_audit("acme-site", AUDIT))
        self.assertEqual([a["date"] for a in run(hist.load_project("acme-site"))["audits"]],
                         ["2099-01-04", "2099-01-05", "2099-01-06"])

    def test_experiments_need_an_action_and_do_not_truncate_silently(self):
        with self.assertRaises(ValueError):
            run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL, experiments=[{"mechanism": "other"}]))
        self.assertEqual(self.backend.data, {})
        with self.assertRaises(ValueError):
            run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL,
                                  experiments=[{"action": str(i)} for i in range(tools.MAX_EXPERIMENTS + 1)]))

    def test_unknown_keys_are_not_stored(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL, brand={"name": "Acme", "evil": "x" * 9999},
                              experiments=[{"action": "a", "junk": "z"}]))
        data = run(hist.load_project("acme-site"))
        self.assertEqual(data["meta"]["brand"], {"name": "Acme"})
        self.assertNotIn("junk", data["experiments"][0])

    def test_two_saves_at_once_do_not_lose_a_round(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))

        async def both():
            await asyncio.gather(hist.save_results("acme-site", runs("one", {"p1"})),
                                 hist.save_results("acme-site", runs("two", {"p1"})))
        run(both())
        self.assertEqual(sorted(run(hist.load_project("acme-site"))["meta"]["snapshots"]), ["baseline", "one", "two"])

    def test_string_booleans_are_refused(self):
        with self.assertRaises(ValueError):
            run(runner.run_tool("save_results", {"project": "acme-site", "audit": AUDIT, "replace": "false"}))

    def test_report_note_is_honest_without_a_link(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        out = run(report.make_report("acme-site"))  # memory backend cannot make links
        self.assertIsNone(out["share_url"])
        self.assertIn("No share link", out["note"])

    def test_storage_refuses_to_fall_back_to_memory_by_accident(self):
        stg.set_backend(None)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CITEBASE_ALLOW_MEMORY", None)
            os.environ.pop("APIFY_IS_AT_HOME", None)
            with self.assertRaises(ValueError):
                run(stg.get_backend())


class AuditHistory(Base):
    def test_second_audit_on_a_later_day_reports_trend(self):
        run(hist.save_audit("acme-site", AUDIT))
        with mock.patch.object(hist, "today", return_value="2099-01-01"):
            out = run(hist.save_audit("acme-site", {**AUDIT, "health_score": 80}))
        self.assertEqual(out["trend"]["change"], 10)

    def test_same_day_audit_overwrites_without_trend(self):
        run(hist.save_audit("acme-site", AUDIT))
        out = run(hist.save_audit("acme-site", {**AUDIT, "health_score": 75}))
        self.assertIsNone(out["trend"])
        self.assertEqual(len(run(hist.load_project("acme-site"))["audits"]), 1)

    def test_problem_list_is_capped(self):
        many = {**AUDIT, "problems": [{"check": str(i), "detail": "x"} for i in range(50)]}
        run(hist.save_audit("acme-site", many))
        self.assertEqual(len(run(hist.load_project("acme-site"))["audits"][0]["problems"]), hist.MAX_AUDIT_PROBLEMS)


class ReportTests(Base):
    def page(self, project="acme-site"):
        return self.backend.data[run(report.make_report(project))["stored_key"]]

    def test_report_escapes_html_in_brand_name(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL, brand={"name": "<script>alert(1)</script>"}))
        run(hist.save_audit("acme-site", AUDIT))
        page = self.page()
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("Website health", page)

    def test_report_with_two_rounds_has_trend_chart(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        run(hist.save_results("acme-site", runs("2026-12", {"p1", "p2"})))
        self.assertIn("<svg", self.page())

    def test_report_for_unknown_project_fails_plainly(self):
        with self.assertRaises(ValueError):
            run(report.make_report("nothing-here"))

    def test_report_page_has_no_scripts_or_external_files(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        page = self.page()
        for bad in ("<script", "http://", "https://", "<link", "<img"):
            self.assertNotIn(bad, page)

    def test_report_result_says_how_to_stop_sharing(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        out = run(report.make_report("acme-site"))
        self.assertIn("stop sharing", out["note"])


class ImporterTests(unittest.TestCase):
    ITEMS = [
        {"query": "Question 1", "platform": "perplexity", "brand_mentioned": True, "sentiment": "positive",
         "brand_mention_count": 2, "is_cited_as_source": True, "cited_urls": ["https://www.acme.com/a", "https://x.org/y"],
         "competitor_mentions": ["Rival"], "scraped_at": "2026-11-07T10:00:00Z"},
        {"query": "question  1", "platform": "perplexity", "brand_mentioned": True, "sentiment": "negative",
         "brand_mention_count": 1},
        {"query": "question 2", "platform": "google_ai_overviews", "brand_mentioned": False},
        {"query": "not in panel", "platform": "chatgpt", "brand_mentioned": True},
    ]

    def test_convert_maps_rows_and_flags(self):
        out = importer.convert(self.ITEMS, PANEL, "baseline")
        self.assertEqual(out["summary"]["rows"], 3)
        self.assertEqual(out["unmatched_queries"], ["not in panel"])
        first, second, third = out["runs"]
        self.assertTrue(first["recommended"])
        self.assertFalse(second["recommended"])  # negative wording is not a recommendation
        self.assertEqual((first["repeat"], second["repeat"]), (1, 2))
        self.assertEqual(third["platform"], "google-aio")
        self.assertEqual(first["cited_domains"], "acme.com;x.org")

    def test_convert_rejects_empty_and_unmatched(self):
        with self.assertRaises(ValueError):
            importer.convert([], PANEL, "baseline")
        with self.assertRaises(ValueError):
            importer.convert([{"query": "zzz", "platform": "chatgpt"}], PANEL, "baseline")

    def test_single_mention_goes_to_review(self):
        out = importer.convert(self.ITEMS, PANEL, "baseline")
        self.assertTrue(any(r["prompt_id"] == "p1" for r in out["needs_review"]))

    def test_importer_and_loop_agree_on_the_metric_version(self):
        self.assertEqual(importer.METRIC_VERSION, tools.cl.METRIC_VERSION)


class SchedulePlanTests(unittest.TestCase):
    def test_site_only_plan(self):
        plan = tools.schedule_plan("acme-site", "acme.com", "weekly")
        self.assertEqual(plan["cron"], "0 8 * * 1")
        self.assertIsNone(plan["ai_checks"])
        self.assertEqual(plan["free_site_check"]["input"]["arguments"]["url"], "https://acme.com")

    def test_ai_checks_cost_and_cap(self):
        plan = tools.schedule_plan("acme-site", "acme.com", "daily", panel=PANEL, brand={"name": "Acme"})
        ai = plan["ai_checks"]
        self.assertEqual(ai["repeats"], 3)
        monitor = [e for e in ai["runs"] if e["job"] == "ai_brand_check"]
        self.assertEqual(sum(e["checks_per_run"] for e in monitor), 18)  # 6 questions x 3 assistants, per repeat
        self.assertEqual(ai["checks_per_round"], 18 * 3 + 4)  # 3 repeats, plus one Google AI Overviews answer per buying question
        for entry in ai["runs"]:
            self.assertGreaterEqual(entry["suggested_max_cost_usd"], entry["cost_per_run_usd"])
        self.assertAlmostEqual(ai["estimated_cost_per_month_usd"], round(ai["cost_per_round_usd"] * 30, 2))

    def test_bad_frequency(self):
        with self.assertRaises(ValueError):
            tools.schedule_plan("acme-site", "acme.com", "hourly")

    def test_max_pages_is_capped(self):
        plan = tools.schedule_plan("acme-site", "acme.com", max_pages=500)
        self.assertEqual(plan["free_site_check"]["input"]["arguments"]["max_pages"], tools.MAX_AUDIT_PAGES)


class RunnerTests(Base):
    def test_unknown_tool_lists_names(self):
        with self.assertRaises(ValueError) as e:
            run(runner.run_tool("nope", {}))
        self.assertIn("save_results", str(e.exception))

    def test_extra_argument_refused(self):
        with self.assertRaises(ValueError):
            run(runner.run_tool("get_history", {"project": "acme-site", "bogus": 1}))

    def test_stateless_tool_still_works(self):
        out = run(runner.run_tool("quote_cost", {"items": [{"job": "serp_page", "units": 2}]}))
        self.assertGreater(out["total_usd"], 0)

    def test_measure_with_project_reads_saved_data(self):
        run(runner.run_tool("save_results", {"project": "acme-site", "panel": PANEL, "runs": runs("baseline", {"p1"})}))
        out = run(runner.run_tool("measure_recommendation_share", {"project": "acme-site"}))
        self.assertEqual(out["project"], "acme-site")

    def test_measure_with_project_refuses_new_data(self):
        with self.assertRaises(ValueError) as e:
            run(runner.run_tool("measure_recommendation_share",
                                {"project": "acme-site", "panel": PANEL, "runs": runs("baseline", {"p1"})}))
        self.assertIn("save_results", str(e.exception))
        self.assertEqual(run(hist.list_projects()), [])  # a read never writes

    def test_save_needs_runs_or_audit(self):
        with self.assertRaises(ValueError):
            run(runner.run_tool("save_results", {"project": "acme-site"}))

    def test_save_audit_only_creates_project(self):
        out = run(runner.run_tool("save_results", {"project": "acme-site", "audit": AUDIT}))
        self.assertEqual(out["snapshots_saved"], {})
        self.assertEqual(out["audit_saved"]["project"], "acme-site")
        try:
            import models  # needs pydantic, which the minimal CI job does not install
        except ImportError:
            return
        self.assertEqual(models.SaveResult(**out).audit_saved["project"], "acme-site")  # output model keeps the field
        self.assertEqual(len(run(hist.load_project("acme-site"))["audits"]), 1)

    def test_save_runs_and_audit_together(self):
        out = run(runner.run_tool("save_results", {"project": "acme-site", "panel": PANEL, "runs": runs("baseline", {"p1"}),
                                                   "audit": AUDIT}))
        self.assertIn("baseline", out["snapshots_saved"])
        self.assertIsNotNone(out["audit_saved"])

    def test_audit_site_takes_no_project(self):
        with self.assertRaises(ValueError):
            run(runner.run_tool("audit_site", {"url": "acme.com", "project": "acme-site"}))

    def test_import_and_save_through_runner(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL))
        items = [{"query": "question 1", "platform": "chatgpt", "brand_mentioned": True, "sentiment": "positive",
                  "brand_mention_count": 2}]
        out = run(runner.run_tool("import_ai_results", {"project": "acme-site", "items": items, "snapshot": "2026-12",
                                                        "save": True}))
        self.assertIn("2026-12", out["saved"]["snapshots_saved"])

    def test_schedule_uses_saved_panel_and_brand(self):
        run(hist.save_results("acme-site", runs("baseline", {"p1"}), PANEL, brand={"name": "Acme", "domain": "acme.com"}))
        plan = run(runner.run_tool("schedule_checks", {"project": "acme-site", "url": "acme.com"}))
        self.assertEqual(plan["ai_checks"]["runs"][0]["input"]["brandName"], "Acme")

    def test_scheduled_check_saves_audit_and_report(self):
        fake = {"site": "https://acme.com", "health_score": 66, "subscores": {}, "counts": {}, "pages_checked": 3,
                "problems": [{"check": "Sitemap", "detail": "missing", "level": "fail", "area": "technical", "example_urls": []}],
                "passed": [], "limits": ""}
        with mock.patch.object(tools, "run_audit", return_value=fake):
            out = run(runner.run_tool("scheduled_check", {"project": "acme-site", "url": "acme.com"}))
        self.assertEqual(out["health_score"], 66)
        self.assertEqual(out["top_problems"], ["Sitemap"])
        self.assertTrue(any(k.endswith("report.html") for k in self.backend.data))


if __name__ == "__main__":
    unittest.main()
