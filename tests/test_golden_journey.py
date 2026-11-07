"""Golden journey: a first-time web user walks the whole connector once, and every output feeds the next tool.

audit_site -> next_steps -> quote_cost -> (paid check, faked) -> save_results -> import_ai_results -> save_results
-> get_history -> measure_recommendation_share -> next_steps -> make_report -> schedule_checks.

Every call goes through the real MCP tool layer in-process (server.build_server().call_tool), so the typed inputs,
the typed outputs and the plain-language error wrapper are all exercised. Storage is the in-memory backend, the site
check reads a local fixture server (tests/test_site_audit.py) and the paid AI check is a fixture list shaped like the
AI Brand Monitor dataset items. Nothing touches the network, Apify or a real account.

Links in the chain that do not fit together are kept as `known_gap` tests marked expectedFailure: the healthy parts
stay green, and when a gap is fixed the test starts passing and the marker must be removed.
"""
import asyncio
import importlib.util
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_site_audit import ServerCase  # noqa: E402

HAVE = all(importlib.util.find_spec(m) for m in ("mcp", "pydantic"))
if HAVE:
    from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

    import server  # noqa: E402
    import storage as stg  # noqa: E402
    import tools  # noqa: E402

PROJECT = "fixturely-site"
BRAND = {"name": "Fixturely", "domain": "fixturely.example", "competitors": ["Rival One", "Rival Two"]}
ENGINES = ("chatgpt", "perplexity", "gemini")
REPEATS = 3
BASELINE, LATER = "baseline", "2026-12"
BASELINE_DAY, LATER_DAY, CHANGE_DAY = "2026-11-07", "2026-12-07", "2026-11-20"
BASE_HITS = {"a01", "a02", "c01"}                                   # 3 of 20 buying questions: 15%
TARGETS = [f"a{n:02d}" for n in range(3, 11)]                       # the change helps these 8 questions
LATER_HITS = BASE_HITS | set(TARGETS)                               # 11 of 20: 55%
NO_RAW_ERRORS = ("Traceback", "KeyError", "TypeError", "AttributeError", "ValidationError", "pydantic")
STRANGER = "a question that is not in the panel"

# Same shape as the ai_check pack: 20 buying questions, 5 controls, 5 brand-name checks.
PANEL = (
    [{"prompt_id": f"a{n:02d}", "prompt": f"best invoicing tool for freelancers number {n}", "type": "awareness"}
     for n in range(1, 11)]
    + [{"prompt_id": f"c{n:02d}", "prompt": f"which invoicing app should a small studio pick {n}", "type": "consideration"}
       for n in range(1, 11)]
    + [{"prompt_id": f"x{n:02d}", "prompt": f"how do I bake sourdough bread {n}", "type": "control"} for n in range(1, 6)]
    + [{"prompt_id": f"b{n:02d}", "prompt": f"is Fixturely any good {n}", "type": "brand"} for n in range(1, 6)]
)
BUYING = [p for p in PANEL if p["type"] in ("awareness", "consideration")]
BY_TEXT = {p["prompt"]: p for p in PANEL}


def brand_monitor_items(hits, day, extra=()):
    """What the AI Brand Monitor dataset holds: one item per question x engine x repeat, plus one Google AI Overviews
    item per buying question (the ai_check pack prices exactly this: 30 x 3 x 3 + 20 = 290 items)."""
    out = []
    for p in PANEL:
        for platform in ENGINES:
            for _ in range(REPEATS):
                hit = p["prompt_id"] in hits or p["type"] == "brand"
                out.append({"query": p["prompt"], "platform": platform, "brand_mentioned": hit,
                            "sentiment": "positive" if hit else "", "brand_mention_count": 2 if hit else 0,
                            "is_cited_as_source": hit, "cited_urls": ["https://www.fixturely.example/a"] if hit else [],
                            "competitor_mentions": ["Rival One"], "scraped_at": f"{day}T10:00:00Z"})
    for p in BUYING:
        hit = p["prompt_id"] in hits
        out.append({"query": p["prompt"], "platform": "google_ai_overviews", "brand_mentioned": hit,
                    "sentiment": "positive" if hit else "", "is_cited_as_source": False, "scraped_at": f"{day}T10:00:00Z"})
    return out + list(extra)


def retyped_rows(items, snapshot, day):
    """What the assistant must type by hand for a first round, because import_ai_results cannot create the question
    list: only the fields save_results needs, with its own judgement of `recommended`."""
    repeat, rows = {}, []
    for item in items:
        pid = BY_TEXT[item["query"]]["prompt_id"]
        platform = {"google_ai_overviews": "google-aio"}.get(item["platform"], item["platform"])
        repeat[(pid, platform)] = repeat.get((pid, platform), 0) + 1
        hit = bool(item["brand_mentioned"])
        rows.append({"snapshot": snapshot, "prompt_id": pid, "platform": platform, "repeat": repeat[(pid, platform)],
                     "recommended": hit, "mentioned": hit, "cited": bool(item.get("is_cited_as_source")), "date": day})
    return rows


REVIEW_ITEMS = (  # mentions that are not clearly positive must be read by a person, never counted automatically
    {"query": "which invoicing app should a small studio pick 9", "platform": "chatgpt", "brand_mentioned": True,
     "sentiment": "neutral", "brand_mention_count": 1, "mention_context": "Fixturely is also an option.",
     "scraped_at": f"{LATER_DAY}T10:00:00Z"},
    {"query": "which invoicing app should a small studio pick 10", "platform": "perplexity", "brand_mentioned": True,
     "sentiment": "negative", "brand_mention_count": 1, "mention_context": "Fixturely is not suited to teams.",
     "scraped_at": f"{LATER_DAY}T10:00:00Z"},
    {"query": STRANGER, "platform": "chatgpt", "brand_mentioned": False},
)
EXPERIMENT = {"action": "Joined two best-of lists", "mechanism": "listicle", "date": CHANGE_DAY,
              "target_prompt_ids": ",".join(TARGETS)}


class Web:
    """A first-time web user: calls tools by name, gets typed output, sees only plain error text."""

    def __init__(self, case):
        self.case = case
        self.mcp = server.build_server()
        self.seen = []  # every output, to prove no raw exception text ever reaches the user

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        self.case.assertFalse(result.is_error, (name, result))
        self.seen.append((name, json.dumps(result.structured_content)))
        return result.structured_content

    async def fail(self, name, **arguments):
        """Calls a tool that must refuse; returns the message the user would see."""
        with self.case.assertRaises(ToolError) as caught:
            await self.mcp.call_tool(name, arguments)
        return str(caught.exception)


async def first_round(web, audit=None):
    """Panel and the first round. The questions can only be saved together with rows, so the baseline is typed."""
    return await web.call("save_results", project=PROJECT, panel=PANEL, brand=BRAND, audit=audit,
                          runs=retyped_rows(brand_monitor_items(BASE_HITS, BASELINE_DAY), BASELINE, BASELINE_DAY))


async def later_round(web):
    imported = await web.call("import_ai_results", project=PROJECT, snapshot=LATER,
                              items=brand_monitor_items(LATER_HITS, LATER_DAY, REVIEW_ITEMS))
    saved = await web.call("save_results", project=PROJECT, runs=imported["runs"], append=True, experiments=[EXPERIMENT])
    return imported, saved


@unittest.skipUnless(HAVE, "mcp and pydantic are not installed")
class GoldenJourney(ServerCase):
    def setUp(self):
        super().setUp()
        self.backend = stg.MemoryBackend()
        stg.set_backend(self.backend)
        self.addCleanup(stg.set_backend, None)
        patcher = mock.patch.object(server.log, "disabled", True)  # keep the one-line call records out of test output
        patcher.start()
        self.addCleanup(patcher.stop)
        self.web = Web(self)

    def assert_plain(self):
        for name, text in self.web.seen:
            for raw in NO_RAW_ERRORS:
                self.assertNotIn(raw, text, f"{name} leaked '{raw}'")

    # ------------------------------------------------------------------ the whole chain
    def test_first_time_user_journey(self):
        asyncio.run(self.journey())

    async def journey(self):
        web = self.web
        # 1. check the site (local fixture, no network)
        audit = await web.call("audit_site", url=self.base, max_pages=5)
        self.assertEqual(audit["pages_checked"], 3)
        self.assertIsInstance(audit["health_score"], int)
        self.assertTrue(audit["problems"])
        self.assertEqual(set(audit["counts"]), {"fail", "warn", "pass"})

        # 2. next_steps takes the audit exactly as returned
        steps = (await web.call("next_steps", audit=audit))["steps"]
        problem_checks = {f"site check: {p['check']}" for p in audit["problems"]}
        self.assertEqual(steps[-1]["step"], "Check again in 30 days")
        self.assertTrue(all(s["why"] and s["who"] and s["effort"] for s in steps))
        self.assertTrue({s["based_on"] for s in steps[:-1]} <= problem_checks)
        self.assertEqual(steps[0]["urgency"], "do first" if audit["counts"]["fail"] else "soon")

        # 3. quote the paid AI check; the priced units are exactly what the fixture dataset holds
        items = brand_monitor_items(BASE_HITS, BASELINE_DAY)
        quote = await web.call("quote_cost", pack="ai_check")
        self.assertEqual({line["job"] for line in quote["lines"]}, {"ai_brand_check", "ai_overview"})
        self.assertEqual(sum(line["units"] for line in quote["lines"]), len(items))
        self.assertGreaterEqual(quote["suggested_cap_usd"], quote["total_usd"] * 1.3)
        self.assertIn(f"maxTotalChargeUsd = {quote['suggested_cap_usd']}", quote["how_to_run"])

        # 4. first save: questions + typed baseline rows + the site check + brand details, all in one call
        saved = await first_round(web, audit)
        self.assertEqual(saved["project"], PROJECT)
        self.assertEqual(saved["snapshots_saved"], {BASELINE: len(items)})
        self.assertEqual(saved["panel_prompts"], len(PANEL))
        self.assertEqual(saved["audit_saved"]["project"], PROJECT)
        self.assertEqual(saved["brand"]["name"], BRAND["name"])
        self.assertEqual(saved["warnings"], [])

        # 5. import the later round's paid results (not saved yet), read the review list, then save the rows as given
        imported = await web.call("import_ai_results", project=PROJECT, snapshot=LATER,
                                  items=brand_monitor_items(LATER_HITS, LATER_DAY, REVIEW_ITEMS))
        later_rows = len(items) + len(REVIEW_ITEMS) - 1  # the two review items match a question; the stranger does not
        self.assertEqual(imported["summary"]["rows"], later_rows)
        self.assertEqual(imported["summary"]["recommended"], 11 * len(ENGINES) * REPEATS + 11 + 5 * len(ENGINES) * REPEATS)
        self.assertEqual(imported["unmatched_queries"], [STRANGER])
        self.assertIsNone(imported["saved"])
        self.assertEqual([(r["prompt_id"], r["sentiment"]) for r in imported["needs_review"]],
                         [("c09", "neutral"), ("c10", "negative")])  # close calls first
        self.assertTrue(all(not r["auto_recommended"] and r["context"] for r in imported["needs_review"]))
        self.assertEqual({r["platform"] for r in imported["runs"]}, {"chatgpt", "perplexity", "gemini", "google-aio"})
        later_saved = await web.call("save_results", project=PROJECT, runs=imported["runs"], append=True,
                                     experiments=[EXPERIMENT])
        self.assertEqual(later_saved["snapshots_saved"], {LATER: later_rows})
        self.assertEqual(sorted(later_saved["snapshots_in_project"]), [LATER, BASELINE])
        self.assertEqual(later_saved["panel_prompts"], len(PANEL))  # the frozen list was reused, not retyped
        self.assertEqual(later_saved["warnings"], [])

        # 6. history shows both rounds in save order, current counting, the brand-name check apart from the headline
        history = await web.call("get_history", project=PROJECT)
        first, latest = history["snapshots"]
        self.assertEqual((first["snapshot"], latest["snapshot"]), (BASELINE, LATER))
        self.assertAlmostEqual(first["recommendation_share"], 0.15, places=2)
        self.assertAlmostEqual(latest["recommendation_share"], 0.55, places=2)
        self.assertLess(latest["rs_low"], latest["recommendation_share"])
        self.assertLess(latest["recommendation_share"], latest["rs_high"])
        self.assertEqual(first["prompts"], len(BUYING))
        for snap in history["snapshots"]:
            self.assertEqual(snap["metric_version"], tools.cl.METRIC_VERSION)
            self.assertFalse(snap["older_metric"])
            self.assertEqual(snap["reputation_share"], 1.0)  # brand-name questions are reported separately
            self.assertEqual(snap["reputation_prompts"], 5)
        self.assertEqual(history["audits"][0]["health_score"], audit["health_score"])
        self.assertEqual(history["experiments"][0]["action"], EXPERIMENT["action"])
        self.assertIn("| 2026-12 |", history["markdown"])
        self.assertIn("55.0%", history["markdown"])

        # 7. measure the saved project: headline, verdict wording, smallest visible change
        measured = await web.call("measure_recommendation_share", project=PROJECT)
        self.assertEqual((measured["baseline"], measured["current"], measured["project"]), (BASELINE, LATER, PROJECT))
        self.assertTrue(measured["headline"].startswith("AI recommends you in 55.0% of buying questions (likely range "))
        self.assertEqual(measured["summary"]["all"]["metric_version"], tools.cl.METRIC_VERSION)
        self.assertAlmostEqual(measured["summary"]["all"]["reputation_share"], 1.0)
        self.assertEqual(measured["change"]["all"]["verdict"], "improved")
        self.assertAlmostEqual(measured["change"]["all"]["delta"], 0.40, places=2)
        self.assertTrue(measured["change"]["all"]["comparable"])
        self.assertGreater(measured["smallest_change_points"], 0)
        self.assertEqual(measured["experiments"][0]["timing"], "ok")
        self.assertEqual(measured["experiments"][0]["result"]["verdict"], "supported")
        self.assertIn("improved", measured["markdown"])
        self.assertTrue(measured["next"])
        # the only caution allowed is the known pack/repeat one (see test_known_gap_pack_round_...)
        self.assertTrue(all("fewer than 3 repeats" in w for w in measured["warnings"]), measured["warnings"])

        # 8. next_steps takes the measurement exactly as returned, next to the audit
        combined = (await web.call("next_steps", audit=audit, report=measured))["steps"]
        self.assertEqual(combined[-1]["step"], "Check again in 30 days")
        self.assertTrue(all(not s["step"].startswith("Get your brand onto") for s in combined))  # 55% is not "low"
        self.assertTrue({s["based_on"] for s in combined[:-1]} <= problem_checks)

        # 9. the shareable report repeats the headline number, the verdict wording and the site problems
        report = await web.call("make_report", project=PROJECT)
        self.assertEqual((report["snapshots"], report["site_checks"]), (2, 1))
        self.assertIn("stop sharing", report["note"])
        self.assertIsNone(report["share_url"])  # the memory backend cannot make links, and the note says so
        self.assertIn("No share link", report["note"])
        page = self.backend.data[report["stored_key"]]
        self.assertEqual(len(page), report["bytes"])
        self.assertIn("55.0%", page)
        self.assertIn("AI assistants recommended Fixturely in the latest round (2026-12)", page)
        self.assertIn('<span class="up">improved</span>', page)
        self.assertIn("supported", page)
        self.assertIn(f"{audit['health_score']}/100", page)
        self.assertIn("Top problems to fix", page)
        self.assertIn("What to do next", page)
        for bad in ("<script", "<link", "<img"):  # self-contained page (problem details may quote the audited address)
            self.assertNotIn(bad, page)

        # 10. the schedule reuses the saved questions and brand; its queries are the exact panel text
        plan = await web.call("schedule_checks", project=PROJECT, url=audit["site"], frequency="monthly")
        self.assertEqual(plan["cron"], "0 8 1 * *")
        self.assertEqual(plan["free_site_check"]["input"]["arguments"]["url"], audit["site"])
        ai = plan["ai_checks"]
        self.assertEqual(ai["actor"], quote["lines"][0]["actor"])  # same Actor that was quoted
        self.assertEqual(ai["input"]["brandName"], BRAND["name"])
        self.assertEqual(ai["input"]["competitors"], BRAND["competitors"])
        self.assertEqual(ai["input"]["customQueries"], [p["prompt"] for p in PANEL])
        self.assertEqual(ai["checks_per_run"], len(PANEL) * len(ai["input"]["platforms"]))
        self.assertAlmostEqual(ai["estimated_cost_per_month_usd"], ai["cost_per_run_usd"], places=2)  # monthly = 1 run
        self.assertIsNone(plan.get("note"))

        # 11. the loop closes: results for the scheduled queries import cleanly into the same project
        scheduled = [{"query": q, "platform": engine, "brand_mentioned": True, "sentiment": "positive",
                      "scraped_at": "2027-01-07T08:00:00Z"}
                     for q in ai["input"]["customQueries"] for engine in ai["input"]["platforms"]]
        again = await web.call("import_ai_results", project=PROJECT, items=scheduled, snapshot="2027-01", save=True)
        self.assertEqual(again["unmatched_queries"], [])
        self.assertEqual(again["summary"]["rows"], ai["checks_per_run"])
        self.assertEqual(again["saved"]["snapshots_saved"], {"2027-01": ai["checks_per_run"]})

        self.assert_plain()

    # ------------------------------------------------------------------ other healthy paths of the same journey
    def test_extra_repeats_for_a_saved_round_are_appended_not_overwritten(self):
        async def go():
            web = self.web
            await first_round(web)
            more = await web.call("import_ai_results", project=PROJECT, snapshot=BASELINE,
                                  items=[i for i in brand_monitor_items(BASE_HITS, BASELINE_DAY) if i["platform"] == "chatgpt"])
            self.assertEqual(more["summary"]["rows"], len(PANEL) * REPEATS)
            self.assertEqual({r["repeat"] for r in more["runs"]}, {1, 2, 3})  # numbered from 1 again
            refused = await web.fail("save_results", project=PROJECT, runs=more["runs"])
            self.assertIn("append=true", refused)
            self.assertIn("Nothing was saved", refused)
            out = await web.call("save_results", project=PROJECT, runs=more["runs"], append=True)
            self.assertEqual(out["snapshots_saved"][BASELINE], 290 + len(PANEL) * REPEATS)
            stored = self.backend.data[stg.key(PROJECT, "runs", BASELINE)]
            first_prompt = [r for r in stored if r["prompt_id"] == "a01" and r["platform"] == "chatgpt"]
            self.assertEqual(sorted(r["repeat"] for r in first_prompt), [1, 2, 3, 4, 5, 6])  # renumbered, no clash
            self.assertEqual(len((await web.call("get_history", project=PROJECT))["snapshots"]), 1)
            self.assert_plain()
        asyncio.run(go())

    def test_a_placeholder_row_lets_the_first_round_be_imported_instead_of_retyped(self):
        """The workaround for the first-import dead end: save the questions with one row, then replace by importing."""
        async def go():
            web = self.web
            items = brand_monitor_items(BASE_HITS, BASELINE_DAY)
            one_row = retyped_rows(items[:1], BASELINE, BASELINE_DAY)
            await web.call("save_results", project=PROJECT, panel=PANEL, runs=one_row, brand=BRAND)
            out = await web.call("import_ai_results", project=PROJECT, snapshot=BASELINE, items=items, save=True,
                                 replace=True)
            self.assertEqual(out["saved"]["snapshots_saved"], {BASELINE: len(items)})
            share = (await web.call("get_history", project=PROJECT))["snapshots"][0]["recommendation_share"]
            self.assertAlmostEqual(share, 0.15, places=2)
        asyncio.run(go())

    def test_mistakes_get_plain_messages_that_say_what_to_do(self):
        async def go():
            web = self.web
            await first_round(web)
            changed = [dict(p) for p in PANEL]
            changed[0]["prompt"] = "a completely different question"
            baseline_rows = retyped_rows(brand_monitor_items(BASE_HITS, BASELINE_DAY), BASELINE, BASELINE_DAY)
            later_rows = retyped_rows(brand_monitor_items(BASE_HITS, LATER_DAY), LATER, LATER_DAY)
            cases = [
                ("unknown project", web.fail("get_history", project="other-site"), (PROJECT, "save_results")),
                ("round already saved", web.fail("save_results", project=PROJECT, runs=baseline_rows),
                 ("append=true", "replace=true", "Nothing was saved")),
                ("frozen questions", web.fail("save_results", project=PROJECT, panel=changed, runs=later_rows),
                 ("frozen", "new project name")),
                ("nothing matches", web.fail("import_ai_results", project=PROJECT, snapshot=LATER,
                                             items=[{"query": "zzz", "platform": "chatgpt"}]),
                 ("same question text",)),
                ("measure with new data", web.fail("measure_recommendation_share", project=PROJECT, panel=PANEL),
                 ("save_results",)),
                ("save nothing", web.fail("save_results", project=PROJECT), ("audit_site", "runs")),
            ]
            for label, pending, words in cases:
                message = await pending
                for word in words:
                    self.assertIn(word, message, label)
                for raw in NO_RAW_ERRORS:
                    self.assertNotIn(raw, message, label)
            self.assertEqual(len((await web.call("get_history", project=PROJECT))["snapshots"]), 1)  # nothing leaked in
        asyncio.run(go())

    # ------------------------------------------------------------------ known gaps (expected to fail until fixed)
    @unittest.expectedFailure
    def test_known_gap_first_round_cannot_be_imported_into_a_new_project(self):
        """GAP: import_ai_results needs the project's saved question list, but a list can only be saved together with
        rows (save_results refuses panel-only and silently drops `panel` when only `audit` comes with it). So the
        paid results of the very first round cannot be imported: the assistant must retype ~290 rows by hand."""
        async def go():
            web = self.web
            audit = await web.call("audit_site", url=self.base, max_pages=5)
            saved = await web.call("save_results", project=PROJECT, panel=PANEL, brand=BRAND, audit=audit)
            self.assertEqual(saved["panel_prompts"], len(PANEL))  # today 0: the panel is dropped without a warning
            out = await web.call("import_ai_results", project=PROJECT, snapshot=BASELINE, save=True,
                                 items=brand_monitor_items(BASE_HITS, BASELINE_DAY))
            self.assertEqual(out["saved"]["snapshots_saved"], {BASELINE: 290})
        asyncio.run(go())

    @unittest.expectedFailure
    def test_known_gap_pack_round_does_not_trigger_the_repeat_warning(self):
        """GAP: the ai_check pack prices one Google AI Overviews item per buying question (20 units), so a round
        bought exactly as quoted always has 'fewer than 3 repeats' for that engine and the first headline carries a
        warning that tells the user they under-collected."""
        async def go():
            web = self.web
            await first_round(web)
            await later_round(web)
            measured = await web.call("measure_recommendation_share", project=PROJECT)
            self.assertEqual(measured["warnings"], [])
        asyncio.run(go())

    @unittest.expectedFailure
    def test_known_gap_scheduled_round_meets_the_repeat_and_engine_rules(self):
        """GAP: the schedule plan asks for one answer per question and engine (checks_per_run) and leaves out Google
        AI Overviews, so each scheduled round has 1 repeat (rule: 3) and a different engine set from a pack round.
        Every measurement after a scheduled import then warns, and the 'all' change drops google-aio."""
        async def go():
            web = self.web
            await first_round(web)
            await later_round(web)
            plan = (await web.call("schedule_checks", project=PROJECT, url=self.base))["ai_checks"]
            scheduled = [{"query": q, "platform": engine, "brand_mentioned": True, "sentiment": "positive",
                          "scraped_at": "2027-01-07T08:00:00Z"}
                         for q in plan["input"]["customQueries"] for engine in plan["input"]["platforms"]]
            out = await web.call("import_ai_results", project=PROJECT, items=scheduled, snapshot="2027-01", save=True)
            self.assertEqual(out["summary"]["rows"], plan["checks_per_run"])  # the plan and the import agree
            measured = await web.call("measure_recommendation_share", project=PROJECT)
            self.assertEqual(measured["warnings"], [])
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
