"""The spend gate always covers the plugin's own Apify tools, with or without a seo-workspace/ folder.

Outside a workspace the generic send/paid heuristics for OTHER servers stay silent (no prompts in
unrelated projects), but this plugin's own call-actor must still need a valid cap, an allowlisted
Actor and a daily ceiling. State lives under CITEBASE_HOME (default ~/.citebase)."""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_approval_gate import APIFY, GATE, ROOT, GateCase  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import approval_gate as gate  # noqa: E402

OWN = "mcp__plugin_citebase_apify__"


def load(*parts):
    with open(os.path.join(ROOT, *parts)) as fh:
        return json.load(fh)


class ToolNameTests(unittest.TestCase):
    """How the registered tool prefix was verified, kept as tests so it cannot drift."""

    def test_prefix_is_derived_from_manifests(self):
        name = load(".claude-plugin", "plugin.json")["name"]
        servers = list(load(".mcp.json")["mcpServers"])
        self.assertEqual(servers, ["apify"])
        self.assertEqual(f"mcp__plugin_{name}_{servers[0]}__", gate.OWN_APIFY_PREFIX)
        self.assertEqual(gate.OWN_APIFY_PREFIX, OWN)

    def test_hook_matchers_route_the_own_call_actor_to_the_gate(self):
        hooks = load("hooks", "hooks.json")["hooks"]
        pre = re.compile(hooks["PreToolUse"][0]["matcher"])
        post = re.compile(hooks["PostToolUse"][0]["matcher"])
        self.assertTrue(pre.search(OWN + "call-actor"))
        self.assertTrue(post.search(OWN + "call-actor"))
        for read_only in ("fetch-actor-details", "get-actor-run", "get-dataset-items", "abort-actor-run"):
            self.assertFalse(pre.search(OWN + read_only), read_only)
        for hook in hooks["PreToolUse"] + hooks["PostToolUse"]:
            self.assertIn("approval_gate.py", hook["hooks"][0]["command"])

    def test_mcp_url_exposes_only_the_tools_the_gate_understands(self):
        url = load(".mcp.json")["mcpServers"]["apify"]["url"]
        tools = set(url.split("tools=")[1].split(","))
        self.assertEqual(tools, {"fetch-actor-details", "call-actor", "get-actor-run", "get-dataset-items",
                                 "abort-actor-run"})


class OutsideWorkspaceCase(GateCase):
    def setUp(self):
        super().setUp()
        self.outside = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(self.outside)

    def pre(self, tool, tool_input, cwd=None):
        return self.run_gate("pre", tool, tool_input, cwd=cwd or self.outside)

    def decision(self, tool, tool_input, cwd=None):
        return self.pre(tool, tool_input, cwd)[1]

    def run_raw(self, mode, data: bytes, env=None):
        proc = subprocess.run([sys.executable, GATE, mode], input=data, capture_output=True, env=env or self.env())
        out = proc.stdout.decode("utf-8", "replace")
        decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out.strip() else None
        return proc.returncode, decision, out + proc.stderr.decode("utf-8", "replace")


class OwnApifyOutsideWorkspaceTests(OutsideWorkspaceCase):
    def test_uncapped_call_is_denied(self):
        _, decision, out = self.pre(APIFY, self.actor(cap=None))
        self.assertEqual(decision, "deny")
        self.assertIn("callOptions", out)

    def test_invalid_caps_are_denied(self):
        for bad in ("lots", 0, -1, True, None, [], {}):
            self.assertEqual(self.decision(APIFY, self.actor(cap=bad)), "deny", bad)

    def test_non_allowlisted_actor_is_denied(self):
        for name in ("someone/else", "khadinakbar-evil/x", "apify/website-content-crawler", "khadinakbar", ""):
            self.assertEqual(self.decision(APIFY, self.actor(name=name)), "deny", name)

    def test_extra_allowed_actor_setting_is_honoured(self):
        self.opts["CLAUDE_PLUGIN_OPTION_ALLOWED_ACTORS"] = "apify/website-content-crawler"
        self.assertIsNone(self.decision(APIFY, self.actor(name="apify/website-content-crawler")))
        self.assertEqual(self.decision(APIFY, self.actor(name="apify/other")), "deny")

    def test_daily_ceiling_blocks_after_recorded_spend(self):
        self.opts["CLAUDE_PLUGIN_OPTION_DAILY_SPEND_USD"] = "1"
        self.opts["CLAUDE_PLUGIN_OPTION_MAX_RUN_USD"] = "5"
        self.run_gate("post", APIFY, self.actor(cap=0.8), cwd=self.outside)
        _, decision, out = self.pre(APIFY, self.actor(cap=0.5))
        self.assertEqual(decision, "deny")
        self.assertIn("daily", out.lower())

    def test_single_cap_above_ceiling_is_denied(self):
        self.opts["CLAUDE_PLUGIN_OPTION_DAILY_SPEND_USD"] = "1"
        self.opts["CLAUDE_PLUGIN_OPTION_MAX_RUN_USD"] = "50"
        self.assertEqual(self.decision(APIFY, self.actor(cap=1.5)), "deny")

    def test_capped_allowlisted_run_inside_limits_passes_silently(self):
        self.assertIsNone(self.decision(APIFY, self.actor(cap=0.5)))

    def test_cap_above_per_run_limit_asks(self):
        self.assertEqual(self.decision(APIFY, self.actor(cap=5)), "ask")

    def test_post_records_spend_in_citebase_home_only(self):
        self.run_gate("post", APIFY, self.actor(cap=0.75), cwd=self.outside)
        days = self.state()["days"]
        self.assertAlmostEqual(days[dt.date.today().isoformat()]["spend_usd"], 0.75)
        self.assertEqual(os.listdir(self.outside), [])  # nothing is created in the user's project

    def test_state_defaults_to_dot_citebase_in_home_dir(self):
        env = {k: v for k, v in self.env().items() if k != "CITEBASE_HOME"}
        env["HOME"] = os.path.join(self.tmp.name, "fakehome")
        os.makedirs(env["HOME"])
        payload = json.dumps({"tool_name": APIFY, "tool_input": self.actor(cap=0.4), "cwd": self.outside}).encode()
        self.run_raw("post", payload, env=env)
        self.assertTrue(os.path.isfile(os.path.join(env["HOME"], ".citebase", "state.json")))

    def test_spelling_variants_of_the_tool_name_cannot_bypass(self):
        for tool in (OWN + "callActor", OWN + "call_actor", OWN + "Call-Actor"):
            self.assertEqual(self.decision(tool, self.actor(cap=None)), "deny", tool)

    def test_dedicated_actor_names_on_the_own_server_are_gated(self):
        self.assertEqual(self.decision(OWN + "khadinakbar--scrape-google-serp", {"q": 1}), "ask")
        self.assertEqual(self.decision(OWN + "evil--thing", {"q": 1}), "deny")

    def test_gate_applies_in_a_workspace_too(self):
        self.assertEqual(self.run_gate("pre", APIFY, self.actor(cap=None))[1], "deny")


class OtherToolsStaySilentTests(OutsideWorkspaceCase):
    """No prompts, no blocks, in projects that merely have the plugin installed."""

    def test_other_servers_call_actor_outside_workspace_is_silent(self):
        for tool in ("mcp__apify__call-actor", "mcp__2897bf92_x__call-actor", "mcp__apify__khadinakbar--tool"):
            self.assertIsNone(self.decision(tool, self.actor(cap=None)), tool)

    def test_lookalike_server_prefixes_are_not_ours(self):
        for tool in ("mcp__plugin_citebase_apify_evil__call-actor", "mcp__plugin_citebase_apifyx__call-actor",
                     "mcp__plugin_citebase__call-actor", "mcp__plugin_other_apify__call-actor",
                     "mcp__plugin_otherplugin_apify__call-actor"):
            self.assertIsNone(self.decision(tool, self.actor(cap=None)), tool)

    def test_own_server_read_tools_are_silent(self):
        for name in ("fetch-actor-details", "get-actor-run", "get-dataset-items", "abort-actor-run"):
            self.assertIsNone(self.decision(OWN + name, {"actor": "evil/x", "runId": "r"}), name)

    def test_send_and_paid_heuristics_stay_workspace_only(self):
        mail = {"to": "pat@example.com", "subject": "s", "body": "b"}
        for tool, args in (("mcp__gmail__send_email", mail), ("mcp__x__checkout_cart", {"quantity": 1}),
                           ("mcp__r__start_campaign", {"campaign_id": 1}), ("mcp__mail__reply", {"body": "x"})):
            self.assertIsNone(self.decision(tool, args), tool)

    def test_non_mcp_and_unrelated_tools_are_silent(self):
        for tool in ("Bash", "Read", "mcp__x__list_things", "", "mcp__"):
            self.assertIsNone(self.decision(tool, {"command": "ls"}), tool)

    def test_seo_workspace_that_is_a_file_does_not_count(self):
        with open(os.path.join(self.outside, "seo-workspace"), "w") as fh:
            fh.write("not a folder")
        self.assertIsNone(self.decision("mcp__apify__call-actor", self.actor(cap=None)))
        self.assertEqual(self.decision(APIFY, self.actor(cap=None)), "deny")


class StateAndPathTrickTests(OutsideWorkspaceCase):
    def test_missing_state_directory_is_fine_for_pre_and_created_by_post(self):
        self.home = os.path.join(self.tmp.name, "no", "such", "dir")
        self.assertIsNone(self.decision(APIFY, self.actor(cap=0.5)))
        self.assertFalse(os.path.exists(self.home))  # a pre check never writes
        self.assertEqual(self.decision(APIFY, self.actor(cap=None)), "deny")
        self.run_gate("post", APIFY, self.actor(cap=0.5), cwd=self.outside)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "state.json")))

    def test_unreadable_or_odd_state_fails_closed(self):
        os.makedirs(self.home)
        path = os.path.join(self.home, "state.json")
        today = dt.date.today().isoformat()
        for text in ("{not json", "[]", '"x"', "null", '{"days": []}', '{"approvals": 5}',
                     '{"days": {"%s": {"sent": 0, "spend_usd": "lots"}}}' % today,
                     '{"days": {"%s": {"sent": 0, "spend_usd": NaN}}}' % today,
                     '{"days": {"%s": {"sent": 0, "spend_usd": -999}}}' % today):
            with open(path, "w") as fh:
                fh.write(text)
            self.assertEqual(self.decision(APIFY, self.actor(cap=0.5)), "deny", text)

    def test_state_path_that_is_a_file_fails_closed(self):
        bad = os.path.join(self.tmp.name, "afile")
        with open(bad, "w") as fh:
            fh.write("x")
        self.home = bad
        self.assertEqual(self.decision(APIFY, self.actor(cap=0.5)), "deny")

    def test_odd_cwd_values_cannot_switch_the_gate_off(self):
        for cwd in ("/", "", None, 5, [], {}, "..", "../../..", "relative/dir", "\x00", "a/\x00/b", "a" * 5000,
                    "~", os.path.join(self.outside, "..", "elsewhere", ".") + os.sep,
                    os.path.join(self.tmp.name, "does", "not", "exist")):
            payload = json.dumps({"tool_name": APIFY, "tool_input": self.actor(cap=None), "cwd": cwd}).encode()
            code, decision, out = self.run_raw("pre", payload)
            self.assertEqual((code, decision), (0, "deny"), (cwd, out))

    def test_cwd_pointing_at_a_file_does_not_crash_or_open_the_gate(self):
        target = os.path.join(self.outside, "plain.txt")
        with open(target, "w") as fh:
            fh.write("x")
        self.assertEqual(self.decision(APIFY, self.actor(cap=None), cwd=target), "deny")

    def test_missing_cwd_key_still_denies(self):
        payload = json.dumps({"tool_name": APIFY, "tool_input": self.actor(cap=None)}).encode()
        self.assertEqual(self.run_raw("pre", payload)[1], "deny")

    def test_non_dict_tool_input_denies_for_the_own_tool(self):
        for tool_input in (None, [], "x", 5, [{"actor": "khadinakbar/x"}]):
            payload = json.dumps({"tool_name": APIFY, "tool_input": tool_input, "cwd": self.outside}).encode()
            self.assertEqual(self.run_raw("pre", payload)[1], "deny", tool_input)

    def test_actor_name_path_tricks_are_denied(self):
        for name in ("khadinakbar/../evil/x", "khadinakbar/x/../../evil/y", "KHADINAKBAR/x/y", "khadinakbar//x",
                     "khadinakbar/x y", "khadinakbar/x\ny", "../khadinakbar/x", "khadinakbar\\x", " khadinakbar/x/",
                     "khadinakbar/" + "a" * 200000):
            self.assertEqual(self.decision(APIFY, self.actor(name=name)), "deny", name[:40])

    def test_actor_tilde_form_passes_but_only_for_the_right_owner(self):
        self.assertIsNone(self.decision(APIFY, self.actor(name="khadinakbar~scrape-google-serp")))
        self.assertEqual(self.decision(APIFY, self.actor(name="evil~scrape-google-serp")), "deny")


class MalformedPayloadTests(OutsideWorkspaceCase):
    """An unreadable hook payload must block (exit 2), never wave the call through."""

    BAD = (b"", b" ", b"{", b'{"tool_name": ', b"null", b"42", b'"text"', b"[]", b"NaN", b"true",
           b'{"tool_name": "x", "tool_input": NaN}', b'{"tool_name": "x", "tool_input": {"v": Infinity}}',
           b'{"tool_name": "x"} trailing', b"\xff\xfe{}", b"\x00\x00", b"{'tool_name': 'x'}",
           b'{"tool_name": "x",}', b"\xef\xbb\xbf{")

    def test_unreadable_payloads_exit_2_in_both_modes(self):
        for mode in ("pre", "post"):
            for raw in self.BAD:
                code, decision, _ = self.run_raw(mode, raw)
                self.assertEqual(code, 2, (mode, raw))
                self.assertIsNone(decision)

    def test_tool_name_must_be_a_string(self):
        for name in (None, 5, ["x"], {"a": 1}, True):
            payload = json.dumps({"tool_name": name, "tool_input": {}, "cwd": self.outside}).encode()
            self.assertEqual(self.run_raw("pre", payload)[0], 2, name)

    def test_missing_tool_name_is_unreadable(self):
        self.assertEqual(self.run_raw("pre", b'{"tool_input": {}}')[0], 2)

    def test_deep_nesting_never_fails_open(self):
        deep = b'{"tool_name": "%s", "tool_input": {"actor": "khadinakbar/x", "input": %s0%s}}' % (
            APIFY.encode(), b"[" * 200000, b"]" * 200000)
        code, decision, _ = self.run_raw("pre", deep)
        self.assertTrue(code == 2 or decision == "deny", (code, decision))

    def test_huge_inputs_do_not_fail_open_or_hang(self):
        big = {"tool_name": APIFY, "cwd": self.outside,
               "tool_input": {"actor": "khadinakbar/x", "input": {"q": ["x" * 50] * 100000},
                              "callOptions": {"maxTotalChargeUsd": 1e308}}}
        code, decision, _ = self.run_raw("pre", json.dumps(big).encode())
        self.assertEqual(code, 0)
        self.assertEqual(decision, "deny")  # 1e308 is above the daily ceiling

    def test_overlong_integer_cap_is_rejected(self):
        raw = b'{"tool_name": "%s", "tool_input": {"actor": "khadinakbar/x", "callOptions": {"maxTotalChargeUsd": %s}}}' % (
            APIFY.encode(), b"9" * 6000)
        code, decision, _ = self.run_raw("pre", raw)
        self.assertTrue(code == 2 or decision == "deny", (code, decision))

    def test_post_with_unusable_cap_records_nothing_and_does_not_crash(self):
        code, _, _ = self.run_gate("post", APIFY, self.actor(cap=None), cwd=self.outside)
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.home, "state.json")))


if __name__ == "__main__":
    unittest.main()
