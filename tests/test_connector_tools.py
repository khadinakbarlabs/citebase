"""Tests for the connector's tool logic (connector/tools.py). Needs no MCP library."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools  # noqa: E402
from test_site_audit import ServerCase  # noqa: E402


class PlaybookTests(unittest.TestCase):
    def test_index_lists_every_skill_and_reference(self):
        names = {p["name"] for p in tools.get_playbook()["playbooks"]}
        for expected in ("start", "citation-loop", "outreach", "seo-audit", "checklist-onpage", "outreach-playbook",
                         "tools-and-apis", "measurement"):
            self.assertIn(expected, names)

    def test_index_includes_the_get_cited_journey(self):
        out = tools.get_playbook()
        self.assertEqual(out["start_here"], "start")
        self.assertGreaterEqual(len(out["journey"]), 3)
        self.assertEqual(out["journey"][0]["playbook"], "start")
        self.assertTrue(any("audit_site" in step["do"] for step in out["journey"]))
        self.assertEqual(out["featured"][0], "start")
        self.assertEqual(out["playbooks"][0]["name"], "start")

    def test_skill_text_has_web_note_and_no_frontmatter(self):
        text = tools.get_playbook("start")["text"]
        self.assertTrue(text.startswith("WEB MODE"))
        self.assertNotIn("\nname: start", text)
        self.assertIn("audit_site", text)
        self.assertIn("next_steps", text)

    def test_core_skills_name_their_web_tools(self):
        """Product path skills must tell web agents which connector tools to call (not only Actor IDs)."""
        required = {
            "start": ("audit_site", "next_steps", "quote_cost", "ai_check"),
            "ai-search-visibility": ("quote_cost", "ai_check", "call-actor", "audit_site", "next_steps"),
            "citation-loop": ("quote_cost", "ai_check", "import_ai_results", "measure_recommendation_share"),
            "seo-audit": ("audit_site", "next_steps", "quote_cost"),
            "seo-checklists": ("audit_site", "next_steps"),
            "outreach": ("check_outreach_draft",),
            "creator-outreach": ("quote_cost", "creators", "check_outreach_draft"),
            "link-building": ("quote_cost", "call-actor", "check_outreach_draft"),
            "press-release": ("quote_cost", "check_outreach_draft"),
            "competitor-research": ("quote_cost", "competitors", "call-actor"),
            "keyword-research": ("quote_cost", "keywords", "call-actor"),
            "ai-content-check": ("check_ai_content",),
            "humanize-content": ("check_ai_content",),
            "eeat-audit": ("check_ai_content",),
            "content-optimize": ("check_ai_content", "quote_cost"),
            "content-brief": ("quote_cost", "keywords"),
            "programmatic-seo": ("check_ai_content", "quote_cost"),
            "entity-seo": ("quote_cost", "audit_site"),
            "platform-presence": ("quote_cost", "call-actor"),
            "directory-listings": ("quote_cost", "call-actor"),
            "social-content": ("quote_cost", "check_ai_content"),
            "social-listening": ("quote_cost", "call-actor"),
        }
        for name, needles in required.items():
            text = tools.get_playbook(name)["text"]
            self.assertIn("## Web connector mode", text, name)
            for needle in needles:
                self.assertIn(needle, text, f"{name} missing {needle}")
        self.assertEqual(set(required), {p["name"] for p in tools.get_playbook()["playbooks"] if p["kind"] == "skill"})
        self.assertIn("next_steps", tools.WEB_NOTE)
        self.assertIn("ai_check", tools.WEB_NOTE)

    def test_reference_text_is_returned_without_web_note(self):
        self.assertFalse(tools.get_playbook("measurement")["text"].startswith("WEB MODE"))

    def test_unknown_names_and_path_tricks_are_refused(self):
        for bad in ("nope", "../README", "../../etc/passwd", "skills/start/SKILL", ""):
            if bad == "":
                continue
            with self.assertRaises(ValueError, msg=bad) as ctx:
                tools.get_playbook(bad)
            self.assertIn("get_playbook", str(ctx.exception))


class QuoteTests(unittest.TestCase):
    def test_serp_quote_and_cap(self):
        q = tools.quote_cost([{"job": "serp_page", "units": 15}])
        self.assertAlmostEqual(q["total_usd"], 0.0721, places=4)  # 15 pages x ($0.0018 + about $0.003 of Apify compute) + start fee
        self.assertEqual(q["suggested_cap_usd"], 0.1)
        self.assertIn("maxTotalChargeUsd = 0.1", q["how_to_run"])

    def test_request_fee_is_counted_once_per_request(self):
        q = tools.quote_cost([{"job": "keyword_ideas", "units": 100, "requests": 1}])
        self.assertAlmostEqual(q["total_usd"], 1.2001, places=3)
        two = tools.quote_cost([{"job": "keyword_ideas", "units": 100, "requests": 2}])
        self.assertGreater(two["total_usd"], q["total_usd"] + 0.19)

    def test_zero_units_cost_only_the_start_fee(self):
        self.assertLess(tools.quote_cost([{"job": "keyword_volume", "units": 0}])["total_usd"], 0.001)

    def test_cap_is_at_least_thirty_percent_above_total(self):
        q = tools.quote_cost([{"job": "ai_brand_check", "units": 180}, {"job": "ai_overview", "units": 20}])
        self.assertGreaterEqual(q["suggested_cap_usd"], q["total_usd"] * 1.3)
        self.assertAlmostEqual(q["total_usd"], 16.4002, places=3)  # 180 x $0.08 + 20 x $0.10 fallback rate + start fees

    def test_ai_check_pack_is_big_enough_for_the_measurement_minimums(self):
        """A user who buys the pack must not get 'fewer than 20 buying questions' on the first report."""
        pack = {i["job"]: i["units"] for i in tools.PRICES["packs"]["ai_check"]["items"]}
        questions = tools.cl.MIN_PROMPTS + tools.cl.MIN_CONTROLS
        self.assertGreaterEqual(pack["ai_brand_check"], questions * 3 * tools.cl.MIN_REPEATS)
        self.assertGreaterEqual(pack["ai_overview"], tools.cl.MIN_PROMPTS)
        self.assertIn(str(questions + 5), tools.PRICES["packs"]["ai_check"]["about"])

    def test_bad_input_gets_a_helpful_error(self):
        for bad in ([], [{"job": "unknown", "units": 1}], [{"job": "serp_page", "units": -1}],
                    [{"job": "serp_page", "units": "lots"}]):
            with self.assertRaises(ValueError):
                tools.quote_cost(bad)

    def test_every_priced_actor_is_named_in_the_plugin_reference(self):
        # the prices themselves are compared in test_prices_doc_sync.py
        with open(os.path.join(ROOT, "references", "tools-and-apis.md"), encoding="utf-8") as fh:
            ref = fh.read()
        for job, spec in tools.PRICES["jobs"].items():
            self.assertIn(spec["actor"], ref, job)


class PackTests(unittest.TestCase):
    def test_every_pack_prices_and_uses_known_jobs(self):
        for name, spec in tools.PRICES["packs"].items():
            q = tools.quote_cost(None, name)
            self.assertEqual(q["pack"], name)
            self.assertGreater(q["total_usd"], 0)
            self.assertTrue(spec["about"].endswith("."), name)
            for item in spec["items"]:
                self.assertIn(item["job"], tools.PRICES["jobs"], f"{name}: {item['job']}")

    def test_pack_and_items_together_are_refused(self):
        with self.assertRaises(ValueError):
            tools.quote_cost([{"job": "serp_page", "units": 1}], "starter")

    def test_unknown_pack_lists_valid_ones(self):
        with self.assertRaises(ValueError) as e:
            tools.quote_cost(None, "nope")
        self.assertIn("starter", str(e.exception))

    def test_starter_is_cheap_enough_for_a_beginner(self):
        self.assertLess(tools.quote_cost(None, "starter")["total_usd"], 0.25)

    def test_only_public_khadinakbar_actors_are_priced(self):
        for job, spec in tools.PRICES["jobs"].items():
            self.assertTrue(spec["actor"].startswith("khadinakbar/"), job)


class MeasureTests(unittest.TestCase):
    def data(self, after_hits, total=24):
        panel = [{"prompt_id": f"p{n:03d}", "prompt": f"best tool {n}", "type": "consideration"} for n in range(1, total + 1)]
        panel += [{"prompt_id": f"p{total + n:03d}", "prompt": f"control {n}", "type": "control"} for n in range(1, 5)]
        runs = []
        for snap, hits in (("baseline", {"p001", "p002"}), ("after", after_hits)):
            for p in panel:
                for engine in ("chatgpt", "perplexity"):
                    for rep in (1, 2, 3):
                        hit = p["prompt_id"] in hits
                        runs.append({"snapshot": snap, "prompt_id": p["prompt_id"], "platform": engine, "repeat": rep,
                                     "mentioned": hit, "cited": hit, "recommended": hit,
                                     "date": "2026-11-01" if snap == "baseline" else "2026-12-01"})
        return panel, runs

    def test_improvement_is_reported(self):
        panel, runs = self.data({f"p{n:03d}" for n in range(1, 13)})
        exp = [{"action": "Joined two listicles", "mechanism": "listicle", "date": "2026-11-15",  # between the two rounds
                "target_prompt_ids": ",".join(f"p{n:03d}" for n in range(3, 13))}]
        rep = tools.measure(panel, runs, "baseline", "after", exp)
        self.assertEqual(rep["change"]["all"]["verdict"], "improved")
        self.assertEqual(rep["experiments"][0]["result"]["verdict"], "supported")
        self.assertIn("Recommendation Share", rep["markdown"])
        self.assertEqual(rep["due"], [])

    def test_bad_inputs_have_clear_errors(self):
        panel, runs = self.data({"p001"})
        with self.assertRaises(ValueError):
            tools.measure(panel, [dict(runs[0], prompt_id="p999")] + runs[1:])
        with self.assertRaises(ValueError):
            tools.measure(panel, [{k: v for k, v in runs[0].items() if k != "snapshot"}])
        with self.assertRaises(ValueError):
            tools.measure(panel, runs + [runs[0]])
        with self.assertRaises(ValueError):
            tools.measure([{"prompt_id": "x", "prompt": "y", "type": "bogus"}], runs)
        with self.assertRaises(ValueError):
            tools.measure(panel, [])


class NextStepsTests(unittest.TestCase):
    audit = {"problems": [
        {"level": "warn", "check": "Meta description present", "detail": "3 missing"},
        {"level": "fail", "check": "Search + AI crawler access (robots.txt)", "detail": "Blocked: GPTBot"},
        {"level": "fail", "check": "Some brand new check", "detail": "odd"}]}

    def test_failures_come_first_in_plain_words(self):
        steps = tools.next_steps(self.audit)["steps"]
        self.assertEqual(steps[0]["urgency"], "do first")
        self.assertIn("Let search engines and AI answer tools read your site", [s["step"] for s in steps])
        self.assertTrue(all(s["who"] and s["effort"] for s in steps))

    def test_unknown_checks_still_produce_a_step(self):
        steps = tools.next_steps(self.audit)["steps"]
        self.assertTrue(any("brand new check" in s["step"] for s in steps))

    def test_always_ends_with_a_recheck_reminder(self):
        self.assertEqual(tools.next_steps(None)["steps"][-1]["step"], "Check again in 30 days")

    def test_empty_call_offers_site_check_and_ai_path(self):
        steps = tools.next_steps(None)["steps"]
        texts = [s["step"] for s in steps]
        self.assertTrue(any("website" in t.lower() for t in texts))
        self.assertTrue(any("AI assistants recommend" in t for t in texts))
        self.assertIn("quote", tools.next_steps(None)["tip"].lower())

    def test_audit_without_report_offers_an_ai_recommend_check(self):
        steps = tools.next_steps(self.audit)["steps"]
        self.assertTrue(any("AI assistants recommend" in s["step"] for s in steps))
        self.assertIn("quote", tools.next_steps(self.audit)["tip"].lower())

    def test_ai_recommend_survives_many_site_problems(self):
        audit = {"problems": [{"level": "warn", "check": f"x{i}", "detail": ""} for i in range(20)]}
        steps = tools.next_steps(audit, max_steps=5)["steps"]
        self.assertTrue(any("AI assistants recommend" in s["step"] for s in steps))
        self.assertTrue(any(s["based_on"] == "product goal: get cited by AI" for s in steps))

    def test_low_recommendation_share_adds_a_step(self):
        report = {"summary": {"all": {"recommendation_share": 0.05, "control_false_positive": None}}, "due": []}
        steps = tools.next_steps(None, report)["steps"]
        self.assertTrue(any("pages AI already trusts" in s["step"] for s in steps))

    def test_max_steps_is_respected(self):
        audit = {"problems": [{"level": "warn", "check": f"x{i}", "detail": ""} for i in range(20)]}
        self.assertLessEqual(len(tools.next_steps(audit, max_steps=3)["steps"]), 4)


class OutreachCheckTests(unittest.TestCase):
    good = ("Hi Sam, I read your piece on small-business payroll and liked the point about hidden fees. We published "
            "a 2026 comparison of payroll costs across 40 providers, with the raw numbers, that your readers "
            "might find useful as a source. Happy to send the data or answer questions. If this isn't relevant, "
            "just tell me and I won't write again.\n\nThanks,\nAlex Rivera\nAcme Payroll Data, 123 Main Street, Austin, TX 78701")

    def test_good_email_is_ready(self):
        r = tools.check_outreach_draft("sam@example.com", "Payroll cost data for your piece", self.good)
        self.assertTrue(r["ready"], r)
        self.assertEqual(len(r["fingerprint"]), 12)

    def test_problems_block_readiness(self):
        cases = [("sam@example.com", "Hi", "Hello [Name], quick note. " * 5, "bracket"),
                 ("not-an-email", "Hi", self.good, "plain address"),
                 ("sam@example.com", "Hi", "", "empty")]
        for to, subj, body, word in cases:
            r = tools.check_outreach_draft(to, subj, body)
            self.assertFalse(r["ready"], word)
            self.assertTrue(any(word in p for p in r["problems"]), (word, r["problems"]))

    def test_suppressed_and_daily_limit(self):
        r = tools.check_outreach_draft("sam@mail.example.com", "Hi there", self.good, suppressed=["example.com"])
        self.assertFalse(r["ready"])
        r = tools.check_outreach_draft("sam@example.com", "Hi there", self.good, sent_today=20, daily_cap=20)
        self.assertFalse(r["ready"])

    def test_warnings_do_not_block(self):
        body = ("Guaranteed results. Click here https://a.com https://b.com https://c.com. If this is not for you, "
                "reply STOP and I will not write again.\n\nAlex Rivera\nAcme Payroll Data\nacme.example")
        r = tools.check_outreach_draft("sam@example.com", "ACT NOW!!", body)
        self.assertTrue(r["ready"], r["problems"])
        self.assertGreaterEqual(len(r["warnings"]), 3)

    def test_fingerprint_ignores_spacing_but_not_wording(self):
        a = tools.check_outreach_draft("sam@example.com", "Hi there", self.good)["fingerprint"]
        b = tools.check_outreach_draft("SAM@example.com", " Hi   there ", self.good.replace(" ", "  "))["fingerprint"]
        c = tools.check_outreach_draft("sam@example.com", "Hi there", self.good + " P.S. buy")["fingerprint"]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class AuditToolTests(ServerCase):
    def test_audit_returns_plain_summary(self):
        out = tools.run_audit(self.base, 5)
        self.assertEqual(out["pages_checked"], 3)
        self.assertIsInstance(out["health_score"], int)
        self.assertTrue(out["problems"])
        self.assertIn("no JavaScript", out["limits"])
        json.dumps(out)  # must be JSON-serialisable for MCP

    def test_bad_urls_and_private_addresses_are_refused(self):
        with self.assertRaises(ValueError):
            tools.run_audit("   ")
        import site_audit
        site_audit.ALLOW_PRIVATE = False
        with self.assertRaises(ValueError) as ctx:
            tools.run_audit(self.base, 3)
        self.assertIn("Cannot reach", str(ctx.exception))

    def test_page_limit_is_clamped(self):
        self.assertEqual(tools.run_audit(self.base, 999)["pages_checked"], 3)


if __name__ == "__main__":
    unittest.main()
