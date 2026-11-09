"""scripts/check_prices.py compares connector/prices.json with the live public pricing of each Actor.

These tests use small fixtures shaped like the Apify API's GET /v2/acts/{id} answer. They never touch the network and
never read a real token.
"""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import check_prices as cp  # noqa: E402

TODAY = dt.date(2026, 11, 8)
START = 5e-05


def entry(events, usage=False, started="2026-01-01T00:00:00.000Z"):
    return {"pricingModel": "PAY_PER_EVENT", "startedAt": started, "isPPEPlatformUsagePaidByUser": usage,
            "pricingPerEvent": {"actorChargeEvents": {k: {"eventPriceUsd": v} for k, v in events.items()}}}


def actor(events, usage=False, mem=512, extra_entries=()):
    return {"data": {"defaultRunOptions": {"memoryMbytes": mem},
                     "pricingInfos": [entry(events, usage), *extra_entries]}}


SERP_SPEC = {"actor": "khadinakbar/scrape-google-serp", "unit": "SERP page", "per_unit": 0.0018, "per_request": 0.0,
             "unit_event": "scraped-serp-page", "start_events": 1, "usage_paid_by_caller": True}
SERP_LIVE = {"scraped-serp-page": 0.0018, "apify-actor-start": START}


def statuses(rows):
    return {(r["field"], r["status"]) for r in rows}


def drifts(rows):
    return [r for r in rows if r["status"] == "DRIFT"]


class LivePricing(unittest.TestCase):
    def test_current_entry_is_the_latest_one_that_has_started(self):
        data = actor(SERP_LIVE)["data"]
        data["pricingInfos"] = [entry({"a": 3}, started="2026-12-01T00:00:00.000Z"),
                                entry({"a": 2}, started="2026-06-01T00:00:00.000Z"),
                                entry({"a": 1}, started="2026-01-01T00:00:00.000Z")]
        current, future = cp.live_pricing(data, TODAY)
        self.assertEqual(cp.event_prices(current), {"a": 2})
        self.assertEqual(list(future), [dt.date(2026, 12, 1)])
        self.assertEqual(cp.event_prices(future[dt.date(2026, 12, 1)]), {"a": 3})

    def test_an_entry_starting_today_counts_as_current(self):
        data = {"pricingInfos": [entry({"a": 1}, started="2026-11-08T00:00:00.000Z")]}
        current, future = cp.live_pricing(data, TODAY)
        self.assertEqual(cp.event_prices(current), {"a": 1})
        self.assertEqual(future, {})

    def test_an_actor_without_pay_per_event_pricing_has_no_events(self):
        data = {"pricingInfos": [{"pricingModel": "FREE", "startedAt": "2026-01-01T00:00:00.000Z"}]}
        current, _ = cp.live_pricing(data, TODAY)
        self.assertEqual(cp.event_prices(current), {})


class OneJob(unittest.TestCase):
    def check(self, spec, live, today=TODAY, fee=START):
        return cp.check_job("serp_page", spec, live, today, fee)

    def test_a_matching_job_has_no_drift(self):
        rows = self.check(SERP_SPEC, actor(SERP_LIVE, usage=True))
        self.assertEqual(drifts(rows), [])
        self.assertIn(("unit price", "ok"), statuses(rows))

    def test_unit_price_change_is_drift(self):
        rows = self.check(SERP_SPEC, actor({**SERP_LIVE, "scraped-serp-page": 0.002}, usage=True))
        bad = drifts(rows)
        self.assertEqual([r["field"] for r in bad], ["unit price"])
        self.assertEqual((bad[0]["quote"], bad[0]["live"]), (0.0018, 0.002))

    def test_unit_event_gone_is_drift(self):
        rows = self.check(SERP_SPEC, actor({"apify-actor-start": START}, usage=True))
        self.assertEqual([r["field"] for r in drifts(rows)], ["unit price"])
        self.assertIsNone(drifts(rows)[0]["live"])

    def test_request_fee_is_compared(self):
        spec = {**SERP_SPEC, "per_request": 0.05, "request_event": "backlink-api-request"}
        live = actor({**SERP_LIVE, "backlink-api-request": 0.05}, usage=True)
        self.assertEqual(drifts(self.check(spec, live)), [])
        live = actor({**SERP_LIVE, "backlink-api-request": 0.06}, usage=True)
        self.assertEqual([r["field"] for r in drifts(self.check(spec, live))], ["request fee"])

    def test_start_event_price_is_compared_to_the_jobs_own_start_fee(self):
        spec = {**SERP_SPEC, "start_fee_usd": 0.005}
        live = actor({**SERP_LIVE, "apify-actor-start": 0.005}, usage=True)
        self.assertEqual(drifts(self.check(spec, live)), [])
        self.assertEqual([r["field"] for r in drifts(self.check(SERP_SPEC, live))], ["start fee"])

    def test_start_event_that_disappeared_is_drift(self):
        rows = self.check(SERP_SPEC, actor({"scraped-serp-page": 0.0018}, usage=True))
        self.assertEqual([r["field"] for r in drifts(rows)], ["start fee"])

    def test_start_event_that_appeared_where_the_quote_has_none_is_drift(self):
        spec = {**SERP_SPEC, "start_events": 0}
        rows = self.check(spec, actor(SERP_LIVE, usage=True))
        self.assertEqual([r["field"] for r in drifts(rows)], ["start events"])

    def test_no_start_event_on_either_side_is_fine(self):
        spec = {**SERP_SPEC, "start_events": 0}
        rows = self.check(spec, actor({"scraped-serp-page": 0.0018}, usage=True))
        self.assertEqual(drifts(rows), [])

    def test_more_memory_means_more_start_events(self):
        rows = self.check(SERP_SPEC, actor(SERP_LIVE, usage=True, mem=4096))
        bad = drifts(rows)
        self.assertEqual([r["field"] for r in bad], ["start events"])
        self.assertEqual((bad[0]["quote"], bad[0]["live"]), (1, 4))
        self.assertEqual(drifts(self.check({**SERP_SPEC, "start_events": 4}, actor(SERP_LIVE, usage=True, mem=4096))), [])

    def test_a_quote_with_more_start_events_than_live_memory_needs_is_cautious_not_drift(self):
        self.assertEqual(drifts(self.check({**SERP_SPEC, "start_events": 4}, actor(SERP_LIVE, usage=True, mem=256))), [])

    def test_compute_billing_flag_flip_is_drift_both_ways(self):
        rows = self.check(SERP_SPEC, actor(SERP_LIVE, usage=False))
        self.assertEqual([r["field"] for r in drifts(rows)], ["compute billed to you"])
        rows = self.check({**SERP_SPEC, "usage_paid_by_caller": False}, actor(SERP_LIVE, usage=True))
        self.assertEqual([r["field"] for r in drifts(rows)], ["compute billed to you"])

    def test_worst_case_event_is_compared(self):
        spec = {**SERP_SPEC, "per_unit_worst": 0.1, "worst_event": "fallback"}
        good = actor({**SERP_LIVE, "fallback": 0.1}, usage=True)
        self.assertEqual(drifts(self.check(spec, good)), [])
        bad = actor({**SERP_LIVE, "fallback": 0.2}, usage=True)
        self.assertEqual([r["field"] for r in drifts(self.check(spec, bad))], ["worst-case price"])

    def test_extra_and_optional_events_are_compared(self):
        spec = {**SERP_SPEC,
                "extra_events": [{"event": "card", "price_usd": 0.01, "basis": "per_run", "count": 2, "why": "x"}],
                "optional_events": [{"event": "match", "price_usd": 0.005, "basis": "per_unit", "why": "y"}]}
        live = actor({**SERP_LIVE, "card": 0.01, "match": 0.005}, usage=True)
        self.assertEqual(drifts(self.check(spec, live)), [])
        live = actor({**SERP_LIVE, "card": 0.02, "match": 0.005}, usage=True)
        self.assertEqual([r["field"] for r in drifts(self.check(spec, live))], ["extra event card"])

    def test_known_but_unpriced_events_are_noted_and_checked(self):
        spec = {**SERP_SPEC, "other_events": [{"event": "full-text", "price_usd": 0.005, "why": "z"}]}
        live = actor({**SERP_LIVE, "full-text": 0.005}, usage=True)
        self.assertEqual(drifts(self.check(spec, live)), [])
        live = actor({**SERP_LIVE, "full-text": 0.009}, usage=True)
        self.assertEqual([r["field"] for r in drifts(self.check(spec, live))], ["other event full-text"])

    def test_an_event_the_quote_does_not_know_about_is_drift(self):
        rows = self.check(SERP_SPEC, actor({**SERP_LIVE, "surprise": 1.0}, usage=True))
        bad = drifts(rows)
        self.assertEqual([r["field"] for r in bad], ["unknown event surprise"])
        self.assertEqual(bad[0]["live"], 1.0)

    def test_another_pricing_model_is_drift(self):
        data = {"data": {"defaultRunOptions": {}, "pricingInfos": [
            {"pricingModel": "PRICE_PER_DATASET_ITEM", "startedAt": "2026-01-01T00:00:00.000Z"}]}}
        self.assertIn("pricing model", [r["field"] for r in drifts(self.check(SERP_SPEC, data))])


class FuturePrices(unittest.TestCase):
    SPEC = {**SERP_SPEC, "per_request": 0.2, "request_event": "ideas-request", "effective_from": "2026-11-14"}
    FUTURE = entry({**SERP_LIVE, "ideas-request": 0.2}, usage=True, started="2026-11-14T03:40:55.997Z")

    def test_a_declared_future_fee_is_checked_against_the_future_entry(self):
        live = actor(SERP_LIVE, usage=True, extra_entries=[self.FUTURE])
        rows = cp.check_job("keyword_ideas", self.SPEC, live, TODAY, START)
        self.assertEqual(drifts(rows), [])
        self.assertIn(("request fee", "ok"), statuses(rows))

    def test_a_declared_future_date_with_no_future_entry_is_drift(self):
        rows = cp.check_job("keyword_ideas", self.SPEC, actor(SERP_LIVE, usage=True), TODAY, START)
        self.assertIn("effective date", [r["field"] for r in drifts(rows)])

    def test_a_future_entry_on_another_date_is_drift(self):
        other = entry({**SERP_LIVE, "ideas-request": 0.2}, usage=True, started="2026-12-01T00:00:00.000Z")
        rows = cp.check_job("keyword_ideas", self.SPEC, actor(SERP_LIVE, usage=True, extra_entries=[other]), TODAY, START)
        self.assertIn("effective date", [r["field"] for r in drifts(rows)])

    def test_an_undeclared_future_price_change_is_drift(self):
        live = actor(SERP_LIVE, usage=True, extra_entries=[self.FUTURE])
        rows = cp.check_job("serp_page", SERP_SPEC, live, TODAY, START)
        self.assertIn("coming change", [r["field"] for r in drifts(rows)])

    def test_after_the_date_the_fee_must_be_in_the_current_entry(self):
        later = dt.date(2026, 11, 15)
        live = {"data": {"defaultRunOptions": {"memoryMbytes": 512}, "pricingInfos": [
            entry(SERP_LIVE, usage=True, started="2026-01-01T00:00:00.000Z"), self.FUTURE]}}
        spec = {k: v for k, v in self.SPEC.items() if k != "effective_from"}
        self.assertEqual(drifts(cp.check_job("keyword_ideas", spec, live, later, START)), [])
        # still declaring a date that has passed is allowed: the date is history by then
        self.assertEqual(drifts(cp.check_job("keyword_ideas", self.SPEC, live, later, START)), [])
        # but a quote with the fee missing from what is live now is drift
        live_without = actor(SERP_LIVE, usage=True)
        self.assertIn("request fee", [r["field"] for r in drifts(cp.check_job("keyword_ideas", spec, live_without, later, START))])


class WholeFile(unittest.TestCase):
    PRICES = {"start_fee_usd": START, "jobs": {
        "a": {**SERP_SPEC},
        "b": {**SERP_SPEC, "per_unit": 0.1, "unit_event": "other", "per_request": 0.5, "request_event": "req"}}}

    def live(self, **events):
        return {"khadinakbar/scrape-google-serp": actor({**SERP_LIVE, "other": 0.1, "req": 0.5, **events}, usage=True)}

    def test_two_jobs_on_one_actor_share_their_known_events(self):
        rows = cp.compare(self.PRICES, self.live(), TODAY)
        self.assertEqual(drifts(rows), [])
        self.assertEqual({r["job"] for r in rows}, {"a", "b"})

    def test_a_missing_actor_is_an_error_row_not_a_crash(self):
        rows = cp.compare(self.PRICES, {}, TODAY)
        self.assertTrue(rows)
        self.assertEqual({r["status"] for r in rows}, {"ERROR"})

    def test_a_failed_fetch_is_an_error_row(self):
        rows = cp.compare(self.PRICES, {"khadinakbar/scrape-google-serp": RuntimeError("HTTP 500")}, TODAY)
        self.assertEqual({r["status"] for r in rows}, {"ERROR"})
        self.assertIn("HTTP 500", rows[0]["live"])

    def test_the_real_prices_file_loads_and_every_job_is_checkable(self):
        prices = cp.load_prices()
        rows = cp.compare(prices, {}, TODAY)
        self.assertEqual({r["job"] for r in rows}, set(prices["jobs"]))

    def test_render_shows_only_drift_unless_asked(self):
        rows = cp.compare(self.PRICES, self.live(), TODAY)
        self.assertIn("No drift", cp.render(rows))
        rows = cp.compare(self.PRICES, self.live(**{"scraped-serp-page": 0.003}), TODAY)
        text = cp.render(rows)
        self.assertIn("DRIFT", text)
        self.assertIn("unit price", text)
        self.assertIn("0.0018", text)
        self.assertIn("0.003", text)
        self.assertNotIn("\nok ", text)
        self.assertIn("\nok ", cp.render(rows, show_all=True))


class CommandLine(unittest.TestCase):
    PRICES = {"read_on": "2026-11-08", "start_fee_usd": START, "jobs": {"serp_page": SERP_SPEC}}

    def run_main(self, fetch, argv=(), prices=None, env=None):
        buf = io.StringIO()
        code = cp.main(list(argv), fetch=fetch, prices=prices or self.PRICES, today=TODAY, out=buf, env=env or {})
        return code, buf.getvalue()

    def test_exit_zero_when_nothing_drifted(self):
        code, text = self.run_main(lambda name: actor(SERP_LIVE, usage=True))
        self.assertEqual(code, 0)
        self.assertIn("No drift", text)

    def test_exit_one_on_drift(self):
        code, text = self.run_main(lambda name: actor({**SERP_LIVE, "scraped-serp-page": 0.01}, usage=True))
        self.assertEqual(code, 1)
        self.assertIn("DRIFT", text)

    def test_exit_two_when_an_actor_cannot_be_read(self):
        def fetch(name):
            raise RuntimeError("could not reach Apify")
        code, text = self.run_main(fetch)
        self.assertEqual(code, 2)
        self.assertIn("could not reach Apify", text)

    def test_drift_wins_over_errors(self):
        prices = {**self.PRICES, "jobs": {"serp_page": SERP_SPEC, "gone": {**SERP_SPEC, "actor": "khadinakbar/gone"}}}

        def flaky(name):
            if name.endswith("gone"):
                raise RuntimeError("HTTP 404")
            return actor({**SERP_LIVE, "scraped-serp-page": 0.01}, usage=True)
        code, _ = self.run_main(flaky, prices=prices)
        self.assertEqual(code, 1)

    def test_each_actor_is_fetched_once(self):
        calls = []

        def fetch(name):
            calls.append(name)
            return actor({**SERP_LIVE, "other": 0.1}, usage=True)
        prices = {**self.PRICES, "jobs": {"a": SERP_SPEC, "b": {**SERP_SPEC, "unit_event": "other", "per_unit": 0.1}}}
        self.run_main(fetch, prices=prices)
        self.assertEqual(calls, ["khadinakbar/scrape-google-serp"])

    def test_json_output_option(self):
        code, text = self.run_main(lambda name: actor({**SERP_LIVE, "scraped-serp-page": 0.01}, usage=True), ["--json"])
        rows = json.loads(text)
        self.assertEqual(code, 1)
        self.assertTrue(any(r["status"] == "DRIFT" for r in rows))

    def test_all_option_lists_matching_rows(self):
        _, text = self.run_main(lambda name: actor(SERP_LIVE, usage=True), ["--all"])
        self.assertIn("\nok ", text)


class TokenHandling(unittest.TestCase):
    def test_environment_wins_over_the_file(self):
        self.assertEqual(cp.read_token({"APIFY_TOKEN": "from-env"}, "/nonexistent/apify-token.txt"), "from-env")

    def test_missing_token_is_none_not_an_error(self):
        self.assertIsNone(cp.read_token({}, "/nonexistent/apify-token.txt"))

    def test_file_token_is_stripped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("  file-token \n")
        try:
            self.assertEqual(cp.read_token({}, fh.name), "file-token")
        finally:
            os.unlink(fh.name)

    def test_the_token_never_appears_on_the_curl_command_line(self):
        seen = {}

        class Done:
            returncode = 0
            stdout = json.dumps({"data": {"ok": True}})
            stderr = ""

        def fake_run(args, **kwargs):
            seen["args"] = list(args)
            seen["input"] = kwargs.get("input")
            return Done()

        out = cp.curl_get("https://api.apify.com/v2/acts/khadinakbar~x", "s3cret-token", runner=fake_run)
        self.assertEqual(out, {"data": {"ok": True}})
        self.assertEqual(seen["args"][0], "curl")
        self.assertNotIn("s3cret-token", " ".join(seen["args"]))
        self.assertIn("s3cret-token", seen["input"])  # handed over on stdin only
        self.assertIn("-K", seen["args"])

    def test_only_api_apify_com_is_ever_requested(self):
        for url in ("https://example.com/v2/acts/x", "http://api.apify.com/v2/acts/x"):
            with self.assertRaises(ValueError):
                cp.curl_get(url, "t", runner=lambda *a, **k: None)

    def test_a_failed_curl_raises_without_the_token_in_the_message(self):
        class Bad:
            returncode = 22
            stdout = ""
            stderr = "curl: (22) The requested URL returned error: 404"

        with self.assertRaises(RuntimeError) as ctx:
            cp.curl_get("https://api.apify.com/v2/acts/x", "s3cret-token", runner=lambda *a, **k: Bad())
        self.assertNotIn("s3cret-token", str(ctx.exception))

    def test_the_token_is_not_printed_by_main(self):
        buf = io.StringIO()
        prices = {"start_fee_usd": START, "jobs": {"serp_page": SERP_SPEC}}
        cp.main(["--all"], fetch=lambda n: actor(SERP_LIVE, usage=True), prices=prices, today=TODAY, out=buf,
                env={"APIFY_TOKEN": "s3cret-token"})
        self.assertNotIn("s3cret-token", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
