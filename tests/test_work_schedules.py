import asyncio
import datetime as dt
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))
import runner
import storage
import work_schedules as ws


class ScheduleControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.be = storage.MemoryBackend()
        storage.set_backend(self.be)
        self.addCleanup(storage.set_backend, None)
        await runner.run_tool(
            "save_results", {"project": "acme", "brand": {"name": "Acme", "domain": "example.com"}}
        )
        self.schedules = {}

        async def create(**kw):
            record = NS(id="id001", **kw)
            self.schedules[record.id] = record
            return record

        self.create = AsyncMock(side_effect=create)

        async def iterate():
            for resource in self.schedules.values():
                yield resource

        self.client = NS(
            schedules=lambda: NS(create=self.create, iterate=iterate),
            schedule=lambda key: NS(
                get=AsyncMock(side_effect=lambda: self.schedules.get(key)),
                update=AsyncMock(side_effect=lambda **kw: self.update(**kw)),
            ),
        )
        self.identity = patch.object(ws, "_account", AsyncMock(return_value=(self.client, "owner", "actorId")))
        self.identity.start()
        self.addCleanup(self.identity.stop)
        self.preview = await ws.execute(
            "acme", "schedule_preview", {"frequency": "weekly", "timezone": "Asia/Karachi", "monthly_allowance": 2}
        )

    def update(self, **kw):
        item = next(iter(self.schedules.values()))
        for k, v in kw.items():
            setattr(item, k, v)
        return item

    async def test_saved_schedule_proposal_can_be_reviewed_by_its_account_without_a_run(self):
        pid = self.preview["plan_id"]
        self.assertEqual(self.preview["review_url"], f"https://citebase-iota.vercel.app/app/#/schedules?project=acme&plan={pid}")
        with patch.object(self.be, "set", side_effect=AssertionError("review must only read")):
            review = await ws.execute("acme", "schedule_preview", {"plan_id": pid})
            self.assertEqual(review["cadence"], self.preview["cadence"])
            self.assertFalse(review["revises_existing"])
            for project, owner in (("another-site", "owner"), ("acme", "different-owner")):
                with patch.object(ws, "_account", AsyncMock(return_value=(self.client, owner, "actorId"))), self.assertRaises(ValueError):
                    await ws.execute(project, "schedule_preview", {"plan_id": pid})
        self.create.assert_not_awaited()

    async def test_modified_stored_proposal_requires_a_new_preview(self):
        pid = self.preview["plan_id"]
        key = ws.plan_key("acme", pid)
        plan = await self.be.get(key)
        await self.be.set(key, {**plan, "cron": "* * * * *"})
        for operation, data in (("schedule_preview", {"plan_id":pid}), ("schedule_apply", {"plan_id":pid,"confirmed":True})):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "changed"):
                await ws.execute("acme", operation, data)
        self.create.assert_not_awaited()

    async def test_confirm_replay_and_project_bound_pause(self):
        args = {"plan_id": self.preview["plan_id"], "confirmed": True}
        for _ in range(2):
            await ws.execute("acme", "schedule_apply", args)
        self.create.assert_awaited_once()
        self.assertEqual(len(self.create.await_args.kwargs["actions"]), 1)
        args["schedule_id"] = "id001"
        self.assertFalse((await ws.execute("acme", "schedule_pause", args))["enabled"])
        self.assertFalse((await ws.execute("acme", "schedule_list", {}))["schedules"][0]["enabled"])
        with self.assertRaises(ValueError):
            await ws.execute("other", "schedule_resume", args)

    async def test_unconfirmed_and_stale_never_create(self):
        with self.assertRaises(ValueError):
            await ws.execute("acme", "schedule_apply", {"plan_id": self.preview["plan_id"]})
        await runner.run_tool(
            "save_results", {"project": "acme", "brand": {"name": "Acme", "domain": "elsewhere.org"}}
        )
        with self.assertRaises(ValueError):
            await ws.execute("acme", "schedule_apply", {"plan_id": self.preview["plan_id"], "confirmed": True})
        self.create.assert_not_awaited()

    async def test_custom_clock_pins_cron_guard_and_preview_without_changing_default_plans(self):
        same = await ws.execute("acme", "schedule_preview", {
            "frequency": "weekly", "timezone": "Asia/Karachi", "monthly_allowance": 2,
            "local_time": "08:00", "weekday": 0,
        })
        self.assertEqual(same["plan_id"], self.preview["plan_id"])
        custom = await ws.execute("acme", "schedule_preview", {
            "frequency": "weekly", "timezone": "Asia/Karachi", "local_time": "15:45", "weekday": 4,
        })
        plan = await self.be.get(ws.plan_key("acme", custom["plan_id"]))
        self.assertEqual(plan["cron"], "45 15 * * 5")
        when = dt.datetime(2026, 11, 20, 10, 45, tzinfo=dt.timezone.utc)
        self.assertEqual(ws.next_occurrence(custom, when - dt.timedelta(minutes=1)), when)
        self.assertIn("Friday", custom["cadence"])
        self.assertTrue(custom["planned_next_check"])
        self.create.assert_not_awaited()
        await ws.execute("acme", "schedule_apply", {"plan_id": custom["plan_id"], "confirmed": True})
        meta = NS(origin="SCHEDULER", schedule_id="id001", scheduled_at=when)
        self.be.client = NS(run=lambda _: NS(get=AsyncMock(return_value=NS(
            act_id="actorId", user_id="owner", meta=meta))))
        with patch.object(ws.si, "scheduled_run_id", return_value="parent"):
            await ws.begin("acme", custom["plan_id"], plan["input"]["arguments"])
            meta.scheduled_at += dt.timedelta(minutes=1)
            with self.assertRaisesRegex(ValueError, "outside"):
                await ws.begin("acme", custom["plan_id"], plan["input"]["arguments"])

    async def test_invalid_recurrence_does_not_create_an_unexpected_cron(self):
        for opts in ({"local_time": "24:00"}, {"local_time": "8:03"}, {"weekday": True},
                     {"frequency": "daily", "weekday": 1}, {"frequency": "monthly", "month_day": 29}):
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                await ws.execute("acme", "schedule_preview", opts)
        self.create.assert_not_awaited()

    async def test_queue_provisioning_restricts_only_a_proven_new_empty_resource(self):
        from work_storage import Selection
        fresh = NS(id="fresh001", name=None, user_id="owner", total_request_count=0, general_access="FOLLOW_USER_SETTING")
        existing = NS(id="older001", name="other", user_id="owner", total_request_count=0, general_access="ANYONE_WITH_ID_CAN_READ")
        names = {"other":existing}
        named = lambda name: NS(get=AsyncMock(side_effect=lambda: names.get(name)))
        async def claim(name, general_access):
            fresh.name, fresh.general_access = name, general_access
            names[name] = fresh
            return fresh
        update = AsyncMock(side_effect=claim)
        handles = {"owner~new":named("new"), "owner~other":named("other"), "fresh001":NS(update=update)}
        create = AsyncMock(return_value=fresh)
        client = NS(request_queue=handles.__getitem__, request_queues=lambda: NS(get_or_create=create))
        be = NS(client=client,selection=Selection("owner","owner",None,client))
        self.assertEqual((await ws.caller_queue(be, "other")).general_access, "ANYONE_WITH_ID_CAN_READ")
        create.assert_not_awaited()
        self.assertEqual((await ws.caller_queue(be, "new")).general_access, "RESTRICTED")
        create.assert_awaited_once_with()
        update.assert_awaited_once_with(name="new", general_access="RESTRICTED")
        self.assertEqual((await ws.caller_queue(be, "new")).id, fresh.id)
        update.assert_awaited_once()

    async def test_preview_omits_canonical_store_id_and_rejects_a_necessary_unprotected_grant(self):
        self.be.project_store_id = "base001"
        opts = {"frequency":"daily"}
        plan = await ws.execute("acme","schedule_preview",opts)
        self.assertNotIn("project_store_id",(await ws.load_plan(self.be,"acme",plan["plan_id"]))["input"])
        with patch("work_storage.runtime_opens_project_store",AsyncMock(return_value=False)), patch(
            "work_storage.require_private_project_store",AsyncMock(side_effect=ValueError("Restricted project store"))
        ):
            with self.assertRaisesRegex(ValueError,"Restricted"):
                await ws.execute("acme","schedule_preview",opts)
        self.create.assert_not_awaited()

    async def test_confirmed_queue_picker_ids_reopen_existing_caller_queues_in_a_limited_run(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / ".actor/input_schema.json").read_text())
        for field in ws.QUEUE_FIELDS:
            prop = schema["properties"][field]
            self.assertEqual((prop["editor"], prop["resourceType"], prop["resourcePermissions"]),
                             ("resourcePicker", "requestQueue", ["READ", "WRITE"]))
        with patch.object(storage, "actor_owned_store_name", side_effect=lambda name: name + "-v2-actor"):
            names = {ws.queue_name("schedule_ledger_id"): "Ledger001", ws.queue_name("schedule_lock_id", "acme"): "Lock001"}
            info = {ident: NS(id=ident, name=name, user_id="owner", general_access="RESTRICTED") for name, ident in names.items()}
            calls = NS(get_or_create=AsyncMock(side_effect=lambda name: info[names[name]]))
            queue = NS(add_request=AsyncMock(return_value=NS(was_already_present=False)), get_request=AsyncMock(return_value=None))
            caller = NS(request_queues=lambda: calls, request_queue=lambda ident: NS(
                get=AsyncMock(return_value=info[ident]), add_request=queue.add_request, get_request=queue.get_request))
            be = NS(client=caller, get=self.be.get, set=self.be.set, keys=self.be.keys, delete=self.be.delete)
            pid = self.preview["plan_id"]
            await ws.manage("acme", "schedule_apply", {"plan_id": pid, "confirmed": True}, self.client, "owner",
                            "actorId", be, storage.key("acme", "schedule"))
            body = json.loads(self.schedules["id001"].actions[0]["runInput"]["body"])
            self.assertEqual((body["schedule_ledger_id"], body["schedule_lock_id"]), ("Ledger001", "Lock001"))
            limited = NS(client=NS(request_queue=lambda ident: NS(get=AsyncMock(return_value=info[ident]))))
            with ws.queue_grants(body):
                self.assertEqual(await ws.queue_id(limited, "schedule_ledger_id"), "Ledger001")
                self.assertEqual(await ws.queue_id(limited, "schedule_lock_id", "acme"), "Lock001")
                with self.assertRaisesRegex(ValueError, "differs"):
                    await ws.queue_id(limited, "schedule_lock_id", "other")
            with self.assertRaisesRegex(ValueError, "two Apify queues"):
                with ws.queue_grants({"schedule_ledger_id": "Ledger001"}):
                    pass
            info["Ledger001"].general_access = "ANYONE_WITH_ID_CAN_READ"
            with self.assertRaisesRegex(ValueError, "Restricted"):
                await ws.manage("acme", "schedule_resume", {"plan_id": pid, "schedule_id": "id001", "confirmed": True},
                                self.client, "owner", "actorId", be, storage.key("acme", "schedule"))

    async def test_allowance_and_last_outcome_come_from_the_project_even_after_a_missing_event(self):
        now = dt.datetime.now(dt.timezone.utc)
        row = await ws.execute("acme", "schedule_apply", {"plan_id": self.preview["plan_id"], "confirmed": True})
        remote = self.schedules[row["schedule_id"]]
        remote.next_run_at = ws.next_occurrence(row, now)
        await ws.reserve(self.be, "acme", row["schedule_id"], now, 2, 2, charged_at=now)
        event = {"run_id": "observed", "schedule_id": row["schedule_id"], "plan_id": row["plan_id"],
                 "scheduled_at": now.isoformat(), "status": "partial", "checks": 2, "saved_answers": 0}
        await self.be.set(storage.key("acme", "schedule-events", "001"), event)
        await self.be.set(storage.key("acme", "schedule-events", "002"), {
            **event, "schedule_id": "unrelated", "status": "completed"})
        before = dict(self.be.data)
        current = (await ws.execute("acme", "schedule_list", {}))["schedules"][0]
        self.assertEqual(current["last_occurrence"]["run_id"], "observed")
        self.assertEqual(current["last_outcome"], "partial")
        self.assertEqual(current["monthly_reserved"], 2)
        self.assertEqual(current["checks_remaining"], 0)
        self.assertEqual(current["check_status"], "allowance_reached")
        self.assertEqual(current["next_run"], remote.next_run_at.isoformat())
        self.assertGreaterEqual(current["planned_next_check"], current["allowance_resets_at"])
        self.assertEqual(self.be.data, before)

    async def test_dst_skips_a_missing_wall_time_and_does_not_reserve_the_repeated_hour_twice(self):
        zone = "America/New_York"
        at = dt.datetime(2026, 3, 8, tzinfo=dt.timezone.utc)
        daily = {"frequency": "daily", "timezone": zone, "local_time": "02:30"}
        self.assertEqual(ws.next_occurrence(daily, at), dt.datetime(2026, 3, 9, 6, 30, tzinfo=dt.timezone.utc))
        first = dt.datetime(2026, 11, 1, 5, 30, tzinfo=dt.timezone.utc)
        await ws.reserve(self.be, "acme", "sch", first, 1, 3, charged_at=first, timezone=zone)
        with self.assertRaises(ws.DuplicateOccurrence):
            await ws.reserve(self.be, "acme", "sch", first + dt.timedelta(hours=1), 1, 3,
                             charged_at=first, timezone=zone)

    async def test_atomic_monthly_allowance_and_duplicate_occurrence(self):
        async def reserve(when):
            return await ws.reserve(self.be, "acme", "sch", when, 3, 6, charged_at=when)

        t = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
        outcomes = await asyncio.gather(
            *(reserve(t + dt.timedelta(days=i)) for i in (0, 0, 1, 2)), return_exceptions=True
        )
        self.assertEqual(sum(not isinstance(x, Exception) for x in outcomes), 2)
        await reserve(t.replace(month=12))

    async def test_revise_in_place_and_reject_previous_confirmation(self):
        apply = lambda pid: ws.execute("acme", "schedule_apply", {"plan_id": pid, "confirmed": True})
        original = await apply(self.preview["plan_id"])
        updated = await ws.execute("acme", "schedule_preview", {"frequency": "daily", "monthly_allowance": 4})
        row = await apply(updated["plan_id"])
        self.assertEqual(original["schedule_id"], row["schedule_id"])
        self.assertEqual(row["frequency"], "daily")
        with self.assertRaises(ValueError):
            await apply(original["plan_id"])
        self.create.assert_awaited_once()

    async def test_guard_rejects_duplicate_new_parent_and_records_outcome(self):
        pid = self.preview["plan_id"]
        await ws.execute("acme", "schedule_apply", {"plan_id": pid, "confirmed": True})
        plan = await self.be.get(ws.plan_key("acme", pid))
        args = {**plan["input"]["arguments"], "schedule_plan_id": pid}
        meta = NS(
            origin="SCHEDULER",
            schedule_id="id001",
            scheduled_at=dt.datetime(2026, 11, 2, 3, tzinfo=dt.timezone.utc),
        )
        parent = NS(act_id="actorId", user_id="owner", meta=meta)
        self.be.client = NS(run=lambda rid: NS(get=AsyncMock(return_value=parent)))
        with (
            patch.object(ws.si, "scheduled_run_id", side_effect=["first", "second"]),
            patch.object(runner, "scheduled_check", AsyncMock(return_value={"health_score": 50})) as check,
        ):
            await runner.run_tool("scheduled_check", args)
            with self.assertRaisesRegex(ValueError, "already reserved"):
                await runner.run_tool("scheduled_check", args)
            check.assert_awaited_once()
        rows = await ws.events(self.be, "acme")
        self.assertEqual(rows[0]["status"], "completed")
        self.assertEqual(rows[0]["run_id"], "first")

    async def test_migrated_confirmed_parent_reconciles_paid_receipt_without_a_new_audit_charge_or_reservation(self):
        panel = [{"prompt_id": "buy", "prompt": "Best notebooks?", "type": "consideration"}]
        await runner.run_tool("save_results", {"project": "acme", "panel": panel, "runs": [
            {"snapshot":"baseline", "prompt_id":"buy", "platform":"chatgpt", "recommended":True}]})
        plan = await ws.execute("acme", "schedule_preview", {"frequency":"daily", "include_ai":True,
                                "platforms":["chatgpt","google-aio"], "repeats":1, "monthly_allowance":3})
        pid = plan["plan_id"]
        await ws.execute("acme", "schedule_apply", {"plan_id":pid,"confirmed":True})
        args = (await ws.load_plan(self.be, "acme", pid))["input"]["arguments"]
        config = args["ai_import"]
        jobs = runner.managed_schedule_checks(config["managed_checks"], config, await ws.history.load_project("acme"))
        now = dt.datetime.now(dt.timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
        parent = NS(id="parent1", act_id="actorId", user_id="owner", stats=NS(migration_count=0),
                    meta=NS(origin="SCHEDULER", schedule_id="id001", scheduled_at=now))
        child = NS(id="child1", status="SUCCEEDED", default_dataset_id="dataset1", act_id=ws.si.CHILD_ACTOR_IDS[jobs[0]["actor"]],
                   meta=NS(actor_run_id=parent.id))
        self.be.client = NS(run=lambda rid: NS(get=AsyncMock(return_value=parent),wait_for_finish=AsyncMock(return_value=child)))
        self.be.child_client = NS(actor=AsyncMock(side_effect=AssertionError("unexpected paid start")))
        self.be.datasets["dataset1"] = [{"query":"Best notebooks?", "platform":"chatgpt", "brand_mentioned":False, "brand_mention_count":0}]
        receipt_key = storage.key("acme","scheduled-runs","scheduled-parent1")
        with patch.object(ws.si, "scheduled_run_id", return_value="parent1"), patch.object(runner,"audit",AsyncMock()) as audit:
            _, key, event = await ws.begin("acme", pid, args)
            await self.be.set(key, {**event,"site_health_score":82})
            await self.be.set(receipt_key, {"authorization":ws.si.fingerprint([config["input_fingerprints"],[j["cap"] for j in jobs]]),
                                            "runs":["child1",None]})
            with self.assertRaises(ws.DuplicateOccurrence):
                await runner.guarded_check({**args,"schedule_plan_id":pid})
            parent.stats.migration_count = 1
            first, second = await asyncio.gather(*(runner.guarded_check({**args,"schedule_plan_id":pid}) for _ in range(2)))
            for result in [first, second]:
                self.assertEqual(result["health_score"],82)
                self.assertEqual(result["ai_import"]["status"],"partial")
                self.assertEqual(result["ai_import"]["saved_answers"],1)
                self.assertEqual(result["ai_import"]["expected_answers"],2)
                self.assertEqual(result["ai_import"]["saved_datasets"],1)
                self.assertEqual(result["ai_import"]["expected_datasets"],2)
                self.assertIsNone(result["ai_import"]["alert"])
            self.assertIsNone((await runner.run_tool("get_history",{"project":"acme"}))["scheduled_alert"])
            self.assertEqual((await self.be.get(receipt_key))["runs"], ["child1",None])
            self.assertEqual((await self.be.get(key))["status"], "partial")
            self.assertEqual((await ws.execute("acme","schedule_list",{}))["schedules"][0]["monthly_reserved"],3)
            self.be.child_client.actor.assert_not_called()
            audit.assert_not_awaited()

    async def test_ambiguous_create_recovers_exact_binding_without_a_second_post(self):
        args = {"plan_id": self.preview["plan_id"], "confirmed": True}
        row = await ws.execute("acme", "schedule_apply", args)
        await self.be.delete(storage.key("acme", "schedule"))
        recovered = await ws.execute("acme", "schedule_apply", args)
        self.assertEqual(row["schedule_id"], recovered["schedule_id"])
        self.create.assert_awaited_once()

    async def test_definite_create_denial_requires_a_fresh_confirmation_but_timeout_never_reposts(self):
        opts = {"frequency": "weekly", "timezone": "Asia/Karachi", "monthly_allowance": 2}
        old = self.preview["plan_id"]
        args = {"plan_id": old, "confirmed": True}
        creator = self.create.side_effect
        self.create.side_effect = type("Denied", (Exception,), {"status_code": 403})()
        with self.assertRaises(Exception):
            await ws.execute("acme", "schedule_apply", args)
        with self.assertRaises(ValueError):
            await ws.execute("acme", "schedule_apply", args)
        self.create.assert_awaited_once()
        new = await ws.execute("acme", "schedule_preview", opts)
        self.assertNotEqual(new["plan_id"], old)
        args["plan_id"] = new["plan_id"]
        self.create.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            await ws.execute("acme", "schedule_apply", args)
        self.create.side_effect = creator
        self.assertEqual((await ws.execute("acme", "schedule_preview", opts))["plan_id"], args["plan_id"])
        with self.assertRaisesRegex(ValueError, "already attempted"):
            await ws.execute("acme", "schedule_apply", args)
        different = await ws.execute("acme", "schedule_preview", {"frequency": "daily"})
        with self.assertRaisesRegex(ValueError, "already attempted"):
            await ws.execute("acme", "schedule_apply", {**args, "plan_id": different["plan_id"]})
        self.assertEqual(self.create.await_count, 2)

    async def test_delayed_start_debits_current_utc_month(self):
        november = dt.datetime(2026, 11, 30, tzinfo=dt.timezone.utc)
        december = november + dt.timedelta(days=1)
        await ws.reserve(self.be, "acme", "sch", november, 1, 1, charged_at=december)
        with self.assertRaisesRegex(ValueError, "monthly"):
            await ws.reserve(self.be, "acme", "sch", december, 1, 1, charged_at=december)

    async def test_selected_question_subset_survives_paid_run_reconstruction(self):
        questions = [
            {"prompt_id": "a", "prompt": "Which notebooks?", "type": "awareness"},
            {"prompt_id": "b", "prompt": "Which markers?", "type": "consideration"},
        ]
        await runner.run_tool("save_results", {"project": "acme", "panel": questions})
        inputs = {
            "include_ai": True,
            "platforms": ["chatgpt"],
            "repeats": 1,
            "prompt_ids": ["b"],
            "monthly_allowance": 2,
        }
        summary = await ws.execute("acme", "schedule_preview", inputs)
        self.assertEqual(summary["checks_per_occurrence"], 2)
        self.assertEqual(summary["prompt_ids"], ["b"])
        self.assertGreater(summary["cap_per_occurrence_usd"], 0)
        plan = await self.be.get(ws.plan_key("acme", summary["plan_id"]))
        config = plan["input"]["arguments"]["ai_import"]
        data = await ws.history.load_project("acme")
        checks = runner.managed_schedule_checks(config["managed_checks"], config, data)
        self.assertEqual(checks[0]["input"]["customQueries"], ["Which markers?"])
        data["panel"][1]["prompt"] = "Edited question?"
        with self.assertRaisesRegex(ValueError, "differ"):
            runner.managed_schedule_checks(config["managed_checks"], config, data)

    async def test_platform_queue_atomic_insert_contract(self):
        from apify_client._models import RequestRegistration, RequestResource

        resource = RequestResource.model_validate(
            {"id": "req1", "url": "https://example.invalid/", "uniqueKey": "test", "userData": {"amount": 7}}
        )
        queue = NS(
            add_request=AsyncMock(
                side_effect=[
                    RequestRegistration(request_id="req1", was_already_present=False, was_already_handled=False),
                    RequestRegistration(request_id="req1", was_already_present=True, was_already_handled=False),
                ]
            ),
            get_request=AsyncMock(return_value=resource),
        )
        ledger = ws.Ledger(None, queue)
        self.assertEqual(await ledger.claim(["month", "acme", "2026-11", 0], 7), (True, 7))
        self.assertEqual(await ledger.claim(["month", "acme", "2026-11", 0], 1), (False, 7))
        calls = queue.add_request.await_args_list
        self.assertEqual(calls[0].args[0]["uniqueKey"], calls[1].args[0]["uniqueKey"])

    async def test_rejected_revision_can_be_corrected_and_uncertain_exact_put_retried(self):
        args = {"plan_id": self.preview["plan_id"], "confirmed": True}
        await ws.execute("acme", "schedule_apply", args)
        for error, frequency in [
            (type("Rejected", (Exception,), {"status_code": 403})(), "daily"),
            (TimeoutError(), "monthly"),
        ]:
            updated = await ws.execute("acme", "schedule_preview", {"frequency": frequency})
            args["plan_id"] = updated["plan_id"]
            with patch.object(self, "update", side_effect=error):
                with self.assertRaises(Exception):
                    await ws.execute("acme", "schedule_apply", args)
        row = await ws.execute("acme", "schedule_apply", args)
        self.assertEqual(row["frequency"], "monthly")
        self.create.assert_awaited_once()

    async def test_expired_signed_in_view_pauses_apify_and_never_resumes(self):
        date = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        updated = await ws.execute("acme", "schedule_preview", {"frequency": "daily", "stop_date": date})
        args = {"plan_id": updated["plan_id"], "confirmed": True}
        await ws.execute("acme", "schedule_apply", args)
        self.assertIn("pause", updated["stop_policy"])
        with patch.object(ws, "past_cutoff", return_value=True):
            import work_storage
            async with work_storage.for_caller(None, read_only=True):
                observed = await ws.execute("acme", "schedule_list", {})
            self.assertTrue(observed["schedules"][0]["needs_manual_pause"])
            self.assertTrue(self.schedules["id001"].is_enabled)
            result = await ws.execute("acme", "schedule_list", {})
            self.assertFalse(result["schedules"][0]["enabled"])
            self.assertFalse(self.schedules["id001"].is_enabled)
            with self.assertRaises(ValueError):
                await ws.execute("acme", "schedule_resume", {**args, "schedule_id": "id001"})

    async def test_final_run_pauses_only_its_matching_schedule_or_reports_missing_grant(self):
        today = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1)
        updated = await ws.execute(
            "acme", "schedule_preview", {"frequency": "daily", "stop_date": today.isoformat()}
        )
        pid = updated["plan_id"]
        await ws.execute("acme", "schedule_apply", {"plan_id": pid, "confirmed": True})
        plan = await self.be.get(ws.plan_key("acme", pid))
        remote = self.schedules["id001"]
        remote.user_id = "owner"
        parent = NS(user_id="owner", meta=NS(schedule_id="id001"))
        when = dt.datetime.combine(today, dt.time(8), dt.timezone.utc)
        self.be.client = self.client
        result = await ws.pause_at_final_check(self.be, "acme", pid, plan, parent, when)
        self.assertEqual(result, "paused")
        self.assertFalse(remote.is_enabled)
        remote.is_enabled = True
        with patch.object(self, "update", side_effect=PermissionError):
            self.assertEqual(
                await ws.pause_at_final_check(self.be, "acme", pid, plan, parent, when), "needs_signed_in_pause"
            )
        remote.user_id = "another-owner"
        self.assertEqual(
            await ws.pause_at_final_check(self.be, "acme", pid, plan, parent, when), "needs_signed_in_pause"
        )
        self.assertTrue(remote.is_enabled)

    async def test_expiring_platform_mutex_releases_after_an_error(self):
        queue = NS(
            add_request=AsyncMock(return_value=NS(request_id="mutex")),
            list_and_lock_head=AsyncMock(return_value=NS(items=[NS(id="mutex")])),
            delete_request_lock=AsyncMock(),
        )
        queues = NS(get_or_create=AsyncMock(return_value=NS(id="queue")))
        be = NS(client=NS(request_queues=lambda: queues, request_queue=lambda qid, client_key: queue))
        with patch.object(storage, "actor_owned_store_name", side_effect=lambda name: name + "-v2-actor"):
            with self.assertRaisesRegex(ValueError, "simulated"):
                async with ws.schedule_lock(be, "acme"):
                    raise ValueError("simulated")
        queue.delete_request_lock.assert_awaited_once_with("mutex")
        self.assertEqual(queue.list_and_lock_head.await_args.kwargs["lock_duration"], dt.timedelta(minutes=5))
