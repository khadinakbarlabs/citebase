"""Private project exercises through the signed-in Apify input interface."""
import json
import io
import logging
import pathlib
import sys
import unittest
from types import SimpleNamespace as Row
from unittest.mock import AsyncMock, Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "connector"))
import history
import main
import storage
import work_auth


class ManagedProjectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        storage.set_backend(storage.MemoryBackend())
        self.addCleanup(storage.set_backend, None)
        self.actor = Mock()
        self.actor.configuration = Row(actor_run_id="run01", actor_id="actor01", user_id="owner",
                                       default_key_value_store_id="default1", input_key="INPUT", token="unit-token",
                                       api_base_url="https://api.apify.com")
        self.actor.is_at_home.return_value = True
        self.client = Mock()
        self.run = Row(id="run01", act_id="actor01", user_id="owner", default_key_value_store_id="default1",
                       meta=Row(origin="MCP"))
        self.client.run.return_value.get = AsyncMock(return_value=self.run)
        self.client.user.return_value.get = AsyncMock(return_value=Row(id="owner", username="account"))
        self.info = Row(id="private01", user_id="owner", name="citebase-mcp-results-actor01", general_access="RESTRICTED")
        self.client.key_value_stores.return_value.get_or_create = AsyncMock(return_value=self.info)
        self.store = self.client.key_value_store.return_value
        self.store.get = AsyncMock(return_value=self.info)
        self.store.update = AsyncMock(return_value=self.info)
        self.records = {}
        async def set_record(key, value):
            self.records[key] = value
        self.store.set_record = AsyncMock(side_effect=set_record)
        self.store.get_record = AsyncMock(side_effect=lambda key: {"value": self.records[key]} if key in self.records else None)
        self.actor.get_value = AsyncMock(return_value={"private_request": "ENCRYPTED_JSON:a:b"})
        self.actor.get_input = AsyncMock()
        for name in ("push_data", "fail", "set_value", "set_status_message"):
            setattr(self.actor, name, AsyncMock())
        self.enterContext(patch.object(main, "Actor", self.actor))
        self.enterContext(patch.object(work_auth, "new_client", return_value=self.client))

    async def run_tool(self, tool, request, **extra):
        self.actor.get_input.return_value = {"tool": tool, "private_request": request, **extra}
        await main.run_once()
        return self.actor

    def test_schema_encrypts_private_arguments_and_offers_project_work(self):
        properties = json.loads((ROOT / ".actor/input_schema.json").read_text())["properties"]
        self.assertEqual(properties["private_request"]["type"], "object")
        self.assertTrue(properties["private_request"]["isSecret"])
        self.assertIn("project_work", properties["tool"]["enum"])

    async def test_managed_read_and_write_use_normal_project_and_publish_only_locator(self):
        await history.save_results("demo-site", [], brand={"name": "Sample"})
        args = {"project": "demo-site", "operation": "brief_save",
                "data": {"goal": "Private fixture description", "expected_revision": 0}}
        actor = await self.run_tool("project_work", args)
        actor.fail.assert_not_awaited()
        locator = actor.set_value.await_args.args[1]["private_result"]
        self.assertEqual(locator, {"store_id": "private01", "key": "result.run01"})
        private = self.records[locator["key"]]
        self.assertTrue(private["ok"])
        self.assertEqual(private["result"]["result"]["brief"]["goal"], "Private fixture description")
        public_outputs = str(actor.push_data.await_args_list) + str(actor.set_value.await_args_list)
        self.assertNotIn("Private fixture", public_outputs)
        self.assertNotIn("demo-site", public_outputs)
        actor.get_value.assert_awaited_once_with("INPUT")
        self.assertIsNone(work_auth._request.get())
        actor.configuration.actor_run_id = self.run.id = "run02"
        await self.run_tool("project_work", {"project": "demo-site", "operation": "brief_get"})
        self.assertEqual(self.records["result.run02"]["result"]["result"]["brief"]["goal"], "Private fixture description")

    async def test_managed_created_project_is_editable_through_verified_dashboard_bearer(self):
        from server import build_app
        from starlette.testclient import TestClient
        await self.run_tool("save_results", {"project": "sample-site", "brand": {"name": "Sample", "domain": "sample.example"},
                                             "create_only": True})
        self.actor.fail.assert_not_awaited()
        headers = {"Authorization": "Bearer dashboard-unit", "X-Apify-Authorization": "Bearer platform-unit"}
        with patch.object(work_auth, "tenant_id", return_value="owner"), TestClient(build_app()) as dashboard:
            reply = dashboard.patch("/v1/projects/sample-site/brief", headers=headers,
                                    json={"expected_revision": 0, "goal":"Dashboard entry"})
            self.assertEqual(reply.status_code, 200, reply.text)
        self.actor.configuration.actor_run_id = self.run.id = "run02"
        await self.run_tool("project_work", {"project": "sample-site", "operation": "brief_get"})
        self.assertEqual(self.records["result.run02"]["result"]["result"]["brief"]["goal"], "Dashboard entry")
        self.actor.configuration.actor_run_id = self.run.id = "run03"
        await self.run_tool("get_history", {})
        self.assertEqual(self.records["result.run03"]["result"]["projects"][0]["project"], "sample-site")

    async def test_no_work_on_unverified_encryption_identity_or_result_store(self):
        args = {"project": "demo-site", "operation": "brief_save", "data": {"goal": "Private fixture"}}
        with patch("runner.run_tool", new_callable=AsyncMock) as dispatch:
            self.actor.get_value.return_value = {"private_request": args}
            await self.run_tool("project_work", args)
            self.actor.get_value.return_value = {"private_request": "ENCRYPTED_JSON:a:b"}
            self.run.user_id = "someone-else"
            await self.run_tool("project_work", args)
            self.run.user_id = "owner"
            self.run.meta.origin = "STANDBY"
            await self.run_tool("project_work", args)
            self.run.meta.origin = "API"
            self.info.general_access = "ANYONE_WITH_ID_CAN_READ"
            await self.run_tool("project_work", args)
            self.info.general_access = "RESTRICTED"
            self.info.user_id = "someone-else"
            await self.run_tool("project_work", args)
            self.assertEqual(self.actor.fail.await_count, 5)
            self.assertNotIn("Private fixture", str(self.actor.fail.await_args_list))
            self.store.set_record.assert_not_awaited()
            dispatch.assert_not_awaited()

    async def test_sensitive_error_is_available_only_in_the_private_record(self):
        with patch("runner.run_tool", new_callable=AsyncMock, side_effect=ValueError("Private fixture correction")):
            await self.run_tool("get_history", {"project": "private-site"})
        self.actor.fail.assert_awaited_once()
        self.assertFalse(self.records["result.run01"]["ok"])
        self.assertIn("Private fixture correction", self.records["result.run01"]["error"])
        outputs = str(self.actor.push_data.await_args_list) + str(self.actor.set_value.await_args_list) + str(self.actor.fail.await_args)
        self.assertNotIn("Private fixture", outputs)

    async def test_result_store_honors_explicit_sharing_and_only_initializes_the_default(self):
        from managed_project import result_store
        def restrict(**_):
            self.info.general_access = "RESTRICTED"
        self.store.update.side_effect = restrict
        for access in ("ANYONE_WITH_ID_CAN_READ", "ANYONE_WITH_NAME_CAN_READ", "UNKNOWN_POLICY"):
            self.info.general_access = access
            with self.subTest(access=access):
                with self.assertRaisesRegex(ValueError, "Restricted"):
                    await result_store(self.client, self.run)
                self.store.update.assert_not_awaited()
                self.store.set_record.assert_not_awaited()
        self.info.general_access = "FOLLOW_USER_SETTING"
        _, info = await result_store(self.client, self.run)
        self.assertEqual(info.general_access, "RESTRICTED")
        await result_store(self.client, self.run)
        self.store.update.assert_awaited_once_with(general_access="RESTRICTED")

    async def test_old_and_mixed_plaintext_inputs_never_authorize_project_work(self):
        self.actor.get_input.return_value = {"tool":"project_work","arguments":{"project":"demo-site","operation":"brief_get"}}
        with patch("runner.run_tool", new_callable=AsyncMock) as dispatch:
            await main.run_once()
            await self.run_tool("project_work", {"project":"demo-site"}, arguments={"operation":"brief_get"})
            self.assertEqual(self.actor.fail.await_count, 2)
            self.store.set_record.assert_not_awaited()
            dispatch.assert_not_awaited()

    async def test_privileged_schedules_point_back_to_the_dashboard(self):
        with patch("runner.run_tool", new_callable=AsyncMock) as dispatch:
            await self.run_tool("project_work", {"project":"demo-site","operation":"schedule_apply","data":{"confirmed":True}})
            dispatch.assert_not_awaited()
        self.assertIn("dashboard", self.records["result.run01"]["error"])

    async def test_restarted_run_reuses_its_receipt_and_preserves_indeterminate_work(self):
        args = {"project": "demo-site"}
        self.records["result.run01"] = {"ok": True, "result": {"private": True}}
        with patch("runner.run_tool", new_callable=AsyncMock) as dispatch:
            await self.run_tool("get_history", args)
            self.actor.fail.assert_not_awaited()
            self.records["result.run01"] = {"status": "started"}
            await self.run_tool("get_history", args)
            self.actor.fail.assert_awaited_once()
            dispatch.assert_not_awaited()

    def test_http_framework_logs_omit_customer_details(self):
        import server
        from starlette.testclient import TestClient
        stream = io.StringIO()
        observer = logging.StreamHandler(stream)
        root_log = logging.getLogger()
        root_log.addHandler(observer)
        self.addCleanup(root_log.removeHandler, observer)
        for name in ("httpx", "httpx2", "mcp.server.mcpserver.server"):
            framework_log = logging.getLogger(name)
            self.addCleanup(framework_log.setLevel, framework_log.level)
            framework_log.setLevel(logging.INFO)
        server.setup_logging()
        with patch("project_work.execute", side_effect=ValueError("PRIVATE-FIXTURE-CORRECTION")), TestClient(server.build_app()) as client:
            response = client.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                         "params": {"name": "project_work", "arguments": {"project": "private-site", "operation": "brief_get"}}})
            self.assertTrue(response.json()["result"]["isError"])
            client.get("/v1/projects/PRIVATE-FIXTURE-PATH/brief")
        self.assertNotIn("PRIVATE-FIXTURE", stream.getvalue())
