"""Regression tests for the security review of the approval gate (findings 3-9, 13, 15, 16)."""
import codecs
import datetime as dt
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_approval_gate import APIFY, GATE, SEND, GateCase  # noqa: E402


class SendClassificationTests(GateCase):
    mail = {"to": "pat@example.com", "subject": "Quick idea", "body": "Hi Pat, a short note."}

    def test_reply_and_forward_without_visible_recipient_ask(self):
        for tool, args in (("mcp__mail__reply", {"message_id": "abc", "body": "thanks"}),
                           ("mcp__mail__forward", {"message_id": "abc"}),
                           ("mcp__mail__reply_all", {"thread_id": "t1", "body": "ok"})):
            _, decision, _ = self.run_gate("pre", tool, args)
            self.assertEqual(decision, "ask", tool)

    def test_read_only_and_prepare_tools_are_not_gated(self):
        for tool in ("mcp__r__prepare_reply", "mcp__r__list_replies", "mcp__r__get_campaign",
                     "mcp__r__search_messages", "mcp__g__create_draft", "mcp__g__delete_draft"):
            _, decision, _ = self.run_gate("pre", tool, {"thread_id": 1})
            self.assertIsNone(decision, tool)

    def test_name_spellings_are_still_gated(self):
        for tool in ("mcp__r__send-email", "mcp__r__sendEmail", "mcp__g__gmail_send_email", "mcp__r__send_emails"):
            _, decision, _ = self.run_gate("pre", tool, self.mail)
            self.assertEqual(decision, "deny", tool)
        for tool in ("mcp__z__purchase-domains", "mcp__z__buy-mailboxes", "mcp__z__buyDomain"):
            _, decision, _ = self.run_gate("pre", tool, {"quantity": 1})
            self.assertEqual(decision, "ask", tool)

    def test_foreign_dedicated_actor_tools_are_denied(self):
        _, decision, _ = self.run_gate("pre", "mcp__apify__someone--tool", {"q": 1})
        self.assertEqual(decision, "deny")
        _, decision, _ = self.run_gate("pre", "mcp__apify__khadinakbar--my_actor.v2", {"q": 1})
        self.assertEqual(decision, "ask")

    def test_hook_matcher_covers_spelling_variants(self):
        import re
        with open(os.path.join(os.path.dirname(GATE), "..", "hooks", "hooks.json")) as fh:
            pre = re.compile(json.load(fh)["hooks"]["PreToolUse"][0]["matcher"])
        for name in ("mcp__r__send-email", "mcp__r__sendEmail", "mcp__g__gmail_send_email", "mcp__r__send_emails",
                     "mcp__z__purchase-domains", "mcp__z__buy-mailboxes", "mcp__a__apify--rag-web-browser",
                     "mcp__a__khadinakbar--my_actor", "mcp__x__call-actor"):
            self.assertTrue(pre.search(name), name)
        self.assertFalse(pre.search("Bash"))
        self.assertFalse(pre.search("mcp__x__list_pages"))


class RobustnessTests(GateCase):
    def raw(self, tool_input_json, tool="mcp__g__reply", cwd=None, mode="pre"):
        payload = '{"tool_name": "%s", "tool_input": %s, "cwd": %s}' % (tool, tool_input_json, json.dumps(cwd or self.ws))
        return self.run_gate(mode, tool, {}, raw=payload)

    def test_deeply_nested_input_never_fails_open(self):
        deep = '{"to": ' + "[" * 3000 + '"a@b.com"' + "]" * 3000 + "}"
        code, decision, _ = self.raw(deep)
        self.assertTrue(code == 2 or decision in ("deny", "ask"), (code, decision))

    def test_nan_and_infinity_caps_are_rejected(self):
        for bad in ("NaN", "Infinity"):
            code, decision, _ = self.raw('{"actor": "khadinakbar/x", "callOptions": {"maxTotalChargeUsd": %s}}' % bad,
                                         tool=APIFY)
            self.assertTrue(code == 2 or decision == "deny", (bad, code, decision))

    def test_non_string_cwd_does_not_crash(self):
        payload = json.dumps({"tool_name": APIFY, "tool_input": {}, "cwd": 5})
        code, _, _ = self.run_gate("pre", APIFY, {}, raw=payload)
        self.assertIn(code, (0, 2))

    def test_workspace_found_many_levels_up(self):
        sub = self.ws
        for i in range(12):
            sub = os.path.join(sub, f"d{i}")
        os.makedirs(sub)
        _, decision, _ = self.run_gate("pre", APIFY, self.actor(cap=None), cwd=sub)
        self.assertEqual(decision, "deny")


class RecipientTests(GateCase):
    mail = {"to": "pat@example.com", "subject": "Quick idea", "body": "Hi Pat, a short note."}

    def suppress_file(self, text, bom=False):
        os.makedirs(self.home, exist_ok=True)
        with open(os.path.join(self.home, "suppression.txt"), "wb") as fh:
            fh.write((codecs.BOM_UTF8 if bom else b"") + text.encode("utf-8"))

    def check(self, email):
        return self.ledger("suppress", "check", email).returncode

    def test_suppression_rule_forms(self):
        cases = [("bad@x.com", "bad+promo@x.com"), ("@blocked.com", "a@mail.blocked.com"),
                 ("blocked.org", "a@blocked.org"), ("*@wild.net", "z@wild.net"), ("Mixed@Case.com", "mixed@case.com")]
        for rule, email in cases:
            self.suppress_file(rule + "\n")
            self.assertEqual(self.check(email), 1, (rule, email))
        self.assertEqual(self.check("someone@else.com"), 0)

    def test_bom_in_rule_file_is_ignored(self):
        self.suppress_file("first@x.com\nsecond@x.com\n", bom=True)
        self.assertEqual(self.check("first@x.com"), 1)

    def test_unicode_and_apostrophe_addresses_are_parsed_whole(self):
        for addr in ("o'brien@x.com", "jürgen@x.com", "bad@münchen.de"):
            self.suppress_file(addr + "\n")
            mail = dict(self.mail, to=["ok@x.com", addr])
            _, decision, out = self.run_gate("pre", SEND, mail)
            self.assertEqual(decision, "deny", addr)
            self.assertIn("suppress", out.lower(), addr)

    def test_unparseable_recipient_text_fails_closed(self):
        _, decision, out = self.run_gate("pre", SEND, dict(self.mail, to="broken@, ok@x.com"))
        self.assertEqual(decision, "deny")
        self.assertIn("recipient", out.lower())

    def test_other_recipient_key_spellings_are_checked(self):
        self.suppress_file("pat@example.com\n")
        for key in ("to_email", "toAddresses", "BCC", "recipient_email"):
            mail = {key: "pat@example.com", "subject": "s", "body": "b"}
            _, decision, out = self.run_gate("pre", SEND, mail)
            self.assertEqual(decision, "deny", key)
            self.assertIn("suppress", out.lower(), key)

    def test_sender_fields_are_not_counted_as_recipients(self):
        mail = dict(self.mail, **{"from": "me@mine.com"})
        self.ledger("approve", "--args", json.dumps(mail))
        self.suppress_file("me@mine.com\n")
        _, decision, _ = self.run_gate("pre", SEND, mail)
        self.assertEqual(decision, "ask")


class ApprovalTests(GateCase):
    mail = {"to": "pat@example.com", "subject": "Quick idea", "body": "Hi Pat, a short note."}

    def approve(self, args=None):
        self.assertEqual(self.ledger("approve", "--args", json.dumps(args or self.mail)).returncode, 0)

    def test_expired_approval_is_not_honoured(self):
        self.approve()
        state = self.state()
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat(timespec="seconds")
        for rec in state["approvals"].values():
            rec["ts"] = old
        with open(os.path.join(self.home, "state.json"), "w") as fh:
            json.dump(state, fh)
        _, decision, _ = self.run_gate("pre", SEND, self.mail)
        self.assertEqual(decision, "deny")

    def test_approval_covers_every_part_of_the_message(self):
        self.approve()
        variants = [dict(self.mail, html="<a href='//evil.example'>x</a>"),
                    dict(self.mail, attachments=[{"name": "invoice.exe"}]),
                    dict(self.mail, bcc="extra@example.com"),
                    dict(self.mail, subject="Quick idea!"),
                    dict(self.mail, body="Hi Pat, a short note. P.S. buy now")]
        for variant in variants:
            _, decision, _ = self.run_gate("pre", SEND, variant)
            self.assertEqual(decision, "deny", sorted(variant))

    def test_to_versus_to_plus_bcc_are_different_messages(self):
        both = dict(self.mail, to=["pat@example.com", "lee@example.com"])
        self.approve(both)
        moved = dict(self.mail, to="pat@example.com", bcc="lee@example.com")
        _, decision, _ = self.run_gate("pre", SEND, moved)
        self.assertEqual(decision, "deny")


if __name__ == "__main__":
    unittest.main()
