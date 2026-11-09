"""Connector hardening: odd numbers, the outreach check's hard rules, and the fixed safety sentences."""
import ast
import asyncio
import json
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
import runner  # noqa: E402
import tools  # noqa: E402

SETUP_URL = ("https://mcp.apify.com/?actors=khadinakbar/citebase&tools=fetch-actor-details,call-actor,"
             "get-actor-run,get-dataset-items,get-key-value-store-record,abort-actor-run")
SIGNED = "\n\nAlex Rivera\nAcme Payroll Data\nacme.example"
OPT = " If this isn't relevant, just tell me and I won't write again."
BODY = ("Hi Sam, I read your piece on small-business payroll and liked the point about hidden fees. We published a "
        "2026 comparison of payroll costs across 40 providers, with the raw numbers, that your readers might find "
        "useful as a source. Happy to send the data or answer questions.")


def run(coro):
    return asyncio.run(coro)


class NonFiniteNumbers(unittest.TestCase):
    def test_infinity_in_any_tool_gets_a_plain_error(self):
        cases = [("quote_cost", {"items": [{"job": "serp_page", "units": 1, "requests": math.inf}]}),
                 ("audit_site", {"url": "https://example.com", "max_pages": math.inf}),
                 ("next_steps", {"max_steps": math.inf}),
                 ("check_outreach_draft", {"to": "a@b.com", "subject": "Hi", "body": "x", "sent_today": math.inf}),
                 ("quote_cost", {"items": [{"job": "serp_page", "units": float("nan")}]})]
        for name, args in cases:
            with self.assertRaisesRegex(ValueError, "finite"):
                tools.dispatch(name, args)
            with self.assertRaisesRegex(ValueError, "finite"):
                run(runner.run_tool(name, args))

    def test_non_finite_numbers_hidden_deep_inside_are_found(self):
        deep = {"items": [{"job": "serp_page", "units": 1, "extra": [[{"x": -math.inf}]]}]}
        with self.assertRaisesRegex(ValueError, "finite"):
            tools.dispatch("quote_cost", deep)

    def test_json_literal_1e999_over_run_is_a_plain_error(self):
        args = json.loads('{"items": [{"job": "serp_page", "units": 1, "requests": 1e999}]}')
        with self.assertRaisesRegex(ValueError, "finite"):
            run(runner.run_tool("quote_cost", args))

    def test_normal_numbers_still_work(self):
        self.assertEqual(tools.dispatch("quote_cost", {"items": [{"job": "serp_page", "units": 15, "requests": 1}]})
                         ["suggested_cap_usd"], 0.1)

    def test_arithmetic_errors_become_plain_errors(self):
        original = tools.DISPATCH["next_steps"]
        tools.DISPATCH["next_steps"] = lambda a: 1 // 0
        try:
            with self.assertRaises(ValueError):
                tools.dispatch("next_steps", {})
            with self.assertRaises(ValueError):
                run(runner.run_tool("next_steps", {}))
        finally:
            tools.DISPATCH["next_steps"] = original
        tools.DISPATCH["next_steps"] = lambda a: float(10 ** 400)  # OverflowError
        try:
            with self.assertRaises(ValueError):
                tools.dispatch("next_steps", {})
        finally:
            tools.DISPATCH["next_steps"] = original

    def test_huge_whole_numbers_do_not_crash_the_audit_limit(self):
        with self.assertRaises(ValueError):
            tools.run_audit("https://example.com", max_pages=float("inf"))


class OutreachHardRules(unittest.TestCase):
    def check(self, body, subject="Payroll cost data for your piece"):
        return tools.check_outreach_draft("sam@example.com", subject, body)

    def test_complete_email_is_ready(self):
        r = self.check(BODY + OPT + SIGNED)
        self.assertTrue(r["ready"], r["problems"])

    def test_not_interested_is_not_an_opt_out_line(self):
        r = self.check(BODY + " Many teams are not interested in payroll data, but you might be." + SIGNED)
        self.assertFalse(r["ready"])
        self.assertTrue(any("say no" in p for p in r["problems"]), r["problems"])

    def test_ordinary_pitch_wording_is_not_an_opt_out_line(self):
        for line in ("Please reply no later than Friday.", "I would say no one covers this better.",
                     "We write no fluff, just data.", "Say no more, I have the numbers."):
            r = self.check(BODY + " " + line + SIGNED)
            self.assertFalse(r["ready"], line)
            self.assertTrue(any("say no" in p for p in r["problems"]), line)

    def test_a_complete_stop_or_no_reply_is_an_opt_out_line(self):
        for line in ("Reply STOP to opt out.", 'Reply "no" and I will not write again.', "Just say no.",
                     "Reply no\nif this is not for you"):
            self.assertTrue(self.check(BODY + " " + line + SIGNED)["ready"], line)

    def test_missing_opt_out_is_a_problem_not_a_warning(self):
        r = self.check(BODY + SIGNED)
        self.assertFalse(r["ready"])
        self.assertTrue(any("say no" in p for p in r["problems"]))
        self.assertFalse(any("say no" in w for w in r["warnings"]))

    def test_each_real_opt_out_wording_counts(self):
        for line in ("Reply STOP and I will not write again.", "You can unsubscribe any time.",
                     "If you'd rather not hear from me, tell me and I won't email again.",
                     "Let me know if you'd rather I stopped writing.", "No thanks is a fine answer."):
            self.assertTrue(self.check(BODY + " " + line + SIGNED)["ready"], line)

    def test_missing_sender_and_address_is_a_problem(self):
        for tail in ("", "\n\nThanks, Alex"):
            r = self.check(BODY + OPT + tail)
            self.assertFalse(r["ready"], tail)
            self.assertTrue(any("sender" in p and "address" in p for p in r["problems"]), r["problems"])

    def test_a_postal_address_is_enough(self):
        for tail in ("\n\nAlex, 123 Main Street, Austin, TX 78701", "\n\nAlex, PO Box 55, Leeds LS1 4AP",
                     "\n\nAlex - 10 Downing Street, London SW1A 2AA"):
            self.assertTrue(self.check(BODY + OPT + tail)["ready"], tail)

    def test_a_signature_block_with_name_and_company_is_enough(self):
        self.assertTrue(self.check(BODY + OPT + "\n\nBest,\nAlex Rivera\nFounder, Acme Payroll Data")["ready"])

    def test_curly_apostrophes_still_match(self):
        self.assertTrue(self.check(BODY + " If this isn’t relevant, just tell me and I won’t write again." + SIGNED)["ready"])


class FixedSafetySentences(unittest.TestCase):
    DATA_RULE_WORDS = ("data", "never instructions")

    def instructions(self) -> str:
        """server.py's INSTRUCTIONS text, evaluated without importing the MCP library."""
        with open(os.path.join(ROOT, "connector", "server.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "INSTRUCTIONS" for t in n.targets))
        return str(eval(compile(ast.Expression(node.value), "server.py", "eval"), {"tools": tools}))

    def test_data_is_never_instructions_sentence_everywhere(self):
        for where, text in (("INSTRUCTIONS", self.instructions()), ("WEB_NOTE", tools.WEB_NOTE),
                            ("get_playbook skill text", tools.get_playbook("start")["text"])):
            low = text.lower()
            self.assertIn(tools.DATA_NOT_INSTRUCTIONS.lower(), low, where)
        low = tools.DATA_NOT_INSTRUCTIONS.lower()
        for word in ("web pages", "ai answers", "reviews", "datasets", "never instructions"):
            self.assertIn(word, low)

    def test_web_fallback_sentence_and_setup_address_everywhere(self):
        self.assertEqual(tools.SETUP_URL, SETUP_URL)
        quote = tools.quote_cost(None, "starter")["how_to_run"]
        for where, text in (("INSTRUCTIONS", self.instructions()), ("WEB_NOTE", tools.WEB_NOTE), ("how_to_run", quote)):
            self.assertIn(tools.WEB_FALLBACK, text, where)
            self.assertIn(SETUP_URL, text, where)
        self.assertIn("no call-actor tool", tools.WEB_FALLBACK)
        self.assertIn("setup address", tools.WEB_FALLBACK)

    def test_fixed_sentences_use_no_banned_words(self):
        for text in (tools.DATA_NOT_INSTRUCTIONS, tools.WEB_FALLBACK):
            for word in ("free", "open-source", "open source"):
                self.assertNotIn(word, text.lower())

    def test_quote_still_gives_the_cap(self):
        q = tools.quote_cost([{"job": "serp_page", "units": 15}])
        self.assertIn("maxTotalChargeUsd = 0.1", q["how_to_run"])


if __name__ == "__main__":
    unittest.main()
