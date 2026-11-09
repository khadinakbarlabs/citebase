"""End-to-end test of the MCP server over HTTP. Skipped when the `mcp` package is not installed."""
import importlib.util
import json
import os
import socket
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
os.environ["CITEBASE_ALLOW_MEMORY"] = "1"  # the test server keeps projects in memory
HAVE = all(importlib.util.find_spec(m) for m in ("mcp", "uvicorn", "httpx"))
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
           "MCP-Protocol-Version": "2025-06-18"}


@unittest.skipUnless(HAVE, "mcp, uvicorn and httpx are not installed")
class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn
        from server import build_app
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.uv = uvicorn.Server(uvicorn.Config(build_app(), host="127.0.0.1", port=cls.port, log_level="warning"))
        cls.thread = threading.Thread(target=cls.uv.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.uv.started:
                break
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.uv.should_exit = True
        cls.thread.join(5)

    def rpc(self, method, params=None, id_=1):
        import httpx
        body = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}
        res = httpx.post(f"http://127.0.0.1:{self.port}/mcp", json=body, headers=HEADERS, timeout=30)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def call(self, name, args):
        out = self.rpc("tools/call", {"name": name, "arguments": args})
        return out["result"]

    def test_readiness_probe(self):
        import httpx
        res = httpx.get(f"http://127.0.0.1:{self.port}/", headers={"x-apify-container-server-readiness-probe": "1"})
        self.assertEqual(res.status_code, 200)

    def test_lists_the_tools_with_hints(self):
        tools = self.rpc("tools/list")["result"]["tools"]
        writes = {"save_results", "make_report", "import_ai_results"}
        self.assertEqual({t["name"] for t in tools}, {"get_playbook", "audit_site", "quote_cost",
                                                       "measure_recommendation_share", "next_steps",
                                                       "check_outreach_draft", "check_ai_content",
                                                       "get_history", "schedule_checks"} | writes)
        for t in tools:
            self.assertEqual(t["annotations"]["readOnlyHint"], t["name"] not in writes, t["name"])
            self.assertGreater(len(t["description"]), 100, t["name"])
            self.assertTrue(t["description"].rstrip().endswith("."), t["name"])

    def test_served_arguments_match_what_run_accepts(self):
        import runner
        for t in self.rpc("tools/list")["result"]["tools"]:
            self.assertEqual(set(t["inputSchema"].get("properties", {})), runner.ALLOWED_ARGS[t["name"]], t["name"])

    def test_instructions_carry_the_fixed_safety_and_setup_sentences(self):
        import server
        import tools
        self.assertIn(tools.DATA_NOT_INSTRUCTIONS, server.INSTRUCTIONS)
        self.assertIn(tools.WEB_FALLBACK, server.INSTRUCTIONS)
        self.assertIn(tools.SETUP_URL, server.INSTRUCTIONS)

    def test_measure_over_mcp_returns_headline_next_and_brand_warning(self):
        panel = [{"prompt_id": f"p{n:02d}", "prompt": f"best tool {n}", "type": "consideration"} for n in range(1, 21)]
        panel[0]["prompt"] = "is Acme the best tool"
        panel += [{"prompt_id": f"c{n}", "prompt": f"control {n}", "type": "control"} for n in range(1, 6)]
        runs = [{"snapshot": "baseline", "prompt_id": p["prompt_id"], "platform": "chatgpt", "repeat": r,
                 "recommended": p["prompt_id"] == "p02"} for p in panel for r in (1, 2, 3)]
        out = self.call("measure_recommendation_share", {"panel": panel, "runs": runs, "brand": {"name": "Acme"}})
        self.assertFalse(out.get("isError"), out)
        data = out["structuredContent"]
        self.assertTrue(data["headline"])
        self.assertTrue(data["next"])
        self.assertTrue(any("name the brand" in w for w in data["warnings"]), data["warnings"])

    def test_quote_cost_over_http(self):
        result = self.call("quote_cost", {"items": [{"job": "serp_page", "units": 15}]})
        self.assertFalse(result.get("isError"))
        data = result.get("structuredContent") or json.loads(result["content"][0]["text"])
        self.assertEqual(data["suggested_cap_usd"], 0.1)

    def test_playbook_over_http(self):
        result = self.call("get_playbook", {"name": "start"})
        text = json.dumps(result)
        self.assertIn("WEB MODE", text)

    def test_errors_are_tool_errors_with_help(self):
        result = self.call("get_playbook", {"name": "nope"})
        self.assertTrue(result["isError"])
        self.assertIn("Call get_playbook with no name", json.dumps(result))

    def post_run(self, body=None, raw=None):
        import httpx
        kwargs = {"content": raw} if raw is not None else {"json": body}
        return httpx.post(f"http://127.0.0.1:{self.port}/run", headers={"Content-Type": "application/json"},
                          timeout=30, **kwargs)

    def test_run_endpoint_returns_plain_json(self):
        res = self.post_run({"tool": "quote_cost", "arguments": {"items": [{"job": "serp_page", "units": 15}]}})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["result"]["suggested_cap_usd"], 0.1)

    def test_run_endpoint_errors_say_what_to_fix(self):
        bad_tool = self.post_run({"tool": "nope"})
        self.assertEqual(bad_tool.status_code, 400)
        self.assertIn("Choose one of", bad_tool.json()["error"])
        self.assertEqual(self.post_run(raw="not json").status_code, 400)
        self.assertEqual(self.post_run(body=[1, 2]).status_code, 400)
        self.assertEqual(self.post_run({"tool": "get_playbook", "arguments": {"wrong": 1}}).status_code, 400)

    PANEL = [{"prompt_id": f"p{i}", "prompt": f"question {i}", "type": t}
             for i, t in enumerate(["awareness", "awareness", "consideration", "consideration", "control", "control"], 1)]

    def test_save_history_report_over_mcp(self):
        runs = [{"snapshot": "baseline", "prompt_id": p["prompt_id"], "platform": "chatgpt", "repeat": r,
                 "recommended": p["prompt_id"] == "p1"} for p in self.PANEL for r in (1, 2, 3)]
        saved = self.call("save_results", {"project": "http-test", "panel": self.PANEL, "runs": runs,
                                           "brand": {"name": "Acme", "domain": "acme.com"}})
        self.assertFalse(saved.get("isError"), saved)
        self.assertEqual(saved["structuredContent"]["snapshots_saved"], {"baseline": 18})
        hist = self.call("get_history", {"project": "http-test"})["structuredContent"]
        self.assertEqual(hist["snapshots"][0]["snapshot"], "baseline")
        rep = self.call("make_report", {"project": "http-test"})["structuredContent"]
        self.assertEqual(rep["project"], "http-test")
        measured = self.call("measure_recommendation_share", {"project": "http-test"})["structuredContent"]
        self.assertEqual(measured["project"], "http-test")

    def test_missing_project_is_a_tool_error_with_help(self):
        result = self.call("get_history", {"project": "does-not-exist"})
        self.assertTrue(result["isError"])
        self.assertIn("save_results", result["content"][0]["text"])

    def test_run_endpoint_saves_and_reads_back(self):
        runs = [{"snapshot": "baseline", "prompt_id": p["prompt_id"], "platform": "chatgpt", "repeat": 1,
                 "recommended": False} for p in self.PANEL]
        res = self.post_run({"tool": "save_results", "arguments": {"project": "run-test", "panel": self.PANEL, "runs": runs}})
        self.assertEqual(res.status_code, 200, res.text)
        res = self.post_run({"tool": "get_history", "arguments": {"project": "run-test"}})
        self.assertEqual(res.json()["result"]["panel_prompts"], 6)

    def test_scheduled_check_is_not_an_mcp_tool_but_runs_through_run(self):
        names = {t["name"] for t in self.rpc("tools/list")["result"]["tools"]}
        self.assertNotIn("scheduled_check", names)
        res = self.post_run({"tool": "scheduled_check", "arguments": {"project": "sched-test", "url": "http://127.0.0.1:9/"}})
        self.assertEqual(res.status_code, 400)  # private address is refused, as for audit_site

    def test_run_endpoint_refuses_huge_bodies(self):
        res = self.post_run({"tool": "next_steps", "arguments": {"audit": {"pad": "x" * (2 * 1024 * 1024 + 10)}}})
        self.assertEqual(res.status_code, 413)

    def test_run_endpoint_stops_chunked_oversize(self):
        import httpx
        big = (b'{"tool":"get_playbook","arguments":{"pad":"' + b"x" * (2 * 1024 * 1024 + 10) + b'"}}' for _ in range(1))
        res = httpx.post(f"http://127.0.0.1:{self.port}/run", content=big, timeout=30)  # chunked, no length
        self.assertEqual(res.status_code, 413)

    def test_run_endpoint_refuses_string_booleans(self):
        runs = [{"snapshot": "baseline", "prompt_id": p["prompt_id"], "platform": "chatgpt", "repeat": 1,
                 "recommended": False} for p in self.PANEL]
        res = self.post_run({"tool": "save_results", "arguments": {"project": "flag-test", "panel": self.PANEL, "runs": runs}})
        self.assertEqual(res.status_code, 200, res.text)
        res = self.post_run({"tool": "save_results", "arguments": {"project": "flag-test", "runs": runs, "replace": "false"}})
        self.assertEqual(res.status_code, 400)
        self.assertIn("real boolean", res.json()["error"])

    def test_run_endpoint_refuses_private_audit(self):
        res = self.post_run({"tool": "audit_site", "arguments": {"url": "http://127.0.0.1:9/"}})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Cannot reach", res.json()["error"])

    def test_openapi_describes_run_first(self):
        spec = json.load(open(os.path.join(ROOT, ".actor", "web_server_openapi.json")))
        self.assertEqual(list(spec["paths"])[0], "/run")
        enum = spec["paths"]["/run"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["tool"]["enum"]
        import runner
        self.assertEqual(set(enum), set(runner.TOOL_NAMES))

    def test_calls_are_logged_without_any_content(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            import server
            server.log.handlers = [h for h in server.log.handlers if not getattr(h, "_citebase", False)]
            server.setup_logging()
            self.call("check_outreach_draft", {"to": ["secret.person@example.com"], "subject": "Confidential subject",
                                               "body": "Confidential body text for the log test."})
            self.call("get_playbook", {"name": "nope"})
        out = buf.getvalue()
        self.assertIn('"event": "tool_call"', out)
        self.assertIn('"tool": "check_outreach_draft"', out)
        self.assertIn('"ok": false', out)  # the failed get_playbook call is recorded as failed
        for secret in ("secret.person", "Confidential", "log test"):
            self.assertNotIn(secret, out)

    def test_private_address_audit_is_refused(self):
        result = self.call("audit_site", {"url": "http://127.0.0.1:9/"})
        self.assertTrue(result["isError"])
        self.assertIn("Cannot reach", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
