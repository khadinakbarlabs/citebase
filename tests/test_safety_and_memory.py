"""Money safety and project memory: per-run spending caps, the 'start once' rule, no double counting, no score for
a site that could not be read, and everything a returning user needs without retyping (project list, saved site
checks with what changed, settings, to-dos, import by dataset id, misspelt project names)."""
import asyncio
import datetime as dt
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import history as hist  # noqa: E402
import runner  # noqa: E402
import site_audit as sa  # noqa: E402
import storage as stg  # noqa: E402
import tools  # noqa: E402

PANEL = [{"prompt_id": f"p{i}", "prompt": f"question {i}", "type": t}
         for i, t in enumerate(["awareness", "awareness", "consideration", "consideration", "control", "control"], 1)]
BRAND = {"name": "Acme", "domain": "acme.com"}


def run(coro):
    return asyncio.run(coro)


def rows(snapshot, stamp=None, repeat=1, country=None):
    out = []
    for p in PANEL:
        row = {"snapshot": snapshot, "prompt_id": p["prompt_id"], "platform": "chatgpt", "repeat": repeat,
               "recommended": p["prompt_id"] == "p1"}
        if stamp:
            row["answered_at"] = stamp
        if country:
            row["country"] = country
        out.append(row)
    return out


def monitor_items(stamp="2026-11-06T10:00:00Z"):
    """AI Brand Monitor dataset items for the panel: one per question on one engine."""
    return [{"query": p["prompt"], "platform": "chatgpt", "brand_mentioned": p["prompt_id"] == "p1",
             "sentiment": "positive" if p["prompt_id"] == "p1" else "", "brand_mention_count": 1,
             "is_cited_as_source": False, "cited_urls": [], "scraped_at": stamp} for p in PANEL]


def audit_result(problems, passed=(), score=70, status="ok"):
    return {"site": "https://acme.com", "pages_checked": 5, "health_score": score, "subscores": {"technical": score},
            "counts": {"fail": len(problems), "warn": 0, "pass": len(passed)}, "status": status,
            "headline": f"https://acme.com scores {score} out of 100.",
            "problems": [{"level": "fail", "area": "technical", "check": c, "detail": "d", "example_urls": []}
                         for c in problems],
            "passed": list(passed), "limits": "limits", "next": "next"}


class Base(unittest.TestCase):
    def setUp(self):
        self.backend = stg.MemoryBackend()
        stg.set_backend(self.backend)

    def tearDown(self):
        stg.set_backend(None)


# ---------------------------------------------------------------- spending caps and the start-once rule
class RunCapTests(unittest.TestCase):
    def test_the_ai_check_pack_gives_a_cap_for_each_run_not_one_cap_for_all(self):
        q = tools.quote_cost(pack="ai_check")
        monitor = next(c for c in q["run_caps"] if c["job"] == "ai_brand_check")
        self.assertEqual(monitor["runs"], 6)  # 30 questions in two batches, three repeats
        self.assertEqual(monitor["units_per_run"], 45)
        self.assertLess(monitor["max_cost_per_run_usd"], q["suggested_cap_usd"] / 4)

    def test_putting_every_run_at_its_cap_stays_close_to_the_total_cap(self):
        q = tools.quote_cost(pack="ai_check")
        every_run = sum(c["runs"] * c["max_cost_per_run_usd"] for c in q["run_caps"])
        self.assertGreaterEqual(every_run, q["total_usd"])  # the caps never block a run that costs what was quoted
        self.assertLess(every_run, q["suggested_cap_usd"] * 1.05)  # and they cannot add up to several times the quote

    def test_several_runs_are_told_to_use_the_per_run_cap(self):
        how = tools.quote_cost(pack="ai_check")["how_to_run"]
        self.assertIn("max_cost_per_run_usd", how)
        self.assertIn("Never put the whole total on one run", how)

    def test_a_single_run_keeps_the_simple_instruction(self):
        q = tools.quote_cost([{"job": "serp_page", "units": 15}])
        self.assertIn(f"maxTotalChargeUsd = {q['suggested_cap_usd']}", q["how_to_run"])
        self.assertEqual(q["run_caps"][0]["max_cost_per_run_usd"], q["suggested_cap_usd"])

    def test_a_job_split_over_requests_shares_its_cap(self):
        q = tools.quote_cost([{"job": "ai_brand_check", "units": 90, "requests": 3}])
        self.assertEqual(q["run_caps"][0]["runs"], 3)
        self.assertLess(q["run_caps"][0]["max_cost_per_run_usd"], q["suggested_cap_usd"])

    def test_a_job_that_cannot_run_yet_has_no_cap(self):
        future = dt.date(2000, 1, 1)
        q = tools.quote_cost([{"job": "keyword_ideas", "units": 10}], today=future)
        self.assertEqual(q["run_caps"], [])


class StartOnceRuleTests(unittest.TestCase):
    def test_every_quote_says_not_to_start_a_run_again(self):
        for q in (tools.quote_cost(pack="ai_check"), tools.quote_cost(pack="starter"),
                  tools.quote_cost([{"job": "serp_page", "units": 1}])):
            self.assertIn("do not start it again", q["how_to_run"])
            self.assertIn("get-actor-run", q["how_to_run"])

    def test_web_playbooks_carry_the_rule(self):
        self.assertIn(tools.RUN_ONCE, tools.WEB_NOTE)
        self.assertIn(tools.RUN_ONCE, tools.get_playbook("start")["text"])

    def test_the_main_playbooks_and_the_tools_reference_say_it_in_their_own_text(self):
        for name in ("start", "ai-search-visibility", "citation-loop", "tools-and-apis"):
            with open(tools.playbook_paths()[name], encoding="utf-8") as fh:
                self.assertIn("get-actor-run", fh.read(), name)


# ---------------------------------------------------------------- no double counting
class DuplicateImportTests(Base):
    def test_the_same_answers_appended_twice_are_counted_once(self):
        stamp = "2026-11-06T10:00:00Z"
        run(hist.save_results("acme-site", rows("baseline", stamp), PANEL, brand=BRAND))
        again = run(hist.save_results("acme-site", rows("baseline", stamp), append=True))
        self.assertEqual(again["snapshots_saved"], {})
        self.assertTrue(any("already saved" in w for w in again["warnings"]), again["warnings"])
        self.assertEqual(len(run(hist.load_project("acme-site"))["runs"]), len(PANEL))

    def test_a_real_second_repeat_is_still_added(self):
        run(hist.save_results("acme-site", rows("baseline", "2026-11-06T10:00:00Z"), PANEL, brand=BRAND))
        more = run(hist.save_results("acme-site", rows("baseline", "2026-11-06T11:30:00Z"), append=True))
        self.assertEqual(more["snapshots_saved"], {"baseline": 2 * len(PANEL)})

    def test_answers_with_only_a_date_are_never_treated_as_duplicates(self):
        run(hist.save_results("acme-site", rows("baseline", "2026-11-06"), PANEL, brand=BRAND))
        more = run(hist.save_results("acme-site", rows("baseline", "2026-11-06"), append=True))
        self.assertEqual(more["snapshots_saved"], {"baseline": 2 * len(PANEL)})

    def test_the_same_moment_from_another_country_is_a_different_answer(self):
        stamp = "2026-11-06T10:00:00Z"
        run(hist.save_results("acme-site", rows("baseline", stamp, country="US"), PANEL, brand=BRAND))
        more = run(hist.save_results("acme-site", rows("baseline", stamp, country="GB"), append=True))
        self.assertEqual(more["snapshots_saved"], {"baseline": 2 * len(PANEL)})

    def test_a_partly_repeated_batch_adds_only_the_new_answers(self):
        stamp = "2026-11-06T10:00:00Z"
        run(hist.save_results("acme-site", rows("baseline", stamp)[:3], PANEL, brand=BRAND))
        more = run(hist.save_results("acme-site", rows("baseline", stamp), append=True))
        self.assertEqual(more["snapshots_saved"], {"baseline": len(PANEL)})


# ---------------------------------------------------------------- a site that could not be read
def crawled(pages, stopped=False):
    return {"start": "https://acme.com", "origin": "https://acme.com", "crawled": len(pages), "pages": pages,
            "stopped_early": stopped,
            "signals": {"robots_txt": {"status": 200, "bytes": 10}, "sitemaps": [], "llms_txt": False}}


class UnreadableSiteTests(Base):
    def audit(self, pages, stopped=False):
        with mock.patch.object(sa, "crawl", return_value=crawled(pages, stopped)):
            return tools.run_audit("https://acme.com", 5)

    def test_a_blocked_site_gets_no_score(self):
        out = self.audit([{"url": "https://acme.com/", "status": 403, "depth": 0}])
        self.assertEqual(out["status"], "unreadable")
        self.assertIsNone(out["health_score"])
        self.assertEqual(out["subscores"], {})
        self.assertIn("403", out["headline"])
        self.assertIn("No score", out["headline"])
        self.assertIn("Do not show a score", out["next"])

    def test_each_cause_is_named_in_plain_words(self):
        cases = {403: "refused", 429: "refused", 503: "server error", 404: "not found", "blocked_by_robots": "robots",
                 0: "did not answer"}
        for status, word in cases.items():
            reason = sa.unreadable_reason(crawled([{"url": "https://acme.com/", "status": status}]))
            self.assertIn(word, reason, status)
        self.assertIn("time limit", sa.unreadable_reason(crawled([])))

    def test_a_page_that_was_read_is_scored_as_before(self):
        self.assertIsNone(sa.unreadable_reason(crawled([{"url": "https://acme.com/", "status": 200, "word_count": 300}])))

    def test_an_unreadable_check_is_not_saved_as_a_point_on_the_trend(self):
        blocked = audit_result(["Site could not be read"], score=None, status="unreadable")
        with self.assertRaises(ValueError) as caught:
            run(hist.save_audit("acme-site", blocked))
        self.assertIn("could not read", str(caught.exception))
        self.assertEqual(run(hist.list_projects()), [])

    def test_audit_site_with_a_project_leaves_history_alone_when_the_site_is_blocked(self):
        run(hist.save_audit("acme-site", audit_result(["XML sitemap"])))
        blocked = audit_result(["Site could not be read"], score=None, status="unreadable")
        with mock.patch.object(tools, "run_audit", return_value=blocked):
            out = run(runner.audit("https://acme.com", 5, "acme-site"))
        self.assertIsNone(out["saved"])
        self.assertEqual(len(run(hist.load_project("acme-site"))["audits"]), 1)

    def test_a_check_cut_short_says_it_covers_part_of_the_site(self):
        summary = {"health_score": 80, "subscores": {"technical": 80}, "fail": 0, "warn": 0, "pass": 3}
        with mock.patch.object(sa, "score", return_value=[]), mock.patch.object(sa, "summarise", return_value=summary):
            out = self.audit([{"url": "https://acme.com/", "status": 200, "word_count": 300}], stopped=True)
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["health_score"], 80)
        self.assertIn("part of the site", out["headline"])
        self.assertIn("time limit", out["limits"])

    def test_the_crawl_reports_when_it_ran_out_of_time(self):
        def slow_follow(url, limit=6):
            return {"url": url, "status": 200, "headers": {"content-type": "text/html"}, "body": b"<html></html>",
                    "ms": 1}, [url]
        with mock.patch.object(sa, "follow", side_effect=slow_follow), \
                mock.patch.object(sa, "site_signals", return_value=({}, mock.Mock(can_fetch=lambda *a: True))), \
                mock.patch.object(sa.time, "monotonic", side_effect=[0.0, 100.0, 100.0, 100.0]):
            out = sa.crawl("https://acme.com", 5, 0, time_budget=60.0)
        self.assertTrue(out["stopped_early"])
        self.assertEqual(out["crawled"], 0)


# ---------------------------------------------------------------- a round keeps its own date
class RoundDateTests(Base):
    def test_a_round_meta_lost_track_of_is_dated_by_its_answers_not_by_the_project(self):
        old = [dict(r, date="2026-01-10") for r in rows("baseline")]
        new = [dict(r, date="2026-06-10") for r in rows("june")]
        run(hist.save_results("acme-site", old, PANEL, brand=BRAND))
        run(hist.save_results("acme-site", new))
        meta = self.backend.data[stg.key("acme-site", "meta")]
        meta["created"] = "2026-01-01"
        meta["snapshots"] = {"baseline": "2026-01-10"}  # as after a save that stopped before meta was written
        data = run(hist.load_project("acme-site"))
        self.assertEqual(data["meta"]["snapshots"]["june"], "2026-06-10")
        self.assertEqual([s["snapshot"] for s in hist.snapshot_trend(data)], ["baseline", "june"])


# ---------------------------------------------------------------- where am I
class ProjectListTests(Base):
    def test_no_project_name_lists_every_project(self):
        run(hist.save_results("acme-site", rows("baseline"), PANEL, brand={**BRAND, "site": "https://acme.com"}))
        run(hist.save_audit("beta-shop", audit_result(["XML sitemap"], score=55)))
        out = run(hist.history(None))
        self.assertIsNone(out["project"])
        names = {p["project"]: p for p in out["projects"]}
        self.assertEqual(set(names), {"acme-site", "beta-shop"})
        self.assertEqual(names["acme-site"]["site"], "https://acme.com")
        self.assertEqual(names["acme-site"]["rounds"], 1)
        self.assertEqual(names["beta-shop"]["health_score"], 55)
        self.assertIn("acme-site", out["markdown"])
        self.assertIn("get_history", out["next"])

    def test_an_empty_account_says_how_to_start(self):
        out = run(runner.run_tool("get_history", {}))
        self.assertEqual(out["projects"], [])
        self.assertIn("audit_site", out["next"])

    def test_checks_older_than_thirty_days_are_listed_as_due(self):
        run(hist.save_audit("acme-site", audit_result(["XML sitemap"])))
        meta = self.backend.data[stg.key("acme-site", "meta")]
        meta["last_audit"]["date"] = (dt.date.today() - dt.timedelta(days=45)).isoformat()
        project = run(hist.history(""))["projects"][0]
        self.assertTrue(any("Site check is due" in line for line in project["due"]), project["due"])

    def test_a_fresh_check_is_not_due(self):
        run(hist.save_audit("acme-site", audit_result(["XML sitemap"])))
        self.assertEqual(run(hist.history(""))["projects"][0]["due"], [])

    def test_projects_saved_before_this_version_still_show_their_last_site_check(self):
        run(hist.save_audit("acme-site", audit_result(["XML sitemap"])))
        del self.backend.data[stg.key("acme-site", "meta")]["last_audit"]
        project = run(hist.history(""))["projects"][0]
        self.assertEqual(project["last_site_check"], hist.today())

    def test_a_project_history_carries_settings_todos_and_a_next_step(self):
        run(hist.save_results("acme-site", [], brand=BRAND, settings={"country": "gb", "frequency": "monthly"},
                              todo=[{"step": "Add a sitemap", "status": "open"}]))
        out = run(hist.history("acme-site"))
        self.assertEqual(out["settings"], {"country": "gb", "frequency": "monthly"})
        self.assertEqual(out["todo"][0]["step"], "Add a sitemap")
        self.assertIn("Open to-dos", out["markdown"])
        self.assertTrue(out["next"])


# ---------------------------------------------------------------- site checks that remember
class SavedAuditTests(Base):
    def check(self, problems, passed=(), project="acme-site", url="https://acme.com"):
        with mock.patch.object(tools, "run_audit", return_value=audit_result(problems, passed)) as fake:
            out = run(runner.audit(url, 5, project))
        return out, fake

    def test_a_project_name_saves_the_check_without_passing_it_back(self):
        out, _ = self.check(["XML sitemap", "Title tag present"])
        self.assertEqual(out["saved"]["project"], "acme-site")
        self.assertTrue(out["saved"]["created"])
        self.assertIn("next_steps with project='acme-site'", out["next"])
        self.assertEqual(len(run(hist.load_project("acme-site"))["audits"]), 1)

    def test_no_project_name_saves_nothing_and_says_how_to_keep_it(self):
        out, _ = self.check(["XML sitemap"], project=None)
        self.assertIsNone(out["saved"])
        self.assertIn("project name", out["next"])
        self.assertEqual(run(hist.list_projects()), [])

    def test_the_next_check_says_what_was_fixed_what_is_new_and_what_is_still_open(self):
        first = audit_result(["XML sitemap", "Title tag present"])
        run(hist.save_audit("acme-site", first))
        key = stg.key("acme-site", "audit", hist.today())
        earlier = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        record = self.backend.data.pop(key)
        self.backend.data[stg.key("acme-site", "audit", earlier)] = {**record, "date": earlier}
        out, _ = self.check(["Title tag present", "Mobile viewport"], passed=["XML sitemap"])
        changes = out["saved"]["changes"]
        self.assertEqual(changes["since"], earlier)
        self.assertEqual(changes["fixed"], ["XML sitemap"])
        self.assertEqual(changes["new"], ["Mobile viewport"])
        self.assertEqual(changes["still_open"], ["Title tag present"])
        self.assertIn("1 fixed, 1 new, 1 still open", out["headline"])

    def test_a_check_that_did_not_run_this_time_is_not_called_fixed(self):
        before = {"date": "2026-01-01", "problems": [{"check": "XML sitemap"}, {"check": "Click depth"}]}
        now = {"problems": [], "passed": ["XML sitemap"]}  # 'Click depth' was not evaluated this time
        self.assertEqual(hist.compare_audits(before, now)["fixed"], ["XML sitemap"])

    def test_a_second_check_on_the_same_day_is_compared_with_the_first(self):
        self.check(["XML sitemap", "Title tag present"])
        out, _ = self.check(["Title tag present"], passed=["XML sitemap"])
        self.assertEqual(out["saved"]["changes"]["fixed"], ["XML sitemap"])
        self.assertEqual(out["saved"]["changes"]["still_open"], ["Title tag present"])
        self.assertEqual(len(run(hist.load_project("acme-site"))["audits"]), 1)

    def test_an_older_shortened_record_does_not_make_problems_look_new(self):
        before = {"date": "2026-01-01", "problems": [{"check": "XML sitemap"}]}  # saved before pass lists were kept
        now = {"problems": [{"check": "XML sitemap"}, {"check": "Click depth"}], "passed": []}
        changes = hist.compare_audits(before, now)
        self.assertEqual(changes["new"], [])
        self.assertIn("shorter form", changes["note"])

    def test_a_bad_site_check_is_refused_before_the_results_are_written(self):
        blocked = audit_result(["Site could not be read"], score=None, status="unreadable")
        with self.assertRaises(ValueError):
            run(runner.save("acme-site", rows("baseline"), PANEL, None, BRAND, blocked))
        self.assertEqual(run(hist.list_projects()), [])

    def test_a_first_check_has_nothing_to_compare(self):
        out, _ = self.check(["XML sitemap"])
        self.assertIsNone(out["saved"]["changes"])

    def test_a_saved_project_can_be_rechecked_without_typing_the_address(self):
        run(hist.save_results("acme-site", [], brand={**BRAND, "site": "https://acme.com"}))
        out, fake = self.check(["XML sitemap"], url=None)
        self.assertEqual(fake.call_args.args[0], "https://acme.com")
        self.assertIsNotNone(out["saved"])

    def test_no_address_and_no_saved_site_asks_for_the_address(self):
        run(hist.save_results("acme-site", [], brand={"name": "Acme"}))
        with self.assertRaises(ValueError) as caught:
            self.check(["XML sitemap"], url=None)
        self.assertIn("Pass the website address", str(caught.exception))

    def test_every_problem_is_kept_so_the_next_check_can_compare_them_all(self):
        many = [f"Check {n}" for n in range(25)]
        run(hist.save_audit("acme-site", audit_result(many)))
        self.assertEqual(len(run(hist.latest_audit("acme-site"))["problems"]), 25)

    def test_the_scheduled_check_reports_changes_and_survives_a_blocked_site(self):
        blocked = audit_result(["Site could not be read"], score=None, status="unreadable")
        with mock.patch.object(tools, "run_audit", return_value=blocked):
            out = run(runner.run_tool("scheduled_check", {"project": "acme-site", "url": "https://acme.com"}))
        self.assertIsNone(out["health_score"])
        self.assertIsNone(out["report_url"])
        self.assertTrue(out["note"])


# ---------------------------------------------------------------- next steps from memory
class NextStepsFromProjectTests(Base):
    def setUp(self):
        super().setUp()
        run(hist.save_audit("acme-site", audit_result(["XML sitemap", "Title tag present"])))

    def test_a_project_name_is_enough(self):
        out = run(runner.run_tool("next_steps", {"project": "acme-site"}))
        steps = [s["step"] for s in out["steps"]]
        self.assertIn("Add a sitemap", steps)
        self.assertEqual(out["project"], "acme-site")

    def test_steps_marked_done_are_not_suggested_again(self):
        run(hist.save_results("acme-site", [], todo=[{"step": "Add a sitemap", "status": "done"}]))
        steps = [s["step"] for s in run(runner.next_steps(None, None, 5, "acme-site"))["steps"]]
        self.assertNotIn("Add a sitemap", steps)
        self.assertIn("Give every page a clear title", steps)

    def test_a_skipped_step_stays_away_and_an_open_one_comes_back(self):
        run(hist.save_results("acme-site", [], todo=[{"step": "Add a sitemap", "status": "skipped"}]))
        self.assertNotIn("Add a sitemap", [s["step"] for s in run(runner.next_steps(None, None, 5, "acme-site"))["steps"]])
        run(hist.save_results("acme-site", [], todo=[{"step": "Add a sitemap", "status": "open"}]))
        self.assertIn("Add a sitemap", [s["step"] for s in run(runner.next_steps(None, None, 5, "acme-site"))["steps"]])

    def test_an_unknown_project_names_the_closest_saved_one(self):
        with self.assertRaises(ValueError) as caught:
            run(runner.next_steps(None, None, 5, "acme-sit"))
        self.assertIn("Did you mean 'acme-site'", str(caught.exception))

    def test_a_blank_project_is_the_same_as_none(self):
        out = run(runner.run_tool("next_steps", {"project": "", "audit": audit_result(["XML sitemap"])}))
        self.assertIn("Add a sitemap", [s["step"] for s in out["steps"]])

    def test_without_a_project_it_works_as_before(self):
        out = run(runner.run_tool("next_steps", {"audit": audit_result(["XML sitemap"])}))
        self.assertIn("Add a sitemap", [s["step"] for s in out["steps"]])

    def test_bad_to_do_updates_are_refused_in_plain_words(self):
        for bad in ([{"step": "", "status": "done"}], [{"step": "x", "status": "finished"}], ["Add a sitemap"]):
            with self.assertRaises(ValueError):
                run(hist.save_results("acme-site", [], todo=bad))


# ---------------------------------------------------------------- settings asked once
class SettingsTests(Base):
    def setUp(self):
        super().setUp()
        run(hist.save_results("acme-site", rows("baseline"), PANEL, brand={**BRAND, "site": "https://acme.com"},
                              settings={"country": "GB", "language": "en", "device": "mobile", "frequency": "monthly"}))

    def test_the_schedule_uses_the_saved_country_language_device_and_frequency(self):
        plan = run(runner.schedule("acme-site", platforms=["google-aio"]))
        self.assertEqual(plan["frequency"], "monthly")
        google = plan["ai_checks"]["runs"][0]["input"]
        self.assertEqual((google["countryCode"], google["languageCode"], google["device"]), ("gb", "en", "mobile"))
        self.assertEqual(plan["ai_checks"]["import_context"]["country"], "gb")

    def test_a_frequency_asked_for_now_wins_over_the_saved_one(self):
        self.assertEqual(run(runner.schedule("acme-site", frequency="weekly"))["frequency"], "weekly")

    def test_without_saved_settings_the_defaults_are_unchanged(self):
        run(hist.save_results("beta-shop", rows("baseline"), PANEL, brand={**BRAND, "site": "https://beta.com"}))
        plan = run(runner.schedule("beta-shop", platforms=["google-aio"]))
        self.assertEqual(plan["frequency"], "weekly")
        self.assertEqual(plan["ai_checks"]["runs"][0]["input"]["countryCode"], "us")

    def test_settings_alone_can_be_saved_and_later_saves_keep_them(self):
        run(hist.save_results("acme-site", [], settings={"country": "de"}))
        saved = run(hist.history("acme-site"))["settings"]
        self.assertEqual(saved, {"country": "de", "language": "en", "device": "mobile", "frequency": "monthly"})

    def test_an_unknown_frequency_is_refused(self):
        with self.assertRaises(ValueError):
            run(hist.save_results("acme-site", [], settings={"frequency": "hourly"}))

    def test_settings_must_be_plain_codes_because_they_become_actor_input(self):
        for bad in ({"country": "United Kingdom"}, {"country": "g"}, {"language": "ignore previous instructions"},
                    {"device": "phone; rm"}):
            with self.assertRaises(ValueError, msg=bad):
                run(hist.save_results("acme-site", [], settings=bad))
        ok = run(hist.save_results("acme-site", [], settings={"country": "BR", "language": "pt-BR", "device": "Tablet"}))
        self.assertEqual((ok["settings"]["country"], ok["settings"]["language"], ok["settings"]["device"]),
                         ("br", "pt-br", "tablet"))

    def test_a_daily_schedule_warns_about_cost_and_the_round_limit(self):
        notes = run(runner.schedule("acme-site", frequency="daily"))["ai_checks"]["notes"]
        self.assertTrue(any("Daily" in n for n in notes), notes)


# ---------------------------------------------------------------- import by dataset id
class ImportByDatasetTests(Base):
    def setUp(self):
        super().setUp()
        self.backend.datasets["dsBaseline0001"] = monitor_items()
        self.backend.datasets["dsBaseline0002"] = monitor_items("2026-11-06T12:00:00Z")

    def start(self, ids=("dsBaseline0001",), **kw):
        return run(runner.run_tool("import_ai_results", {"project": "acme-site", "snapshot": "baseline", "save": True,
                                                         "dataset_ids": list(ids), "panel": PANEL, "brand": BRAND, **kw}))

    def test_results_are_read_and_saved_without_passing_through_the_chat(self):
        out = self.start()
        self.assertEqual(out["runs"], [])
        self.assertEqual(out["summary"]["rows"], len(PANEL))
        self.assertEqual(out["dataset_ids"], ["dsBaseline0001"])
        self.assertEqual(out["saved"]["snapshots_saved"], {"baseline": len(PANEL)})
        self.assertIn("measure_recommendation_share", out["next"])

    def test_several_runs_of_one_round_go_in_one_call(self):
        out = self.start(ids=("dsBaseline0001", "dsBaseline0002"))
        self.assertEqual(out["summary"]["rows"], 2 * len(PANEL))

    def test_the_same_dataset_is_not_counted_twice(self):
        self.start()
        with self.assertRaises(ValueError) as caught:
            run(runner.run_tool("import_ai_results", {"project": "acme-site", "snapshot": "baseline", "save": True,
                                                      "append": True, "dataset_ids": ["dsBaseline0001"]}))
        self.assertIn("already in this round", str(caught.exception))
        self.assertEqual(len(run(hist.load_project("acme-site"))["runs"]), len(PANEL))

    def test_a_second_run_can_be_added_to_the_round_later(self):
        self.start()
        out = run(runner.run_tool("import_ai_results", {"project": "acme-site", "snapshot": "baseline", "save": True,
                                                        "append": True, "dataset_ids": ["dsBaseline0002"]}))
        self.assertEqual(out["saved"]["snapshots_saved"], {"baseline": 2 * len(PANEL)})

    def test_replace_loads_a_dataset_again_from_scratch(self):
        self.start()
        out = self.start(replace=True)
        self.assertEqual(out["saved"]["snapshots_saved"], {"baseline": len(PANEL)})

    def test_without_save_the_rows_come_back_for_review_and_nothing_is_stored(self):
        out = run(runner.import_results("acme-site", None, "baseline", panel=PANEL, brand=BRAND,
                                        dataset_ids=["dsBaseline0001"]))
        self.assertEqual(len(out["runs"]), len(PANEL))
        self.assertEqual(run(hist.list_projects()), [])
        self.assertIn("save=true", out["next"])

    def test_an_unknown_dataset_says_how_to_get_round_it(self):
        with self.assertRaises(ValueError) as caught:
            self.start(ids=("dsMissing00001",))
        self.assertIn("pass the result items", str(caught.exception))

    def test_an_empty_dataset_says_to_wait_and_not_to_start_again(self):
        self.backend.datasets["dsEmpty000001"] = []
        with self.assertRaises(ValueError) as caught:
            self.start(ids=("dsEmpty000001",))
        self.assertIn("Do not start the runs again", str(caught.exception))

    def test_ids_that_are_not_ids_are_refused(self):
        for bad in ("https://api.apify.com/v2/datasets/x", "../secret", "a b", ""):
            with self.assertRaises(ValueError, msg=bad):
                stg.clean_dataset_id(bad)

    def test_items_and_ids_together_are_refused(self):
        with self.assertRaises(ValueError):
            run(runner.import_results("acme-site", monitor_items(), "baseline", panel=PANEL, brand=BRAND,
                                      dataset_ids=["dsBaseline0001"]))

    def test_passing_items_still_works(self):
        out = run(runner.import_results("acme-site", monitor_items(), "baseline", save=True, panel=PANEL, brand=BRAND))
        self.assertEqual(len(out["runs"]), len(PANEL))
        self.assertIsNone(out["dataset_ids"])

    def test_saved_settings_are_not_stamped_on_answers_whose_conditions_are_unknown(self):
        run(hist.save_results("acme-site", [], PANEL, brand=BRAND, settings={"country": "gb", "device": "mobile"}))
        out = run(runner.import_results("acme-site", None, "baseline", dataset_ids=["dsBaseline0001"]))
        self.assertIsNone(out["context"])
        self.assertFalse(any(r.get("country") or r.get("device") for r in out["runs"]))

    def test_datasets_too_large_to_read_whole_are_refused_not_cut_short(self):
        self.backend.datasets["dsHuge00000001"] = monitor_items() * 900  # 5,400 items
        with mock.patch.object(stg, "MAX_DATASET_ITEMS", 5000), self.assertRaises(ValueError) as caught:
            self.start(ids=("dsHuge00000001",))
        self.assertIn("Nothing was imported", str(caught.exception))
        self.assertEqual(run(hist.list_projects()), [])

    def test_two_datasets_that_together_pass_the_limit_are_refused(self):
        with mock.patch.object(stg, "MAX_DATASET_ITEMS", 2 * len(PANEL) - 1), self.assertRaises(ValueError):
            self.start(ids=("dsBaseline0001", "dsBaseline0002"))

    def test_after_a_replace_the_old_dataset_can_be_imported_again(self):
        self.start()
        self.start(ids=("dsBaseline0002",), replace=True, append=True)
        self.assertEqual(self.backend.data[stg.key("acme-site", "meta")]["imports"]["baseline"], ["dsBaseline0002"])
        out = run(runner.run_tool("import_ai_results", {"project": "acme-site", "snapshot": "baseline", "save": True,
                                                        "append": True, "dataset_ids": ["dsBaseline0001"]}))
        self.assertEqual(out["saved"]["snapshots_saved"], {"baseline": 2 * len(PANEL)})

    def test_replacing_a_round_with_plain_items_forgets_its_old_datasets(self):
        self.start()
        run(runner.import_results("acme-site", monitor_items("2026-11-07T09:00:00Z"), "baseline", save=True, replace=True))
        self.assertEqual(self.backend.data[stg.key("acme-site", "meta")]["imports"]["baseline"], [])

    def test_importing_only_answers_already_saved_says_nothing_new_was_added(self):
        run(runner.import_results("acme-site", monitor_items(), "baseline", save=True, panel=PANEL, brand=BRAND))
        self.backend.datasets["dsSameAnswers1"] = monitor_items()
        out = run(runner.run_tool("import_ai_results", {"project": "acme-site", "snapshot": "baseline", "save": True,
                                                        "append": True, "dataset_ids": ["dsSameAnswers1"]}))
        self.assertTrue(any("Nothing new was added" in n for n in out["notes"]), out["notes"])


class ApifyDatasetReadTests(unittest.TestCase):
    """The live backend, with a stand-in for Apify's client."""

    def backend(self, list_items):
        client = mock.Mock()
        client.dataset.return_value.list_items = list_items
        return stg.ApifyBackend(mock.Mock(), client), client

    def test_items_are_read_with_the_callers_own_client(self):
        async def list_items(**kw):
            self.assertEqual(kw, {"limit": 10, "clean": True})
            return mock.Mock(items=[{"query": "q"}])
        backend, client = self.backend(list_items)
        self.assertEqual(run(backend.dataset_items("dsBaseline0001", 10)), [{"query": "q"}])
        client.dataset.assert_called_once_with("dsBaseline0001")

    def test_a_failed_read_becomes_a_plain_sentence(self):
        async def list_items(**kw):
            raise PermissionError("secret detail")
        backend, _ = self.backend(list_items)
        with self.assertRaises(ValueError) as caught:
            run(backend.dataset_items("dsBaseline0001"))
        self.assertIn("pass the result items", str(caught.exception))
        self.assertNotIn("secret detail", str(caught.exception))

    def test_no_client_means_a_plain_refusal(self):
        with self.assertRaises(ValueError):
            run(stg.ApifyBackend(mock.Mock()).dataset_items("dsBaseline0001"))


# ---------------------------------------------------------------- misspelt project names
class MisspeltProjectTests(Base):
    def setUp(self):
        super().setUp()
        run(hist.save_results("acme-site", rows("baseline"), PANEL, brand={**BRAND, "site": "https://acme.com"}))

    def test_a_new_project_with_a_look_alike_name_is_flagged(self):
        out = run(hist.save_results("acme-sit", [], brand=BRAND))
        self.assertTrue(out["created"])
        self.assertTrue(any("NEW project" in w and "acme-site" in w for w in out["warnings"]), out["warnings"])

    def test_a_clearly_different_name_is_not_flagged(self):
        out = run(hist.save_results("globex-store", [], brand=BRAND))
        self.assertTrue(out["created"])
        self.assertFalse(any("NEW project" in w for w in out["warnings"]))

    def test_saving_to_an_existing_project_is_not_a_creation(self):
        self.assertFalse(run(hist.save_results("acme-site", [], brand=BRAND))["created"])

    def test_a_schedule_for_a_misspelt_name_stops_instead_of_planning_the_wrong_thing(self):
        with self.assertRaises(ValueError) as caught:
            run(runner.schedule("acme-sit"))
        self.assertIn("Did you mean 'acme-site'", str(caught.exception))

    def test_a_look_alike_new_project_with_its_own_address_gets_a_plan_and_a_question(self):
        plan = run(runner.schedule("acme-sit", url="https://other.com"))
        self.assertIsNone(plan["ai_checks"])
        self.assertIn("Did you mean 'acme-site'", plan["note"])

    def test_a_schedule_for_a_brand_new_project_says_it_covers_the_site_check_only(self):
        plan = run(runner.schedule("globex-store", url="https://globex.com"))
        self.assertIsNone(plan["ai_checks"])
        self.assertIn("no saved project called 'globex-store'", plan["note"])

    def test_the_site_check_flags_a_look_alike_name_too(self):
        with mock.patch.object(tools, "run_audit", return_value=audit_result(["XML sitemap"])):
            out = run(runner.audit("https://acme.com", 5, "acme-sit"))
        self.assertTrue(any("acme-site" in w for w in out["saved"]["warnings"]))


if __name__ == "__main__":
    unittest.main()
