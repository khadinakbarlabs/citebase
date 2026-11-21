import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))

import storage
import work_auth
import work_storage as ws


class Forbidden(Exception):
    status_code = 403


class StoreScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_private_answer_sharing_is_checked_before_writes(self):
        self.configure("key_value_store", storage.STORE_NAME, "project01")
        _, answer = self.configure("key_value_store", storage.PRIVATE_STORE, "answer001")
        restricted = Obj(id="answer001", user_id="account1", general_access="RESTRICTED")
        answer.update = AsyncMock(return_value=restricted)
        with patch.object(ws, "runtime_identity", return_value=("account1", self.runtime)):
            for access in ("ANYONE_WITH_ID_CAN_READ", "ANYONE_WITH_NAME_CAN_READ", "UNKNOWN_POLICY"):
                answer.get.return_value.general_access = access
                with self.subTest(access=access):
                    async with ws.for_caller(self.caller) as backend:
                        with self.assertRaisesRegex(ValueError, "Restricted"):
                            await backend.private_store()
                    answer.update.assert_not_awaited()
                    answer.set_record.assert_not_called()
            answer.get.return_value.general_access = "FOLLOW_USER_SETTING"
            async with ws.for_caller(self.caller) as backend:
                self.assertEqual((await backend.private_store()).project_store_id, "answer001")
        answer.update.assert_awaited_once_with(general_access="RESTRICTED")

    async def test_verified_managed_run_uses_granted_ids_and_its_own_named_queue_without_a_profile(self):
        owner = "account1"
        base = Obj(id="project01", user_id=owner, name=storage.STORE_NAME, general_access="RESTRICTED")
        private = Obj(id="private01", user_id=owner, name=storage.PRIVATE_STORE, general_access="RESTRICTED")
        queue_name = "citebase-work-revisions-v1"
        queue = Obj(id="queue001", user_id=owner, name=queue_name)
        client = Mock()
        resources = {item.id: Mock(get=AsyncMock(return_value=item)) for item in (base, private, queue)}
        client.key_value_store.side_effect = resources.__getitem__
        client.request_queue.side_effect = {queue.id: resources[queue.id], "~" + queue_name: Mock(get=AsyncMock(return_value=None))}.__getitem__
        client.request_queues.return_value.get_or_create = AsyncMock(return_value=queue)
        client.user.side_effect = AssertionError("Limited runs need no account directory access")
        with (patch.object(ws, "runtime_identity", return_value=(owner, client)),
              work_auth.batch_caller(client, owner=owner, grants={storage.PRIVATE_STORE: private.id}),
              storage.project_store_grant(base.id)):
            async with ws.for_caller(client) as backend:
                self.assertEqual(backend.project_store_id, base.id)
                self.assertEqual((await backend.private_store()).project_store_id, private.id)
                self.assertIs(await backend.revision_queue(queue_name), resources[queue.id])
                private.user_id = "another-account"
                with self.assertRaisesRegex(ValueError, "does not belong"):
                    await backend.selection.resolve("key_value_store", storage.PRIVATE_STORE)
        client.request_queues.return_value.get_or_create.assert_awaited_once_with(name=queue_name)
        client.user.assert_not_called()

    async def test_private_grant_is_never_inferred_from_existing_store_settings(self):
        runtime, base = self.configure("key_value_store", storage.STORE_NAME, "selected")
        runtime.get.return_value.act_id = "actor1"
        with patch.object(ws, "runtime_identity", return_value=("account1", self.runtime)), patch.object(
            ws, "runtime_actor_id", return_value="actor1"
        ):
            async with ws.for_caller(self.caller) as backend:
                self.assertTrue(await ws.runtime_opens_project_store(backend))
                runtime.get.return_value.act_id = None
                self.assertFalse(await ws.runtime_opens_project_store(backend))
                self.assertTrue(await ws.require_private_project_store(backend))
                base.get.return_value.general_access = "FOLLOW_USER_SETTING"
                with self.assertRaisesRegex(ValueError, "Restricted"):
                    await ws.require_private_project_store(backend)
                base.update.assert_not_called()

    async def test_fresh_base_installs_private_name_before_any_project_content(self):
        fresh = Obj(id="freshbase", user_id="account1", name=None, general_access="FOLLOW_USER_SETTING")
        client = Mock()
        client.key_value_stores.return_value.get_or_create = AsyncMock(return_value=fresh)
        resource = client.key_value_store.return_value
        protected = Obj(id="freshbase", user_id="account1", name="chosen", general_access="RESTRICTED")
        resource.update = AsyncMock(return_value=protected)
        resource.get = AsyncMock(return_value=protected)
        result = await storage.new_private_project_store(client, "account1", "acct", "chosen")
        self.assertEqual(result.id, "freshbase")
        client.key_value_stores.return_value.get_or_create.assert_awaited_once_with()
        resource.update.assert_awaited_once_with(name="chosen", general_access="RESTRICTED")
        resource.set_record.assert_not_called()

    def setUp(self):
        self.runtime = Mock()
        self.caller = Mock()
        self.profile = Obj(id="account1", username="acct")
        self.caller.user.return_value.get = AsyncMock(return_value=self.profile)
        self.backend = storage.MemoryBackend()
        self.addCleanup(storage.set_backend, None)

    def configure(self, kind, name, ident, account="account1"):
        obj = Obj(id=ident, name=name, user_id=account, general_access="RESTRICTED")
        runtime_resource = Mock(get=AsyncMock(return_value=obj))
        caller_resource = Mock(get=AsyncMock(return_value=obj), get_record=AsyncMock(return_value={"value": "saved"}),
                               set_record=AsyncMock(side_effect=Forbidden()))
        runtime_fn = getattr(self.runtime, kind)
        resources = getattr(self, "runtime_" + kind, {})
        setattr(self, "runtime_" + kind, resources)
        resources["acct~" + name] = runtime_resource
        resources[ident] = runtime_resource
        runtime_fn.side_effect = lambda k: resources[k]
        caller_map = getattr(self, "caller_" + kind, {})
        setattr(self, "caller_" + kind, caller_map)
        caller_map[ident] = caller_resource
        getattr(self.caller, kind).side_effect = lambda k: caller_map[k]
        return runtime_resource, caller_resource

    async def test_limited_actor_selector_and_readonly_caller(self):
        run, _ = self.configure("key_value_store", storage.STORE_NAME, "legacy00")
        run.get = AsyncMock(side_effect=Forbidden())
        _, project = self.configure("key_value_store", storage.STORE_NAME + "-v2-actor000", "active00")
        _, content = self.configure("key_value_store", storage.PRIVATE_STORE, "private0")
        queue_run, _ = self.configure("request_queue", "citebase-work-revisions-v1", "legacyqueue")
        queue_run.get = AsyncMock(side_effect=Forbidden())
        _, queue = self.configure("request_queue", "citebase-work-revisions-v1-v2-actor000", "activequeue")
        records = {"p.acme.meta": {"value": "saved"}}
        project.get_record.side_effect = records.get
        project.set_record.side_effect = lambda k, v, **_: records.update({k: {"value": v}})
        with patch.object(ws, "runtime_identity", return_value=("account1", self.runtime)), patch.dict(
                "os.environ", {"ACTOR_ID": "actor000"}):
            async with ws.for_caller(self.caller):
                be = await storage.get_backend()
                self.assertIs(be.client, self.caller)
                self.assertIs(be.child_client, self.caller)
                self.assertEqual(be.project_store_id, "active00")
                self.assertEqual(await be.get("p.acme.meta"), "saved")
                private = await be.private_store()
                with self.assertRaises(Forbidden):
                    await private.set("test", 3)
                self.assertIs(await be.revision_queue("citebase-work-revisions-v1"), queue)
        content.set_record.assert_awaited_once()
        project.get_record.assert_any_await("p.acme.meta")
        self.runtime.key_value_stores.assert_not_called()
        self.runtime.request_queues.assert_not_called()

    async def test_caller_without_access_and_foreign_metadata_fail_closed(self):
        _, resource = self.configure("key_value_store", storage.STORE_NAME, "foreign00", "someoneelse")
        with patch.object(ws, "runtime_identity", return_value=("account1", self.runtime)):
            with self.assertRaises(ValueError):
                async with ws.for_caller(self.caller):
                    pass
            resource.get_record.assert_not_called()
            resource.get = AsyncMock(side_effect=Forbidden())
            self.runtime_key_value_store["acct~" + storage.STORE_NAME].get.return_value.user_id = "account1"
            with self.assertRaises((Forbidden, ValueError)):
                async with ws.for_caller(self.caller):
                    pass
        self.caller.key_value_stores.assert_not_called()

    async def test_explicit_fixture_only_and_context_reset(self):
        storage.set_backend(self.backend)
        with patch.object(ws, "runtime_identity", side_effect=AssertionError):
            async with ws.for_caller(None):
                self.assertIs(await storage.get_backend(), self.backend)
        self.assertIsNone(storage._caller_backend.get())

    def missing(self, kind, name):
        absent = Mock(get=AsyncMock(return_value=None))
        getattr(self, "runtime_" + kind)["acct~" + name] = absent
        getattr(self, "caller_" + kind)["acct~" + name] = absent

    async def test_missing_account_store_can_be_read_without_creating_it(self):
        self.configure("key_value_store", storage.STORE_NAME, "emptytest")
        self.missing("key_value_store", storage.STORE_NAME)
        with patch.object(ws, "runtime_identity", return_value=("account1", self.runtime)):
            async with ws.for_caller(self.caller, read_only=True) as backend:
                self.assertEqual(await backend.keys(), [])
                self.assertIsNone(await backend.get("p.missing.meta"))
                self.assertIsNone(await backend.public_url("p.missing.meta"))
                with self.assertRaisesRegex(ValueError, "only reads"):
                    await backend.set("p.missing.meta", {})
        self.caller.key_value_stores.assert_not_called()
        self.runtime.key_value_stores.assert_not_called()

    async def test_read_only_private_store_queue_permissions_and_failed_scope(self):
        _, root = self.configure("key_value_store", storage.STORE_NAME, "active00")
        _, private = self.configure("key_value_store", storage.PRIVATE_STORE, "private0")
        self.configure("request_queue", "citebase-work-revisions-v1", "queue00")
        self.missing("request_queue", "citebase-work-revisions-v1")
        with patch.object(ws, "runtime_identity", return_value=("account1", self.runtime)):
            async with ws.for_caller(self.caller, read_only=True) as backend:
                self.assertIsNone(await backend.revision_queue("citebase-work-revisions-v1"))
                with self.assertRaisesRegex(ValueError, "only reads"):
                    await backend.set("a", "b")
                with self.assertRaisesRegex(ValueError, "only reads"):
                    await backend.delete("a")
                private.get.return_value.general_access = "ANYONE_CAN_READ"
                with self.assertRaisesRegex(ValueError, "Private storage"):
                    await backend.existing_private_store()
                private.update.assert_not_called()
                self.missing("key_value_store", storage.PRIVATE_STORE)
                self.assertIsNone(await backend.existing_private_store())
        root.set_record.assert_not_called()
        root.delete_record.assert_not_called()
        self.caller.key_value_stores.assert_not_called()
        self.caller.request_queues.assert_not_called()

    async def test_page_iteration_deletion_and_signed_links_use_caller(self):
        _, project = self.configure("key_value_store", storage.STORE_NAME, "active00")
        project.list_keys = AsyncMock(side_effect=[
            Obj(items=[Obj(key="p.a")], is_truncated=True, next_exclusive_start_key="p.a"),
            Obj(items=[Obj(key="p.b")], is_truncated=False)])
        project.delete_record = AsyncMock()
        _, private = self.configure("key_value_store", storage.PRIVATE_STORE, "private0")
        private.get_record_public_url = AsyncMock(return_value="https://api.apify.com/x")
        with patch.object(ws, "runtime_identity", return_value=("account1", self.runtime)):
            async with ws.for_caller(self.caller) as backend:
                self.assertEqual(await backend.keys("p."), ["p.a", "p.b"])
                await backend.delete("p.a")
                restricted = await backend.private_store()
                self.assertIsNone(await restricted.public_url("report"))
        project.delete_record.assert_awaited_once_with("p.a")
        self.assertIsNone(storage._caller_backend.get())


class QueueBindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_writers_with_disjoint_grants_cannot_both_elect(self):
        import asyncio
        be = storage.MemoryBackend()
        name = "citebase-work-revisions-v1"
        entered = asyncio.Event()
        proceed = asyncio.Event()
        original = be.set
        async def interleave(key, ident):
            if key.endswith(".original"):
                entered.set()
                await proceed.wait()
            await original(key, ident)
        be.set = interleave
        a = asyncio.create_task(ws.reserve_queue(be, name, Obj(id="firstID", name=name), False))
        await entered.wait()
        await ws.reserve_queue(be, name, Obj(id="otherID", name=name+"-v2-actor"), False)
        proceed.set()
        with self.assertRaisesRegex(ValueError, "conflicting"):
            await a

    async def test_readonly_selection_never_creates_binding_and_later_alias_is_rejected(self):
        name = "citebase-work-revisions-v1"
        first = Obj(id="firstID", name=name)
        second = Obj(id="otherID", name=name+"-v2-actor")
        be = storage.MemoryBackend()
        await ws.reserve_queue(be, name, first, True)
        self.assertEqual(be.data, {})
        await ws.reserve_queue(be, name, first, False)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            await ws.reserve_queue(be, name, second, False)
        self.assertEqual(be.data[f"citebase-queue-binding.{name}.confirmed"]["id"], "firstID")

    async def test_explicit_queue_id_cannot_displace_visible_legacy_and_valid_limited_grant_works(self):
        name = "citebase-work-revisions-v1"
        suffix = name + "-v2-actor000"
        original = Obj(id="oldQueue", name=name, user_id="owner")
        new = Obj(id="newQueue", name=suffix, user_id="owner")
        caller, runtime = Mock(), Mock()
        new_resource = Mock(get=AsyncMock(return_value=new))
        caller.request_queue.side_effect = {new.id: new_resource}.__getitem__
        legacy_lookup = Mock(get=AsyncMock(return_value=original))
        runtime.request_queue.side_effect = {"~" + name: legacy_lookup,
                                             "~" + suffix: Mock(get=AsyncMock(return_value=new))}.__getitem__
        selection = ws.Selection("owner", "", runtime, caller, {"grants": {name: new.id}})
        records = {}
        project = Mock(get_record=AsyncMock(side_effect=lambda key: records.get(key)),
                       set_record=AsyncMock(side_effect=lambda k,v,**_: records.update({k: {"value": v}})))
        backend = ws.CallerBackend(selection, project, "project01")
        with patch.dict("os.environ", {"ACTOR_ID": "actor000"}):
            with self.assertRaisesRegex(ValueError, "conflicting"):
                await backend.revision_queue(name)
            self.assertEqual(records, {})
            legacy_lookup.get.side_effect = Forbidden()
            self.assertIs(await backend.revision_queue(name), new_resource)
            self.assertEqual(records[f"citebase-queue-binding.{name}.confirmed"]["value"]["id"], new.id)
            selection.batch = {"grants": {name: original.id}}
            with self.assertRaisesRegex(ValueError, "conflicting"):
                await backend.revision_queue(name)
