"""Golden journey: a first-time web user walks the whole connector once, and every output feeds the next tool.

audit_site -> next_steps -> quote_cost -> (paid check, faked) -> save_results -> import_ai_results -> save_results
-> get_history -> measure_recommendation_share -> next_steps -> make_report -> schedule_checks.

Every call goes through the real MCP tool layer in-process (server.build_server().call_tool), so the typed inputs,
the typed outputs and the plain-language error wrapper are all exercised. Storage is the in-memory backend, the site
check reads a local fixture server (tests/test_site_audit.py) and the paid AI check is a fixture list shaped like the
AI Brand Monitor dataset items. Nothing touches the network, Apify or a real account.

Links in the chain that did not fit together were kept as `known_gap` tests marked expectedFailure while they were
open; each one is now fixed and the marker is gone. The last one was the scheduled round (fixed in tools.schedule_plan,
not in the import or measurement code).
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


def scheduled_items(plan, day):
    """What the Apify Schedule would leave in the datasets for one round of this plan: every planned Actor run, added
    as many times as the plan says, answered the way each Actor reports (the fixtures use the same shape as the
    baseline, so only the plan decides whether the round matches)."""
    items = []
    for run in plan["ai_checks"]["runs"]:
        queries = run["input"].get("customQueries") or run["input"]["queries"]
        engines = run["input"].get("platforms") or [{"ai_overview": "google_ai_overviews", "ai_mode": "google-aimode"}[run["job"]]]
        for _ in range(run["times"]):
            items += [{"query": q, "platform": engine, "brand_mentioned": True, "sentiment": "positive",
                       "scraped_at": day} for q in queries for engine in engines]
    return items


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

        # 2. next_steps takes the audit exactly as returned (plus the reserved AI-recommend step)
        steps = (await web.call("next_steps", audit=audit))["steps"]
        problem_checks = {f"site check: {p['check']}" for p in audit["problems"]}
        allowed = problem_checks | {"product goal: get cited by AI"}
        self.assertEqual(steps[-1]["step"], "Check again in 30 days")
        self.assertTrue(all(s["why"] and s["who"] and s["effort"] for s in steps))
        self.assertTrue({s["based_on"] for s in steps[:-1]} <= allowed)
        self.assertTrue(any(s["based_on"] == "product goal: get cited by AI" for s in steps))
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
        # a round bought exactly as the pack quotes it (one AI Overviews answer per question, 3 repeats for the
        # assistants) carries no caution at all
        self.assertEqual(measured["warnings"], [])

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

        # 10. the schedule reuses the saved questions and brand; its queries are the exact panel text, the assistants
        # run 3 times (the Actor has no repeat setting, so the run is added 3 times) and Google AI Overviews once
        plan = await web.call("schedule_checks", project=PROJECT, url=audit["site"], frequency="monthly")
        self.assertEqual(plan["cron"], "0 8 1 * *")
        self.assertEqual(plan["free_site_check"]["input"]["arguments"]["url"], audit["site"])
        ai = plan["ai_checks"]
        monitor = [run for run in ai["runs"] if run["job"] == "ai_brand_check"]
        self.assertEqual(monitor[0]["actor"], quote["lines"][0]["actor"])  # same Actor that was quoted
        self.assertEqual(monitor[0]["input"]["brandName"], BRAND["name"])
        self.assertEqual(monitor[0]["input"]["competitors"], BRAND["competitors"])
        self.assertEqual([q for run in monitor for q in run["input"]["customQueries"]], [p["prompt"] for p in PANEL])
        self.assertTrue(all(len(run["input"]["customQueries"]) <= 20 for run in monitor))  # the Actor's own limit
        self.assertEqual({run["times"] for run in monitor}, {REPEATS})
        self.assertEqual(ai["checks_per_round"], len(items))  # the same 290 answers the quoted pack buys
        self.assertAlmostEqual(ai["estimated_cost_per_month_usd"], ai["cost_per_round_usd"], places=2)  # monthly = 1 round
        self.assertGreaterEqual(ai["cost_per_round_usd"], quote["total_usd"] - 0.01)  # at least the quoted pack price
        self.assertIsNone(plan.get("note"))

        # 11. the loop closes: results for the scheduled runs import cleanly into the same project
        scheduled = scheduled_items(plan, "2027-01-07T08:00:00Z")
        again = await web.call("import_ai_results", project=PROJECT, items=scheduled, snapshot="2027-01", save=True)
        self.assertEqual(again["unmatched_queries"], [])
        self.assertEqual(again["summary"]["rows"], ai["checks_per_round"])
        self.assertEqual(again["saved"]["snapshots_saved"], {"2027-01": ai["checks_per_round"]})

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

    # ------------------------------------------------------------------ the scheduled round (formerly a known gap)
    def test_first_round_is_imported_after_saving_the_questions_with_the_site_check(self):
        """Fixed gap: the question list used to be dropped when it came with only a site check, so the paid results of
        the very first round could not be imported and the assistant had to retype ~290 rows by hand."""
        async def go():
            web = self.web
            audit = await web.call("audit_site", url=self.base, max_pages=5)
            saved = await web.call("save_results", project=PROJECT, panel=PANEL, brand=BRAND, audit=audit)
            self.assertEqual(saved["panel_prompts"], len(PANEL))
            self.assertEqual(saved["snapshots_saved"], {})
            self.assertIn("import_ai_results", saved["next"])
            out = await web.call("import_ai_results", project=PROJECT, snapshot=BASELINE, save=True,
                                 items=brand_monitor_items(BASE_HITS, BASELINE_DAY))
            self.assertEqual(out["saved"]["snapshots_saved"], {BASELINE: 290})
            self.assert_plain()
        asyncio.run(go())

    def test_first_round_is_imported_in_one_call_with_the_questions_and_the_brand(self):
        """The shortest path: no separate save of the questions at all."""
        async def go():
            web = self.web
            out = await web.call("import_ai_results", project=PROJECT, snapshot=BASELINE, save=True, panel=PANEL,
                                 brand=BRAND, items=brand_monitor_items(BASE_HITS, BASELINE_DAY))
            self.assertEqual(out["saved"]["snapshots_saved"], {BASELINE: 290})
            self.assertEqual(out["saved"]["panel_prompts"], len(PANEL))
            self.assertEqual(out["saved"]["brand"]["name"], BRAND["name"])
            self.assertEqual(out["skipped"], [])
            self.assertEqual(out["saved"]["warnings"], [])
            history = await web.call("get_history", project=PROJECT)
            self.assertAlmostEqual(history["snapshots"][0]["recommendation_share"], 0.15, places=2)
            measured = await web.call("measure_recommendation_share", project=PROJECT)
            self.assertEqual(measured["warnings"], [])
            self.assert_plain()
        asyncio.run(go())

    def test_a_first_import_without_questions_says_what_is_missing(self):
        async def go():
            web = self.web
            message = await web.fail("import_ai_results", project=PROJECT, snapshot=BASELINE, save=True,
                                     items=brand_monitor_items(BASE_HITS, BASELINE_DAY))
            for word in ("question list", "panel", "save_results"):
                self.assertIn(word, message)
            self.assertNotIn("matched a question", message)  # the questions are missing; the results are fine
        asyncio.run(go())

    def test_pack_round_does_not_trigger_the_repeat_warning(self):
        """Fixed gap: the ai_check pack prices one Google AI Overviews item per buying question (20 units), so a round
        bought exactly as quoted used to carry 'fewer than 3 repeats' for that engine, which told the user they
        under-collected. Single-answer search surfaces are no longer held to the repeat minimum."""
        async def go():
            web = self.web
            await first_round(web)
            await later_round(web)
            measured = await web.call("measure_recommendation_share", project=PROJECT)
            self.assertEqual(measured["warnings"], [])
        asyncio.run(go())

    def test_scheduled_round_meets_the_repeat_and_engine_rules(self):
        """Fixed gap (in tools.schedule_plan, not in the import or the measurement): the plan used to ask for one answer
        per question and engine and left out Google AI Overviews, so each scheduled round had 1 repeat for the
        assistants (rule: 3) and a different engine set from a pack round. Every measurement after a scheduled import
        then warned. The plan now takes a repeats setting (the Actor has none, so the run is added several times),
        splits long lists into runs the Actor accepts, plans the single-answer Google engines once, and follows the
        engines of the first saved round."""
        async def go():
            web = self.web
            await first_round(web)
            await later_round(web)
            plan = await web.call("schedule_checks", project=PROJECT)  # no url: the saved brand domain is used
            self.assertEqual(plan["free_site_check"]["input"]["arguments"]["url"], "https://" + BRAND["domain"])
            ai = plan["ai_checks"]
            self.assertEqual(sorted(ai["engines"]), sorted([*ENGINES, "google-aio"]))  # the engines of the first round
            # the earlier rounds of this project were saved without a country, language or device, so this one is too
            out = await web.call("import_ai_results", project=PROJECT, items=scheduled_items(plan, "2027-01-07T08:00:00Z"),
                                 snapshot="2027-01", save=True)
            self.assertEqual(out["summary"]["rows"], ai["checks_per_round"])  # the plan and the import agree
            self.assertEqual(out["summary"]["rows"], 290)
            self.assertEqual(out["unmatched_queries"], [])
            measured = await web.call("measure_recommendation_share", project=PROJECT)
            self.assertEqual(measured["warnings"], [])
            self.assertEqual(measured["current"], "2027-01")
            self.assertEqual(measured["summary"]["all"]["min_repeats_checked"], 3)
            self.assertEqual(set(measured["summary"]) - {"all"}, set(ENGINES) | {"google-aio"})
            self.assert_plain()
        asyncio.run(go())

    def test_scheduled_round_imported_with_the_plans_context_matches_a_first_round_imported_the_same_way(self):
        """The plan tells the user to pass the run's country, language and device as `context`. Doing it from the first
        round on keeps every round on the same footing, so the measurement has nothing to warn about."""
        async def go():
            web = self.web
            context = {"country": "us", "language": "en", "device": "desktop"}
            await web.call("import_ai_results", project=PROJECT, snapshot=BASELINE, save=True, panel=PANEL, brand=BRAND,
                           items=brand_monitor_items(BASE_HITS, BASELINE_DAY), context=context)
            plan = await web.call("schedule_checks", project=PROJECT)
            self.assertEqual(plan["ai_checks"]["import_context"], context)  # what the plan says to pass
            await web.call("import_ai_results", project=PROJECT, snapshot="2027-01", save=True,
                           items=scheduled_items(plan, "2027-01-07T08:00:00Z"), context=plan["ai_checks"]["import_context"])
            measured = await web.call("measure_recommendation_share", project=PROJECT)
            self.assertEqual(measured["warnings"], [])
            self.assertEqual(measured["current"], "2027-01")
        asyncio.run(go())

    def test_scheduled_round_with_one_repeat_would_still_warn(self):
        """The guard that makes the test above mean something: a round built from a plan with repeats 1 is caught."""
        async def go():
            web = self.web
            await first_round(web)
            await later_round(web)
            plan = await web.call("schedule_checks", project=PROJECT, repeats=1)
            await web.call("import_ai_results", project=PROJECT, items=scheduled_items(plan, "2027-01-07T08:00:00Z"),
                           snapshot="2027-01", save=True)
            measured = await web.call("measure_recommendation_share", project=PROJECT)
            self.assertTrue([w for w in measured["warnings"] if "repeats" in w], measured["warnings"])
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
