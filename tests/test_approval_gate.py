"""Tests for scripts/approval_gate.py and scripts/outreach_ledger.py (stdlib unittest)."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "scripts", "approval_gate.py")
LEDGER = os.path.join(ROOT, "scripts", "outreach_ledger.py")
APIFY = "mcp__plugin_citebase_apify__call-actor"
SEND = "mcp__gmail__send_email"
TODAY = dt.date.today().isoformat()


class GateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.ws = os.path.join(self.tmp.name, "project")
        os.makedirs(os.path.join(self.ws, "seo-workspace"))
        self.opts = {}

    def tearDown(self):
        self.tmp.cleanup()

    def env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_PLUGIN", "CITEBASE"))}
        env["CITEBASE_HOME"] = self.home
        env.update(self.opts)
        return env

    def run_gate(self, mode, tool, tool_input, cwd=None, raw=None):
        payload = raw if raw is not None else json.dumps(
            {"tool_name": tool, "tool_input": tool_input, "cwd": cwd or self.ws})
        proc = subprocess.run([sys.executable, GATE, mode], input=payload, capture_output=True,
                              text=True, env=self.env())
        decision = None
        if proc.stdout.strip():
            decision = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
        return proc.returncode, decision, proc.stdout + proc.stderr

    def ledger(self, *args):
        return subprocess.run([sys.executable, LEDGER, *args], capture_output=True, text=True, env=self.env())

    def state(self):
        with open(os.path.join(self.home, "state.json")) as fh:
            return json.load(fh)

    @staticmethod
    def actor(name="khadinakbar/scrape-google-serp", cap=0.5, **extra):
        call = {"actor": name, "input": {"queries": ["x"]}}
        if cap is not None:
            call["callOptions"] = {"maxTotalChargeUsd": cap}
        call.update(extra)
        return call


class ScopeTests(GateCase):
    def test_outside_workspace_is_silent(self):
        outside = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(outside)
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=None), cwd=outside)
        self.assertIsNone(decision)

    def test_workspace_found_in_parent_directory(self):
        sub = os.path.join(self.ws, "a", "b")
        os.makedirs(sub)
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=None), cwd=sub)
        self.assertEqual(decision, "deny")

    def test_unrelated_tool_is_silent(self):
        _, decision, _ = self.run_gate("pre", "mcp__x__list_things", {})
        self.assertIsNone(decision)

    def test_chat_message_without_email_is_silent(self):
        _, decision, _ = self.run_gate("pre", "mcp__slack__send_message", {"channel": "C1", "text": "hi"})
        self.assertIsNone(decision)


class ApifyTests(GateCase):
    def test_missing_cap_is_denied(self):
        _, decision, out = self.run_gate("pre", APIFY, self.actor(cap=None))
        self.assertEqual(decision, "deny")
        self.assertIn("callOptions", out)

    def test_cap_inside_actor_input_does_not_count(self):
        call = self.actor(cap=None)
        call["input"]["maxTotalChargeUsd"] = 0.5
        _, decision, _ = self.run_gate("pre", APIFY, call)
        self.assertEqual(decision, "deny")

    def test_capped_run_inside_limits_passes_silently(self):
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=0.5))
        self.assertIsNone(decision)

    def test_cap_above_per_run_limit_asks(self):
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=5))
        self.assertEqual(decision, "ask")

    def test_non_numeric_or_zero_cap_is_denied(self):
        for bad in ("lots", 0, -1, True):
            _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=bad))
            self.assertEqual(decision, "deny", bad)

    def test_foreign_actor_is_denied(self):
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(name="someone/else"))
        self.assertEqual(decision, "deny")

    def test_lookalike_owner_is_denied(self):
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(name="khadinakbar-evil/scraper"))
        self.assertEqual(decision, "deny")

    def test_tilde_form_is_accepted(self):
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(name="khadinakbar~scrape-google-serp"))
        self.assertIsNone(decision)

    def test_extra_allowed_actor_option(self):
        self.opts["CLAUDE_PLUGIN_OPTION_ALLOWED_ACTORS"] = "apify/website-content-crawler, foo/bar"
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(name="apify/website-content-crawler"))
        self.assertIsNone(decision)

    def test_daily_ceiling_blocks_after_recorded_spend(self):
        self.opts["CLAUDE_PLUGIN_OPTION_DAILY_SPEND_USD"] = "1"
        self.opts["CLAUDE_PLUGIN_OPTION_MAX_RUN_USD"] = "5"
        self.run_gate("post", APIFY, self.actor(cap=0.8))
        _, decision, out = self.run_gate("pre", APIFY, self.actor(cap=0.5))
        self.assertEqual(decision, "deny")
        self.assertIn("daily", out.lower())

    def test_dedicated_actor_tool_asks(self):
        _, decision, _ = self.run_gate("pre", "mcp__apify__khadinakbar--scrape-google-serp", {"queries": ["x"]})
        self.assertEqual(decision, "ask")

    def test_corrupt_state_fails_closed(self):
        os.makedirs(self.home)
        with open(os.path.join(self.home, "state.json"), "w") as fh:
            fh.write("{not json")
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=0.5))
        self.assertEqual(decision, "deny")


class FailClosedTests(GateCase):
    def test_garbage_payload_exits_2(self):
        code, _, _ = self.run_gate("pre", "", {}, raw="not json")
        self.assertEqual(code, 2)

    def test_payload_not_an_object_exits_2(self):
        code, _, _ = self.run_gate("pre", "", {}, raw="[1,2]")
        self.assertEqual(code, 2)


class SendTests(GateCase):
    mail = {"to": "pat@example.com", "subject": "Quick idea", "body": "Hi Pat,\nA short note."}

    def approve(self, args=None):
        proc = self.ledger("approve", "--args", json.dumps(args or self.mail))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_unapproved_draft_is_denied(self):
        _, decision, out = self.run_gate("pre", SEND, self.mail)
        self.assertEqual(decision, "deny")
        self.assertIn("approve", out)

    def test_approved_draft_asks_the_human(self):
        self.approve()
        _, decision, out = self.run_gate("pre", SEND, self.mail)
        self.assertEqual(decision, "ask")
        self.assertIn("pat@example.com", out)

    def test_edited_body_after_approval_is_denied(self):
        self.approve()
        edited = dict(self.mail, body="Hi Pat, buy now!")
        _, decision, _ = self.run_gate("pre", SEND, edited)
        self.assertEqual(decision, "deny")

    def test_whitespace_and_case_changes_keep_approval(self):
        self.approve()
        same = {"to": "PAT@Example.com", "subject": " Quick   idea ", "body": "Hi Pat,  A short   note."}
        _, decision, _ = self.run_gate("pre", SEND, same)
        self.assertEqual(decision, "ask")

    def test_approval_is_single_use(self):
        self.approve()
        self.run_gate("post", SEND, self.mail)
        _, decision, _ = self.run_gate("pre", SEND, self.mail)
        self.assertEqual(decision, "deny")

    def test_suppressed_address_and_domain_are_denied(self):
        self.approve()
        self.ledger("suppress", "add", "@example.com")
        _, decision, out = self.run_gate("pre", SEND, self.mail)
        self.assertEqual(decision, "deny")
        self.assertIn("suppress", out.lower())

    def test_workspace_suppression_file(self):
        self.approve()
        with open(os.path.join(self.ws, "seo-workspace", "suppression.txt"), "w") as fh:
            fh.write("# do not contact\npat@example.com\n")
        _, decision, _ = self.run_gate("pre", SEND, self.mail)
        self.assertEqual(decision, "deny")

    def test_daily_cap_counts_recipients(self):
        self.opts["CLAUDE_PLUGIN_OPTION_DAILY_SEND_CAP"] = "2"
        multi = dict(self.mail, to="a@x.com, b@x.com", cc="c@x.com")
        self.approve(multi)
        _, decision, out = self.run_gate("pre", SEND, multi)
        self.assertEqual(decision, "deny")
        self.assertIn("cap", out.lower())

    def test_post_counts_recipients_toward_cap(self):
        self.opts["CLAUDE_PLUGIN_OPTION_DAILY_SEND_CAP"] = "2"
        self.run_gate("post", SEND, dict(self.mail, to="a@x.com, b@x.com"))
        self.assertEqual(self.state()["days"][TODAY]["sent"], 2)
        nxt = dict(self.mail, to="z@x.com")
        self.approve(nxt)
        _, decision, _ = self.run_gate("pre", SEND, nxt)
        self.assertEqual(decision, "deny")

    def test_paused_blocks_everything(self):
        self.approve()
        self.ledger("pause", "--reason", "bounce rate")
        _, decision, out = self.run_gate("pre", SEND, self.mail)
        self.assertEqual(decision, "deny")
        self.assertIn("paused", out.lower())

    def test_draft_send_without_recipients_asks(self):
        _, decision, _ = self.run_gate("pre", "mcp__gmail__send_draft", {"draft_id": "r123"})
        self.assertEqual(decision, "ask")

    def test_campaign_start_asks(self):
        for tool in ("start_campaign", "resume_campaign", "activate_campaign"):
            _, decision, _ = self.run_gate("pre", f"mcp__reachinbox__{tool}", {"campaign_id": 7})
            self.assertEqual(decision, "ask", tool)

    def test_weak_send_name_with_email_is_gated(self):
        _, decision, _ = self.run_gate("pre", "mcp__mail__send_message", self.mail)
        self.assertEqual(decision, "deny")


class PaidTests(GateCase):
    def test_cart_and_purchase_tools_ask(self):
        for tool in ("add_guest_post_to_cart", "add_link_insertion_to_cart", "checkout_cart", "purchase_order"):
            _, decision, _ = self.run_gate("pre", f"mcp__vendor__{tool}", {"quantity": 1})
            self.assertEqual(decision, "ask", tool)


class LedgerTests(GateCase):
    def test_status_reports_cap_and_pause(self):
        out = self.ledger("status")
        self.assertEqual(out.returncode, 0)
        self.assertIn("paused", out.stdout.lower())

    def test_resume_clears_pause(self):
        self.ledger("pause")
        self.ledger("resume")
        self.assertFalse(self.state()["paused"])

    def test_suppress_check_matches_domain_rule(self):
        self.ledger("suppress", "add", "@blocked.org")
        proc = self.ledger("suppress", "check", "anyone@blocked.org")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.ledger("suppress", "check", "ok@fine.org").returncode, 0)


if __name__ == "__main__":
    unittest.main()
