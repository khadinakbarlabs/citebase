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

    def test_lists_the_six_tools_with_hints(self):
        tools = self.rpc("tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {"get_playbook", "audit_site", "quote_cost",
                                                       "measure_recommendation_share", "next_steps",
                                                       "check_outreach_draft"})
        for t in tools:
            self.assertTrue(t["annotations"]["readOnlyHint"], t["name"])
            self.assertGreater(len(t["description"]), 100, t["name"])
            self.assertTrue(t["description"].rstrip().endswith("."), t["name"])

    def test_quote_cost_over_http(self):
        result = self.call("quote_cost", {"items": [{"job": "serp_page", "units": 15}]})
        self.assertFalse(result.get("isError"))
        data = result.get("structuredContent") or json.loads(result["content"][0]["text"])
        self.assertEqual(data["suggested_cap_usd"], 0.04)

    def test_playbook_over_http(self):
        result = self.call("get_playbook", {"name": "start"})
        text = json.dumps(result)
        self.assertIn("WEB MODE", text)

    def test_errors_are_tool_errors_with_help(self):
        result = self.call("get_playbook", {"name": "nope"})
        self.assertTrue(result["isError"])
        self.assertIn("Call get_playbook with no name", json.dumps(result))

    def test_private_address_audit_is_refused(self):
        result = self.call("audit_site", {"url": "http://127.0.0.1:9/"})
        self.assertTrue(result["isError"])
        self.assertIn("Cannot reach", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
