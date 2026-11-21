"""Reading a project must not initialize an Apify store, queue, record or access grant."""

import copy
import datetime as dt
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))

import history
import project_work
import storage
import work_auth
import work_storage


class ProjectReads(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        storage.set_backend(None)
        self.addCleanup(storage.set_backend, None)
        self.caller, self.runtime = Mock(), Mock()
        self.caller.user.return_value.get = AsyncMock(return_value=Obj(id="owner", username="acct"))
        self.enterContext(patch.object(work_auth, "require_caller", AsyncMock(return_value=self.caller)))
        self.enterContext(patch.object(work_storage, "runtime_identity", return_value=("owner", self.runtime)))
        self.records = {}
        self.resources = {}
        self.names = {}
        for name in (storage.STORE_NAME, storage.PRIVATE_STORE):
            self.add_resource(name)
        self.caller.key_value_store.side_effect = self.resource
        self.runtime.key_value_store.side_effect = self.resource
        for client in (self.runtime, self.caller):
            client.key_value_stores.side_effect = AssertionError("Read attempted to open a store collection")
            client.request_queue.side_effect = AssertionError("Read looked up an unneeded revision queue")
            client.request_queues.side_effect = AssertionError("Read attempted to create a queue")

    def add_resource(self, name):
        handle = Mock()
        handle.get = AsyncMock(side_effect=lambda: self.names.get(name))
        handle.update = AsyncMock(side_effect=AssertionError("Read attempted to change sharing"))
        handle.get_record = AsyncMock(side_effect=lambda key: {"value": self.records[(name, key)]}
                                      if (name, key) in self.records else None)
        handle.list_keys = AsyncMock(side_effect=lambda **kw: Obj(
            items=[Obj(key=k) for n, k in self.records if n == name and k.startswith(kw.get("prefix") or "")],
            is_truncated=False))
        handle.set_record = AsyncMock(side_effect=AssertionError("Read attempted to write a record"))
        self.resources[name] = handle

    def resource(self, value):
        return self.resources[value.removeprefix("acct~").removesuffix("-id")]

    def enable(self, name, access="RESTRICTED"):
        self.names[name] = Obj(id=name + "-id", user_id="owner", general_access=access)

    async def test_new_account_directory_is_empty_and_specific_project_is_missing(self):
        async with work_auth.legacy_scope("get_history", {}):
            self.assertEqual((await history.history())["projects"], [])
        with self.assertRaisesRegex(ValueError, "project"):
            await project_work.execute("alpha", "brief_get")
        self.assertIsNone(storage._caller_backend.get())

    async def test_old_project_can_read_initial_brief_and_legacy_action_without_private_resources(self):
        self.enable(storage.STORE_NAME)
        self.records[storage.STORE_NAME, storage.key("alpha", "meta")] = {
            "project": "alpha", "settings": {"language": "en"}, "todo": [{"step": "Fix title", "status": "open"}]}
        for private_exists in (False, True):
            if private_exists:
                self.enable(storage.PRIVATE_STORE)
            brief = await project_work.execute("alpha", "brief_get")
            self.assertEqual(brief["result"]["brief"]["language"], "en")
            self.assertEqual(brief["result"]["brief"]["revision"], 0)
            actions = await project_work.execute("alpha", "actions_list", read_only=True)
            self.assertEqual([a["title"] for a in actions["result"]["actions"]], ["Fix title"])
        self.enable(storage.PRIVATE_STORE, "ANYONE_CAN_READ")
        with self.assertRaisesRegex(ValueError, "private|Private"):
            await project_work.execute("alpha", "brief_get")
        self.resources[storage.PRIVATE_STORE].update.assert_not_awaited()

    async def test_saved_version_without_a_readable_queue_is_not_a_default_brief(self):
        import work_actions
        self.enable(storage.STORE_NAME)
        self.enable(storage.PRIVATE_STORE)
        self.records[storage.STORE_NAME, storage.key("alpha", "meta")] = {"project": "alpha"}
        key = storage.key("alpha", "work", work_actions.tag(storage.STORE_NAME + "-id")) + ".brief"
        self.records[storage.PRIVATE_STORE, key + ".v.000000000001." + "f" * 32] = {"revision": 1}
        absent = Mock(get=AsyncMock(return_value=None))
        for client in (self.runtime, self.caller):
            client.request_queue.side_effect = None
            client.request_queue.return_value = absent
        with self.assertRaisesRegex(ValueError, "revision|receipt|queue"):
            await project_work.execute("alpha", "brief_get")

    async def test_existing_elected_brief_is_returned_without_changing_its_store_or_queue(self):
        import work_actions
        self.enable(storage.STORE_NAME)
        self.enable(storage.PRIVATE_STORE)
        self.records[storage.STORE_NAME, storage.key("alpha", "meta")] = {"project": "alpha"}
        key = storage.key("alpha", "work", work_actions.tag(storage.STORE_NAME + "-id")) + ".brief"
        token = "a" * 32
        self.records[storage.PRIVATE_STORE, key + ".v.000000000002." + token] = {
            "revision": 2, "goal": "Grow qualified referrals", "_mutation": "fixture"}
        queue = Mock()
        queue.get = AsyncMock(return_value=Obj(id="queue-id", user_id="owner"))
        queue.get_request = AsyncMock(return_value=Obj(url="https://example.invalid/" + token))
        queue.add_request = AsyncMock(side_effect=AssertionError("Read added a queue request"))
        for client in (self.runtime, self.caller):
            client.request_queue.side_effect = None
            client.request_queue.return_value = queue
        brief = (await project_work.execute("alpha", "brief_get"))["result"]["brief"]
        self.assertEqual(brief, {"revision": 2, "goal": "Grow qualified referrals"})
        queue.get_request.assert_awaited_once()

    async def test_named_get_routes_leave_old_projects_and_weekly_archives_untouched(self):
        from server import build_app
        from starlette.testclient import TestClient
        backend = storage.MemoryBackend()
        storage.set_backend(backend)
        await history.save_results("alpha", [], brand={"name": "Alpha"},
                                   todo=[{"step": "Fix title", "status": "open"}])
        before = copy.deepcopy(backend.data)
        with TestClient(build_app()) as client:
            for resource in ("actions", "brief", "opportunities", "prospects", "digest", "offers"):
                reply = client.get("/v1/projects/alpha/" + resource)
                self.assertEqual(reply.status_code, 200, (resource, reply.text))
                head = client.head("/v1/projects/alpha/" + resource)
                self.assertEqual(head.status_code, 200, resource)
        self.assertIsNone(backend._private)
        self.assertEqual(backend.data, before)

    async def test_enabled_digest_can_be_read_without_electing_another_week(self):
        import work_outreach
        be = storage.MemoryBackend()
        storage.set_backend(be)
        await history.save_results("alpha", [], brand={"name": "Alpha"})
        with patch.object(work_outreach, "today_utc", return_value=dt.date(2026, 11, 4)):
            saved = await project_work.execute("alpha", "digest_save", {
                "enabled": True, "muteUnchanged": False, "recipients": []})
        self.assertEqual(len(saved["result"]["archive"]), 1)
        before = copy.deepcopy(be._private.data)
        with patch.object(work_outreach, "today_utc", return_value=dt.date(2026, 11, 11)):
            archive = (await project_work.execute("alpha", "digest_get", read_only=True))["result"]
            self.assertIsNone(archive["currentIssue"])
            self.assertEqual(archive["archive"], saved["result"]["archive"])
            self.assertEqual(be._private.data, before)
            materialized = (await project_work.execute("alpha", "digest_get"))["result"]
            self.assertEqual(len(materialized["archive"]), 2)

    async def test_legacy_read_and_preview_operations_do_not_provision_storage(self):
        storage.set_backend(storage.MemoryBackend())
        for tool, fields in (
                ("get_history", {}), ("schedule_checks", {"project": "alpha"}), ("quote_cost", {"project": "alpha"}),
                ("measure_recommendation_share", {"project": "alpha"}), ("next_steps", {"project": "alpha"}),
                ("save_results", {"check_only": True}), ("import_ai_results", {}), ("import_ai_results", {"save": False})):
            with self.subTest(tool=tool, fields=fields):
                async with work_auth.legacy_scope(tool, fields):
                    self.assertTrue(storage._read_only.get())
        for tool, fields in (("save_results", {"check_only": False}), ("import_ai_results", {"save": True}),
                             ("make_report", {}), ("audit_site", {"project": "alpha"})):
            with self.subTest(tool=tool, fields=fields):
                async with work_auth.legacy_scope(tool, fields):
                    self.assertFalse(storage._read_only.get())
