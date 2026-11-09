"""quote_cost prices every job at its realistic worst case, not at the best case on the price list.

What the numbers are built from (a read-only audit of 197 real runs and the live pricing of every Actor):
- start events scale with run memory (one per GB, at least one), three Actors have none, two charge $0.005 each;
- the Google AI Overviews Actor used its $0.10 fallback event in every sampled run;
- some Actors bill Apify compute to the caller, which is not in the Actor's own price;
- one Actor's per-request fees are not live yet and it refuses to run until then.
"""
import datetime as dt
import json
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
import tools  # noqa: E402

START = tools.PRICES["start_fee_usd"]
TODAY = dt.date(2026, 11, 8)  # fixed, so the "not live yet" cases do not depend on the day the tests run
AFTER = dt.date(2026, 11, 14)


def quote(job, units, requests=1, today=TODAY):
    return tools.quote_cost([{"job": job, "units": units, "requests": requests}], None, today)


def pack(name, today=TODAY):
    return tools.quote_cost(None, name, today)


def expected_cap(base):
    return max(0.01, math.ceil(round(base * 130, 6)) / 100)


class StartEvents(unittest.TestCase):
    def test_start_events_follow_run_memory_not_a_flat_fee(self):
        # complete-seo-audit defaults to 4 GB: four start events
        self.assertEqual(tools.PRICES["jobs"]["site_audit"]["start_events"], 4)
        self.assertAlmostEqual(quote("site_audit", 1)["total_usd"], 0.1 + 4 * START, places=5)

    def test_three_actors_have_no_start_event_at_all(self):
        for job in ("keyword_difficulty", "longtail_keyword", "youtube_transcript"):
            self.assertEqual(tools.PRICES["jobs"][job]["start_events"], 0, job)
        # no start fee on top of 100 keywords at $0.0015 (compute is separate)
        line = quote("longtail_keyword", 100)["lines"][0]
        self.assertAlmostEqual(line["cost_usd"] - line.get("compute_usd", 0), 0.15, places=5)

    def test_start_events_are_charged_once_per_run(self):
        one = quote("serp_page", 15, requests=1)["total_usd"]
        three = quote("serp_page", 15, requests=3)["total_usd"]
        self.assertAlmostEqual(three - one, 2 * START, delta=0.0001)  # one start event per run at 512 MB; totals show 4 decimals

    def test_quora_start_events_cost_half_a_cent_each(self):
        job = tools.PRICES["jobs"]["quora_question"]
        self.assertEqual((job["start_fee_usd"], job["per_request"]), (0.005, 0.0))
        self.assertGreaterEqual(job["start_events"], 2)
        empty = quote("quora_question", 0)["total_usd"]
        self.assertAlmostEqual(empty, job["start_events"] * 0.005, places=5)  # a run that finds nothing still pays
        self.assertGreaterEqual(empty, 0.01)
        ten = quote("quora_question", 10)["total_usd"]
        self.assertAlmostEqual(ten, empty + 10 * 0.003, places=5)

    def test_software_reviews_with_no_reviews_still_cost_start_and_product_cards(self):
        job = tools.PRICES["jobs"]["review_site"]
        self.assertEqual(job["start_fee_usd"], 0.005)
        zero = quote("review_site", 0)["total_usd"]
        # sampled runs that returned 0 reviews billed $0.02 to $0.04 in events plus compute
        self.assertGreaterEqual(zero, 0.04)
        self.assertGreater(zero, 100 * START)

    def test_a_run_with_zero_results_pays_only_what_it_cannot_avoid(self):
        self.assertLess(quote("keyword_volume", 0)["total_usd"], 0.001)  # no request fee, one 512 MB start event
        self.assertAlmostEqual(quote("serp_page", 0)["total_usd"], START, delta=0.0001)


class AiOverviewsFallback(unittest.TestCase):
    def test_every_query_is_priced_at_the_fallback_rate(self):
        line = quote("ai_overview", 1)["lines"][0]
        self.assertAlmostEqual(line["cost_usd"], 0.10 + 2 * START, places=5)  # 2 GB: two start events
        self.assertEqual(tools.PRICES["jobs"]["ai_overview"]["per_unit"], 0.015)  # the list price stays on record
        self.assertEqual(tools.PRICES["jobs"]["ai_overview"]["per_unit_worst"], 0.10)

    def test_the_line_says_why_in_plain_words(self):
        note = quote("ai_overview", 1)["lines"][0]["note"]
        self.assertIn("$0.10", note)

    def test_brand_match_event_is_covered_by_the_cap_but_not_added_to_the_total(self):
        q = quote("ai_overview", 20)
        self.assertAlmostEqual(q["total_usd"], 20 * 0.10 + 2 * START, places=4)
        self.assertGreaterEqual(q["suggested_cap_usd"], (q["total_usd"] + 20 * 0.005) * 1.3)

    def test_ai_check_pack_is_about_twenty_three_sixty(self):
        q = pack("ai_check")
        self.assertAlmostEqual(q["total_usd"], 270 * 0.08 + 20 * 0.10, delta=0.01)
        self.assertEqual(f"{q['total_usd']:.2f}", "23.60")


class ComputeIsInTheQuote(unittest.TestCase):
    OBSERVED = {"serp_page": 0.0028, "youtube_transcript": 0.0039, "website_contact": 0.0021}

    def test_observed_compute_is_never_under_quoted(self):
        for job, seen in self.OBSERVED.items():
            spec = tools.PRICES["jobs"][job]
            self.assertTrue(spec["usage_paid_by_caller"], job)
            self.assertGreaterEqual(spec["usage_allowance_per_unit"], seen, job)
            self.assertLessEqual(spec["usage_allowance_per_unit"], seen * 1.35, f"{job}: allowance far above what was seen")

    def test_serp_pages_include_their_compute(self):
        q = quote("serp_page", 15)
        self.assertAlmostEqual(q["total_usd"], 15 * (0.0018 + 0.003) + START, delta=0.0001)
        self.assertAlmostEqual(q["includes_compute_usd"], 15 * 0.003, places=5)
        self.assertAlmostEqual(q["lines"][0]["compute_usd"], 15 * 0.003, places=5)

    def test_one_plain_sentence_about_compute(self):
        note = quote("serp_page", 15)["compute_note"]
        self.assertIn("includes about $0.05 of Apify compute", note)
        self.assertNotIn("\n", note)

    def test_no_compute_sentence_when_there_is_none(self):
        q = quote("ai_brand_check", 10)
        self.assertIsNone(q["compute_note"])
        self.assertIsNone(q["includes_compute_usd"])
        self.assertNotIn("compute_usd", q["lines"][0])

    def test_pack_compute_is_summed(self):
        q = pack("starter")
        self.assertAlmostEqual(q["includes_compute_usd"], 15 * 0.003, places=5)
        self.assertIn("Apify compute", q["compute_note"])

    def test_jobs_with_compute_billed_to_you_but_not_measured_say_so(self):
        for job, spec in tools.PRICES["jobs"].items():
            if spec["usage_paid_by_caller"] and not (spec.get("usage_allowance_per_unit") or spec.get("usage_allowance_per_run")):
                self.assertIn("not been measured", spec["usage_note"], job)

    def test_only_actors_where_the_caller_pays_compute_have_an_allowance(self):
        for job, spec in tools.PRICES["jobs"].items():
            if spec.get("usage_allowance_per_unit") or spec.get("usage_allowance_per_run"):
                self.assertTrue(spec["usage_paid_by_caller"], job)
                self.assertTrue(spec.get("usage_note"), job)


class TheCapCoversTheWorstObservedRun(unittest.TestCase):
    # (job, units, runs, real bill of the most expensive sampled run in dollars: events plus compute)
    OBSERVED = [
        ("youtube_transcript", 50, 1, 0.25 + 0.22708),
        ("youtube_transcript", 125, 1, 0.625 + 0.50948),
        ("serp_page", 25, 1, 0.04505 + 0.06924),
        ("serp_page", 1, 1, 0.0018 + 0.00005 + 0.00373),
        ("website_contact", 25, 1, 0.12505 + 0.05175),
        ("website_contact", 1, 1, 0.00505 + 0.00077),
        ("ai_overview", 1, 1, 0.1051),  # fallback event, brand match and two start events
        ("youtube_comment", 10, 1, 0.0101 + 0.00381),
        ("ai_mode", 1, 1, 0.02505 + 0.00047),
        ("ai_page_citation", 16, 1, 1.44005 + 0.00114),
        ("quora_question", 2, 1, 0.016),
        ("review_site", 0, 1, 0.04 + 0.08864),
        ("keyword_difficulty", 1, 1, 0.3 + 0.00052),
    ]

    def test_cap_is_at_least_what_the_worst_sampled_run_cost(self):
        for job, units, runs, real in self.OBSERVED:
            q = quote(job, units, runs)
            self.assertGreaterEqual(q["suggested_cap_usd"], real, f"{job} x{units}: cap {q['suggested_cap_usd']} < real {real}")

    def test_the_quote_itself_is_at_least_the_real_bill_where_nothing_optional_happened(self):
        for job, units, runs, real in self.OBSERVED:
            if job == "ai_overview":
                continue  # the real bill includes the optional brand-match event
            q = quote(job, units, runs)
            slack = 0.001 if real < 0.05 else 0.0  # a tenth of a cent on a one-item run is not worth modelling
            self.assertGreaterEqual(q["total_usd"] + slack + 1e-9, real, f"{job} x{units}: quoted {q['total_usd']} < real {real}")

    def test_fifty_transcripts_have_a_cap_of_at_least_forty_eight_cents(self):
        self.assertGreaterEqual(quote("youtube_transcript", 50)["suggested_cap_usd"], 0.48)

    def test_cap_is_thirty_percent_above_the_total_rounded_up_to_the_cent(self):
        for job, units in (("serp_page", 15), ("youtube_transcript", 50), ("ai_brand_check", 180)):
            q = quote(job, units)
            self.assertEqual(q["suggested_cap_usd"], expected_cap(q["total_usd"]), job)

    def test_cap_has_a_one_cent_floor(self):
        self.assertGreaterEqual(quote("serp_page", 0)["suggested_cap_usd"], 0.01)


class TheHeadsUp(unittest.TestCase):
    def test_says_in_one_line_that_the_cap_may_not_count_compute_and_is_set_high_enough(self):
        text = quote("serp_page", 15)["heads_up"].lower()
        self.assertIn("compute", text)
        self.assertIn("unconfirmed", text)
        self.assertIn("30%", text)
        self.assertNotIn("tiny", text)
        self.assertNotIn("small platform", text)

    def test_no_banned_words_in_any_quote_text(self):
        q = pack("ai_check")
        blob = json.dumps([q["heads_up"], q["how_to_run"], q["compute_note"], [ln.get("note") for ln in q["lines"]]]).lower()
        for word in ("free", "open-source", "open source", "tiny", "small platform"):
            self.assertNotIn(word, blob)

    def test_output_stays_compact(self):
        q = pack("starter")
        self.assertLessEqual(set(q), {"pack", "pack_about", "lines", "total_usd", "suggested_cap_usd", "how_to_run",
                                      "prices_read_on", "heads_up", "includes_compute_usd", "compute_note", "warnings",
                                      "runnable_total_usd"})
        for line in q["lines"]:
            self.assertLessEqual(set(line), {"job", "actor", "units", "unit", "requests", "cost_usd", "compute_usd",
                                             "note", "not_before"})
        self.assertLess(len(json.dumps(q)), 2500)


class NotLiveYet(unittest.TestCase):
    def test_both_dataforseo_jobs_carry_the_date(self):
        for job in ("keyword_ideas", "keyword_volume"):
            self.assertEqual(tools.PRICES["jobs"][job]["effective_from"], "2026-11-14", job)

    def test_still_quotes_the_job_and_warns_plainly(self):
        q = quote("keyword_ideas", 100)
        self.assertAlmostEqual(q["total_usd"], 1.2 + START, delta=0.001)
        self.assertEqual(q["lines"][0]["not_before"], "2026-11-14")
        text = " ".join(q["warnings"])
        self.assertIn("2026-11-14", text)
        self.assertIn("cannot run", text)
        self.assertIn("not included in the spending cap", text)

    def test_a_job_that_cannot_run_gets_no_runnable_cap(self):
        q = quote("keyword_ideas", 100)
        self.assertEqual(q["runnable_total_usd"], 0.0)
        self.assertEqual(q["suggested_cap_usd"], 0.0)
        self.assertIn("do not run", q["how_to_run"].lower())
        self.assertNotIn("maxTotalChargeUsd = 0.0", q["how_to_run"])

    def test_a_mixed_quote_caps_only_what_can_run(self):
        q = tools.quote_cost([{"job": "serp_page", "units": 15}, {"job": "keyword_ideas", "units": 100}], None, TODAY)
        serp = quote("serp_page", 15)
        self.assertAlmostEqual(q["runnable_total_usd"], serp["total_usd"], places=4)
        self.assertEqual(q["suggested_cap_usd"], serp["suggested_cap_usd"])
        self.assertGreater(q["total_usd"], 1.2)
        self.assertIn("maxTotalChargeUsd = %s" % serp["suggested_cap_usd"], q["how_to_run"])

    def test_nothing_is_flagged_on_or_after_the_date(self):
        for day in (AFTER, dt.date(2027, 1, 1)):
            q = quote("keyword_ideas", 100, today=day)
            self.assertFalse(q.get("warnings"))
            self.assertIsNone(q.get("runnable_total_usd"))
            self.assertNotIn("not_before", q["lines"][0])
            self.assertEqual(q["suggested_cap_usd"], expected_cap(q["total_usd"]))

    def test_normal_quotes_have_no_warnings(self):
        for name in tools.PRICES["packs"]:
            q = pack(name)
            self.assertFalse(q.get("warnings"), name)
            self.assertIsNone(q.get("runnable_total_usd"), name)


class PriceFileShape(unittest.TestCase):
    def test_every_job_declares_its_events(self):
        for job, spec in tools.PRICES["jobs"].items():
            self.assertIsInstance(spec["start_events"], int, job)
            self.assertGreaterEqual(spec["start_events"], 0, job)
            self.assertTrue(spec["unit_event"], job)
            self.assertIsInstance(spec["usage_paid_by_caller"], bool, job)
            if spec["per_request"]:
                self.assertTrue(spec["request_event"], job)
            if "per_unit_worst" in spec:
                self.assertGreaterEqual(spec["per_unit_worst"], spec["per_unit"], job)
                self.assertTrue(spec["worst_event"] and spec["worst_note"], job)
            if "effective_from" in spec:
                dt.date.fromisoformat(spec["effective_from"])

    def test_extra_events_have_a_price_and_a_basis(self):
        for job, spec in tools.PRICES["jobs"].items():
            for key in ("extra_events", "optional_events"):
                for event in spec.get(key, []):
                    self.assertGreater(event["price_usd"], 0, job)
                    self.assertIn(event["basis"], ("per_unit", "per_run"), job)
                    self.assertTrue(event["event"] and event["why"], job)

    def test_the_usage_flag_is_set_on_the_eleven_measured_actors(self):
        measured = {"serp_page", "youtube_transcript", "website_contact", "keyword_difficulty", "ai_page_citation",
                    "email_verify", "ai_mode", "longtail_keyword", "review_site", "backlinks", "youtube_comment"}
        for job in measured:
            self.assertTrue(tools.PRICES["jobs"][job]["usage_paid_by_caller"], job)

    def test_pack_totals_are_recomputed_not_remembered(self):
        # these figures are written into the README, the Store page and the reference table: change them together
        expected = {"starter": 0.17, "ai_check": 23.60}
        for name, total in expected.items():
            self.assertEqual(round(pack(name)["total_usd"], 2), total, name)

    def test_models_accept_the_new_fields(self):
        try:
            import models
        except ImportError:
            self.skipTest("pydantic is not installed")
        for q in (pack("starter"), quote("keyword_ideas", 5), quote("ai_overview", 3)):
            result = models.QuoteResult(**q)
            self.assertEqual(result.total_usd, q["total_usd"])
            self.assertEqual(result.includes_compute_usd, q.get("includes_compute_usd"))


PACK_ORDER = ["starter", "keywords", "competitors", "creators", "local", "ai_check"]
RAW_ERROR_WORDS = ("validation error", "pydantic", "literal_error", "input_value", "Input should be", "errors.pydantic.dev")


class UnknownPackNameTests(unittest.TestCase):
    """A wrong pack name is a plain sentence that lists the valid names, never raw validation text."""

    def test_the_function_error_lists_the_valid_names_in_the_documented_order(self):
        with self.assertRaises(ValueError) as caught:
            tools.quote_cost(None, "bogus")
        message = str(caught.exception)
        self.assertIn("'bogus'", message)
        self.assertIn(", ".join(PACK_ORDER), message)
        for word in RAW_ERROR_WORDS:
            self.assertNotIn(word, message)

    def test_pack_names_are_forgiving_about_case_and_spaces(self):
        self.assertEqual(tools.quote_cost(None, " Starter ")["pack"], "starter")
        self.assertEqual(tools.quote_cost(None, "AI_CHECK")["pack"], "ai_check")

    def test_a_blank_pack_name_means_no_pack(self):
        with self.assertRaises(ValueError) as caught:
            tools.quote_cost(None, "   ")
        self.assertIn("pack name", str(caught.exception))

    def test_a_pack_name_that_is_not_text_gets_a_plain_error(self):
        with self.assertRaises(ValueError) as caught:
            tools.quote_cost(None, 5)
        self.assertIn(", ".join(PACK_ORDER), str(caught.exception))

    def test_a_pack_and_items_together_are_still_refused(self):
        with self.assertRaises(ValueError) as caught:
            tools.quote_cost([{"job": "serp_page", "units": 1}], "starter")
        self.assertIn("either a pack or items", str(caught.exception))


@unittest.skipUnless(all(__import__("importlib.util").util.find_spec(m) for m in ("mcp", "pydantic")),
                     "mcp and pydantic are not installed")
class UnknownPackNameThroughTheToolTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import server
        self.mcp = server.build_server()

    def call(self, **arguments):
        import asyncio
        return asyncio.run(self.mcp.call_tool("quote_cost", arguments))

    def test_a_wrong_pack_name_comes_back_as_a_plain_sentence(self):
        from mcp.server.mcpserver.exceptions import ToolError
        with self.assertRaises(ToolError) as caught:
            self.call(pack="bogus")
        message = str(caught.exception)
        self.assertIn(", ".join(PACK_ORDER), message)
        for word in RAW_ERROR_WORDS:
            self.assertNotIn(word, message)

    def test_a_right_pack_name_still_works(self):
        result = self.call(pack="starter")
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["pack"], "starter")

    def test_the_pack_names_stay_visible_to_clients_in_the_served_schema(self):
        import asyncio
        tool = next(t for t in asyncio.run(self.mcp.list_tools()) if t.name == "quote_cost")
        schema = tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema
        pack = schema["properties"]["pack"]
        enums = [branch["enum"] for branch in pack["anyOf"] if "enum" in branch]
        self.assertEqual([sorted(e) for e in enums], [sorted(PACK_ORDER)])
        self.assertIn({"type": "null"}, pack["anyOf"])
        self.assertNotIn("pack", schema.get("required", []))


if __name__ == "__main__":
    unittest.main()
