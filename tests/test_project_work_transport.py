import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "connector"))


class ProjectWorkTransport(unittest.IsolatedAsyncioTestCase):
    async def test_named_application_header_authenticates_and_conflicts_fail_closed(self):
        import work_auth
        from unittest.mock import Mock
        client = Mock()
        client.user.return_value.get = AsyncMock(return_value=type("User", (), {"id": "owner"})())
        custom, legacy, platform = b"x-citebase-authorization", b"authorization", b"x-apify-authorization"
        for headers, accepted in [
            ([(custom, b"Bearer selected"), (platform, b"Bearer routing")], True),
            ([(legacy, b"Bearer selected")], True),
            ([(custom, b"Bearer selected"), (legacy, b"Bearer selected")], True),
            ([(custom, b"Bearer selected"), (legacy, b"Bearer other")], False),
            ([(custom, b"Bearer selected"), (custom, b"Bearer selected")], False),
            ([(legacy, b"Bearer selected"), (legacy, b"Bearer selected")], False),
            ([(custom, b"Basic selected"), (legacy, b"Bearer selected")], False),
            ([(custom, b"Bearer selected,other")], False),
            ([(platform, b"Bearer routing")], False),
        ]:
            with self.subTest(names=[key for key, _ in headers], accepted=accepted), patch.object(
                work_auth, "tenant_id", return_value="owner"
            ), patch.object(work_auth, "new_client", return_value=client) as new_client:
                async def check(scope, receive, send):
                    if accepted:
                        self.assertIs(await work_auth.require_caller(), client)
                    else:
                        with self.assertRaises(work_auth.CallerError):
                            await work_auth.require_caller()
                await work_auth.middleware(check)({"type":"http","headers":headers}, None, None)
                if accepted:
                    new_client.assert_called_once_with("selected")
                else:
                    new_client.assert_not_called()

    def test_dashboard_preflight_permits_application_header(self):
        from server import build_app
        from starlette.testclient import TestClient
        origin = "https://citebase-iota.vercel.app"
        headers = {"Origin": origin, "Access-Control-Request-Method": "POST",
                   "Access-Control-Request-Headers": "Content-Type, X-Citebase-Authorization, X-Apify-Authorization"}
        with TestClient(build_app()) as client:
            approved = client.options("/run", headers=headers)
            self.assertEqual(approved.status_code, 200)
            self.assertEqual(approved.headers.get("Access-Control-Allow-Origin"), origin)
            self.assertNotIn("Access-Control-Allow-Credentials", approved.headers)
            denied = client.options("/run", headers={**headers, "Origin":"https://unrelated.example"})
            self.assertNotIn("Access-Control-Allow-Origin", denied.headers)
    async def test_work_requires_caller_even_for_reads(self):
        import project_work
        with self.assertRaisesRegex(ValueError, "sign in|Sign in"):
            await project_work.execute("test-site", "brief_get", {})

    async def test_one_shot_cannot_return_work(self):
        from main import uses_private_run_data
        self.assertTrue(uses_private_run_data("project_work", {"operation": "digest_get"}))

    async def test_account_must_match_before_access(self):
        import work_auth
        client = AsyncMock()
        client.user = lambda: type("Users", (), {"get": AsyncMock(return_value=type("User", (), {"id": "stranger"})())})()
        with patch.object(work_auth, "tenant_id", return_value="owner"), patch.object(work_auth, "new_client", return_value=client):
            async def check(scope, receive, send):
                with self.assertRaisesRegex(ValueError, "account"):
                    await work_auth.require_caller()
            await work_auth.middleware(check)({"type": "http", "headers": [(b"authorization", b"Bearer example")]}, None, None)
        with self.assertRaises(ValueError):
            await work_auth.require_caller()

    async def test_unknown_operation_is_rejected(self):
        import project_work
        with patch("work_auth.require_caller", new_callable=AsyncMock):
            with self.assertRaisesRegex(ValueError, "operation"):
                await project_work.execute("valid-site", "erase", {})

    def test_published_site_navigation_and_build(self):
        import tempfile
        sys.path.insert(0, str(ROOT / "scripts"))
        from build_site import build
        with tempfile.TemporaryDirectory() as d:
            output = pathlib.Path(d)
            build("https://example.com", output)
            landing = (output / "index.html").read_text()
            self.assertIn("northwind-cafe", landing)
            self.assertIn("acme-payroll", landing)
            self.assertIn("Sign in with Apify", landing)

    async def test_anonymous_server_refuses_saved_records_on_both_transports(self):
        from server import build_app
        from starlette.testclient import TestClient
        # ASGI lifespan starts the stateless MCP session manager.
        with TestClient(build_app()) as client:
            saved_calls = [("get_history", {"project": "acme", "answer_review": "baseline"}),
                           ("make_report", {"project": "acme"}),
                           ("save_results", {"project": "acme", "todo": [{"step": "x", "status": "open"}]})]
            for tool, arguments in saved_calls:
                response = client.post("/run", json={"tool": tool, "arguments": arguments})
                self.assertEqual(response.status_code, 401)
                rpc = client.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                                  json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": tool, "arguments": arguments}})
                self.assertTrue(rpc.json()["result"]["isError"])
            self.assertEqual(client.get("/v1/projects/acme/brief").status_code, 401)

    async def test_named_endpoint_and_mcp_share_saved_brief(self):
        import storage
        from server import build_app
        from starlette.testclient import TestClient
        import history
        storage.set_backend(storage.MemoryBackend())
        self.addCleanup(storage.set_backend, None)
        await history.save_results("demo-site", [], brand={"name": "Example"})
        with patch("work_auth.require_caller", new_callable=AsyncMock), TestClient(build_app()) as client:
            response = client.patch("/v1/projects/demo-site/brief", json={"expected_revision":0,"goal":"More bookings"})
            self.assertEqual(response.status_code, 200, response.text)
            rpc = client.post("/mcp", headers={"Accept":"application/json, text/event-stream"},
                              json={"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"project_work",
                                    "arguments":{"project":"demo-site","operation":"brief_get"}}})
            self.assertEqual(rpc.json()["result"]["structuredContent"]["result"]["brief"]["goal"], "More bookings")
