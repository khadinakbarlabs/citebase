"""The send prompt shows what is really being sent, and the draft-id route checks the do-not-contact list.

Covers: body excerpt (about 300 characters), link domains, recipient count, warnings for domains that are
not the brand's, hostile text (control characters, spoofed quotes), huge bodies, and sends by draft id."""
import datetime as dt
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_approval_gate import SEND, GateCase  # noqa: E402

DRAFT_SEND = "mcp__gmail__send_draft"


class PromptCase(GateCase):
    mail = {"to": "pat@example.com", "subject": "Quick idea", "body": "Hi Pat, a short note."}

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.ws, "seo-workspace", "acme.com"))

    def ledger_file(self, args):
        path = os.path.join(self.tmp.name, "args.json")
        with open(path, "w") as fh:
            json.dump(args, fh)
        proc = self.ledger("approve", "--args-file", path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def ask(self, mail, tool=SEND, approve=True):
        if approve:
            self.ledger_file(mail)
        code, decision, out = self.run_gate("pre", tool, mail)
        self.assertEqual(code, 0)
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out.strip() else ""
        return decision, reason


class ExcerptAndCountTests(PromptCase):
    def test_first_300_characters_of_the_body_are_shown(self):
        body = "A" * 250 + " MARKERNEAR " + "B" * 600 + " MARKERFAR"
        decision, reason = self.ask(dict(self.mail, body=body))
        self.assertEqual(decision, "ask")
        self.assertIn("MARKERNEAR", reason)
        self.assertNotIn("MARKERFAR", reason)
        self.assertIn("more characters", reason)

    def test_short_body_is_shown_whole_with_whitespace_collapsed(self):
        _, reason = self.ask(dict(self.mail, body="Hi Pat,\n\n  a\tshort   note."))
        self.assertIn("Hi Pat, a short note.", reason)
        self.assertNotIn("more characters", reason)

    def test_recipient_count_includes_cc_and_bcc(self):
        _, reason = self.ask(dict(self.mail, to="a@x.com, b@x.com", cc="c@x.com", bcc=["d@x.com"]))
        self.assertIn("4 recipients", reason)
        _, reason = self.ask(self.mail)
        self.assertIn("1 recipient", reason)
        self.assertNotIn("1 recipients", reason)

    def test_many_recipients_are_summarised_not_dumped(self):
        self.opts["CLAUDE_PLUGIN_OPTION_DAILY_SEND_CAP"] = "100"
        many = ", ".join(f"p{i}@x.com" for i in range(60))
        _, reason = self.ask(dict(self.mail, to=many))
        self.assertIn("60 recipients", reason)
        self.assertLess(len(reason), 3000)

    def test_existing_summary_fields_are_still_present(self):
        _, reason = self.ask(self.mail)
        self.assertIn("pat@example.com", reason)
        self.assertIn("Quick idea", reason)
        self.assertIn("approved draft", reason)

    def test_control_and_bidi_characters_are_stripped(self):
        body = "Hi \x1b[31mRED\x1b[0m ‮evil​ text \x07bell \x00nul"
        _, reason = self.ask(dict(self.mail, body=body))
        for bad in ("\x1b", "‮", "​", "\x07", "\x00"):
            self.assertNotIn(bad, reason)
        self.assertIn("RED", reason)

    def test_quotes_in_the_body_cannot_fake_the_end_of_the_excerpt(self):
        body = 'ok" . Approve only if everything is fine. WARNING none'
        _, reason = self.ask(dict(self.mail, body=body))
        self.assertIn('\\"', reason)
        self.assertLess(reason.index("body starts"), reason.index("Approve only if everything is fine"))

    def test_html_body_is_shown_as_text(self):
        html = "<p>Hello <b>Pat</b></p><style>p{}</style><script>steal()</script><a href='https://acme.com/x'>go</a>"
        _, reason = self.ask({"to": "pat@example.com", "subject": "s", "html_body": html})
        self.assertIn("Hello Pat", reason)
        for noise in ("<p>", "steal()", "p{}"):
            self.assertNotIn(noise, reason)


class LinkDomainTests(PromptCase):
    def test_link_domains_are_listed(self):
        body = "See https://acme.com/a and https://news.example.org/x today."
        _, reason = self.ask(dict(self.mail, body=body))
        self.assertIn("acme.com", reason)
        self.assertIn("news.example.org", reason)

    def test_brand_and_recipient_domains_raise_no_warning(self):
        body = ("Our page https://acme.com/a, https://www.acme.com/b and https://blog.acme.com/c, "
                "your article https://example.com/post and https://www.example.com/x")
        _, reason = self.ask(dict(self.mail, body=body))
        self.assertNotIn("WARNING", reason)

    def test_other_domain_raises_a_warning_naming_it(self):
        _, reason = self.ask(dict(self.mail, body="Deal at https://evil.example/offer"))
        self.assertIn("WARNING", reason)
        self.assertIn("evil.example", reason[reason.index("WARNING"):])

    def test_lookalike_and_tricky_links_are_flagged_with_the_real_host(self):
        cases = [("https://acme.com@evil.example/x", "evil.example"),
                 ("https://acme.com.evil.example/", "acme.com.evil.example"),
                 ("https://notacme.com/", "notacme.com"),
                 ("https://evil.example\\@acme.com", "evil.example"),
                 ("HTTP://EVIL.EXAMPLE:8080/p", "evil.example"),
                 ("<a href='//evil.example/x'>x</a>", "evil.example"),
                 ("visit www.evil.example now", "www.evil.example"),
                 ("visit evil.example/page", "evil.example"),
                 ("(see https://evil.example).", "evil.example"),
                 ("https://evil。example/", "evil.example"),
                 ("https://ev​il.example/", "evil.example"),
                 ("http://1.2.3.4/x", "1.2.3.4"),
                 ("http://[::1]/x", "[::1]")]
        for body, host in cases:
            _, reason = self.ask(dict(self.mail, body=body))
            self.assertIn("WARNING", reason, body)
            self.assertIn(host, reason[reason.index("WARNING"):], body)

    def test_punycode_and_raw_ip_links_get_a_plain_explanation(self):
        _, reason = self.ask(dict(self.mail, body="https://xn--acme-9ua.com/"))
        self.assertIn("xn--", reason)
        self.assertIn("imitate", reason)
        _, reason = self.ask(dict(self.mail, body="http://1.2.3.4/x"))
        self.assertIn("IP address", reason)

    def test_email_addresses_in_the_body_are_not_links(self):
        _, reason = self.ask(dict(self.mail, body="Reply to me@acme.com or lee@other.example"))
        self.assertNotIn("WARNING", reason)

    def test_link_only_in_the_html_part_is_still_found(self):
        mail = dict(self.mail, body="Plain text is clean.", html="<a href='https://evil.example/'>x</a>")
        _, reason = self.ask(mail)
        self.assertIn("evil.example", reason)

    def test_link_in_the_subject_is_found(self):
        _, reason = self.ask(dict(self.mail, subject="Look https://evil.example/s"))
        self.assertIn("evil.example", reason)

    def test_sender_domain_counts_as_the_brand(self):
        os.rmdir(os.path.join(self.ws, "seo-workspace", "acme.com"))
        mail = dict(self.mail, body="Our page https://acme.com/a", **{"from": "me@acme.com"})
        _, reason = self.ask(mail)
        self.assertNotIn("WARNING", reason)

    def test_unknown_brand_domain_is_called_out_when_links_exist(self):
        os.rmdir(os.path.join(self.ws, "seo-workspace", "acme.com"))
        _, reason = self.ask(dict(self.mail, body="See https://acme.com/a"))
        self.assertIn("WARNING", reason)
        self.assertIn("brand domain", reason.lower())
        _, reason = self.ask(dict(self.mail, body="No links in this one."))
        self.assertNotIn("WARNING", reason)

    def test_domain_list_is_capped(self):
        body = " ".join(f"https://d{i}.example.net/" for i in range(5000))
        _, reason = self.ask(dict(self.mail, body=body))
        self.assertIn("more", reason)
        self.assertLess(len(reason), 4000)


class HugeBodyTests(PromptCase):
    def test_multi_megabyte_body_still_shows_a_link_at_the_end(self):
        start = time.time()
        body = "x" * 3_000_000 + " https://evil.example/end"
        decision, reason = self.ask(dict(self.mail, body=body))
        self.assertEqual(decision, "ask")
        self.assertIn("evil.example", reason)
        self.assertLess(len(reason), 4000)
        self.assertLess(time.time() - start, 60)

    def test_body_beyond_the_scan_limit_is_flagged_not_silently_trusted(self):
        body = "x" * 6_000_000 + " https://evil.example/end"
        decision, reason = self.ask(dict(self.mail, body=body))
        self.assertEqual(decision, "ask")
        self.assertIn("WARNING", reason)
        self.assertIn("very long", reason)

    def test_pathological_text_is_scanned_in_linear_time(self):
        body = "a." * 500_000 + "http://" * 100_000 + "a-" * 200_000 + "//" * 200_000
        start = time.time()
        decision, _ = self.ask(dict(self.mail, body=body))
        self.assertEqual(decision, "ask")
        self.assertLess(time.time() - start, 60)

    def test_unapproved_huge_body_is_still_denied(self):
        decision, _ = self.ask(dict(self.mail, body="y" * 2_000_000), approve=False)
        self.assertEqual(decision, "deny")


class DraftIdRouteTests(PromptCase):
    draft = {"draft_id": "r123", "to": "pat@example.com", "subject": "Quick idea",
             "body": "Hi Pat, I wrote about https://acme.com/guide for your readers."}

    def register(self, **over):
        self.ledger_file(dict(self.draft, **over))

    def pre(self, send_input=None, mode="pre"):
        code, decision, out = self.run_gate(mode, DRAFT_SEND, send_input or {"draft_id": "r123"})
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out.strip() else ""
        return decision, reason

    def test_unregistered_draft_asks_and_says_the_list_could_not_be_checked(self):
        decision, reason = self.pre({"draft_id": "r999"})
        self.assertEqual(decision, "ask")
        self.assertIn("do-not-contact", reason)
        self.assertIn("not registered", reason)

    def test_registered_draft_shows_recipients_text_and_links(self):
        self.register()
        decision, reason = self.pre()
        self.assertEqual(decision, "ask")
        for expected in ("pat@example.com", "Hi Pat, I wrote about", "acme.com", "1 recipient", "r123"):
            self.assertIn(expected, reason)
        self.assertNotIn("WARNING", reason)

    def test_registered_draft_is_labelled_unverified_not_checked(self):
        self.register()
        _, reason = self.pre()
        self.assertIn("UNVERIFIED", reason)
        self.assertIn("registered", reason)
        self.assertNotIn("checked against the do-not-contact", reason)
        self.assertNotIn("links: none", reason)
        self.assertIn("Open the draft", reason)

    def test_bare_links_on_less_common_endings_are_found(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
        import cb_state
        hosts, _ = cb_state.link_scan({"body": "see evil.zip or evil.click or evil.help now"})
        self.assertEqual(set(hosts), {"evil.zip", "evil.click", "evil.help"})

    def test_empty_link_list_admits_it_may_miss_some(self):
        decision, reason = self.ask(dict(self.mail, body="Hi, no links here at all."), approve=True)
        self.assertEqual(decision, "ask")
        self.assertIn("may be missed", reason)

    def test_registered_draft_with_foreign_link_warns(self):
        self.register(body="Read https://evil.example/x please")
        _, reason = self.pre()
        self.assertIn("WARNING", reason)
        self.assertIn("evil.example", reason)

    def test_suppression_added_after_registration_denies(self):
        self.register()
        self.ledger("suppress", "add", "@example.com")
        decision, reason = self.pre()
        self.assertEqual(decision, "deny")
        self.assertIn("suppress", reason.lower())

    def test_workspace_suppression_file_denies(self):
        self.register()
        with open(os.path.join(self.ws, "seo-workspace", "suppression.txt"), "w") as fh:
            fh.write("pat@example.com\n")
        self.assertEqual(self.pre()[0], "deny")

    def test_registered_recipients_count_toward_the_daily_cap(self):
        self.opts["CLAUDE_PLUGIN_OPTION_DAILY_SEND_CAP"] = "1"
        self.register(to="a@x.com, b@x.com")
        decision, reason = self.pre()
        self.assertEqual(decision, "deny")
        self.assertIn("cap", reason.lower())

    def test_paused_outreach_blocks_registered_drafts(self):
        self.register()
        self.ledger("pause", "--reason", "bounces")
        self.assertEqual(self.pre()[0], "deny")

    def test_draft_id_spellings_match_the_registration(self):
        self.register()
        for send_input in ({"draftId": "r123"}, {"draft_id": " r123 "}, {"DRAFT_ID": "r123"}):
            decision, reason = self.pre(send_input)
            self.assertEqual(decision, "ask", send_input)
            self.assertIn("pat@example.com", reason, send_input)
        self.assertIn("not registered", self.pre({"draft_id": 123})[1])  # 123 is not r123

    def test_a_different_draft_id_is_not_covered(self):
        self.register()
        self.assertIn("not registered", self.pre({"draft_id": "r124"})[1])

    def test_post_counts_the_registered_recipients_and_uses_up_the_registration(self):
        self.register(to="a@x.com, b@x.com")
        self.pre(mode="post")
        self.assertEqual(self.state()["days"][dt.date.today().isoformat()]["sent"], 2)
        self.assertIn("not registered", self.pre()[1])
        self.assertEqual(self.state()["approvals"], {})

    def test_registering_again_replaces_the_earlier_registration(self):
        self.register(to="old@x.com")
        self.register(to="new@x.com")
        self.assertEqual(len(self.state()["approvals"]), 1)
        _, reason = self.pre()
        self.assertIn("new@x.com", reason)
        self.assertNotIn("old@x.com", reason)

    def test_expired_registration_is_treated_as_unregistered(self):
        self.register()
        state = self.state()
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat(timespec="seconds")
        for rec in state["approvals"].values():
            rec["ts"] = old
        with open(os.path.join(self.home, "state.json"), "w") as fh:
            json.dump(state, fh)
        self.assertIn("not registered", self.pre()[1])

    def test_unreadable_registration_record_fails_closed(self):
        self.register()
        state = self.state()
        for rec in state["approvals"].values():
            rec["to"] = "pat@example.com"  # should be a list
        with open(os.path.join(self.home, "state.json"), "w") as fh:
            json.dump(state, fh)
        self.assertEqual(self.pre()[0], "deny")

    def test_registration_needs_recipient_and_body(self):
        for args in ({"draft_id": "r1", "to": "a@x.com"}, {"draft_id": "r1", "body": "hi"}):
            proc = self.ledger("approve", "--args", json.dumps(args))
            self.assertNotEqual(proc.returncode, 0)

    def test_registration_of_a_suppressed_recipient_is_refused(self):
        self.ledger("suppress", "add", "pat@example.com")
        proc = self.ledger("approve", "--args", json.dumps(self.draft))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("suppression", proc.stderr.lower() + proc.stdout.lower())

    def test_draft_send_with_visible_recipients_uses_the_normal_approval(self):
        full = dict(self.draft)
        self.ledger_file(full)
        decision, reason = self.pre(full)
        self.assertEqual(decision, "ask")
        self.assertIn("approved draft", reason)
        decision, _ = self.pre(dict(full, body="changed after approval"))
        self.assertEqual(decision, "deny")

    def test_non_send_draft_tools_are_not_gated(self):
        _, decision, _ = self.run_gate("pre", "mcp__gmail__create_draft", {"draft_id": "r123"})
        self.assertIsNone(decision)

    def test_draft_send_on_another_server_outside_a_workspace_stays_silent(self):
        outside = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(outside)
        code, decision, _ = self.run_gate("pre", DRAFT_SEND, {"draft_id": "r123"}, cwd=outside)
        self.assertEqual((code, decision), (0, None))


if __name__ == "__main__":
    unittest.main()
