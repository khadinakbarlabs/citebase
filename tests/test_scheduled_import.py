import datetime as dt
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))

import runner
import storage
import tools

ACTOR = tools.PRICES["jobs"]["ai_brand_check"]["actor"]
WHEN = dt.datetime(2026, 11, 19, tzinfo=dt.timezone.utc)
PANEL = [{"prompt_id": "buy", "prompt": "Best notebooks?", "type": "awareness"}]


class ScheduledImportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.be = storage.MemoryBackend()
        storage.set_backend(self.be)
        self.addCleanup(storage.set_backend, None)
        self.env = patch.dict(os.environ, {"ACTOR_RUN_ID": "site-run"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.site = NS(id="site-run", user_id="account", meta=NS(origin="SCHEDULER", schedule_id="schedule1",
                                                                 scheduled_at=WHEN))
        self.peers = [self.run_item("finished", "dataset01")]
        self.be.client = NS(
            run=lambda _: NS(get=AsyncMock(return_value=self.site)),
            actor=lambda _: NS(get=AsyncMock(return_value=NS(id="actor1"))),
            runs=lambda: NS(list=AsyncMock(side_effect=lambda **kwargs: NS(items=self.peers))),
            key_value_store=lambda _: NS(get_record=AsyncMock(side_effect=lambda key: {"value": self.actor_input})),
        )
        self.be.datasets["dataset01"] = [{"query": "Best notebooks?", "platform": "chatgpt",
                                         "brand_mentioned": False, "brand_mention_count": 0}]
        self.be.dataset_sources["dataset01"] = ACTOR
        saved = {"project": "acme", "panel": PANEL, "brand": {"name": "Acme", "domain": "example.com"},
                 "runs": [{"snapshot": "baseline", "prompt_id": "buy", "platform": "chatgpt",
                           "recommended": True, "date": "2026-11-18"}]}
        await runner.run_tool("save_results", saved)
        plan = await runner.run_tool("schedule_checks", {"project": "acme", "repeats": 1})
        self.actor_input = plan["ai_checks"]["runs"][0]["input"]
        self.config = plan["ai_checks"]["site_check_input"]["arguments"].get("ai_import")
        self.audit = patch.object(runner, "audit", AsyncMock(return_value={
            "saved": {"trend": None}, "site": "https://example.com", "health_score": 90, "problems": [],
        }))
        self.audit.start()
        self.addCleanup(self.audit.stop)

    def run_item(self, run_id, dataset, *, status="SUCCEEDED", when=WHEN, schedule="schedule1", account="account"):
        return NS(id=run_id, default_dataset_id=dataset, default_key_value_store_id="run-store", status=status, act_id="actor1", user_id=account,
                  meta=NS(origin="SCHEDULER", schedule_id=schedule, scheduled_at=when))

    async def start(self):
        config = self.config
        if not getattr(self.be, "child_client", None):
            config = {k: v for k, v in config.items() if k != "managed_checks"}  # old saved schedules
        return await runner.run_tool("scheduled_check", {
            "project": "acme", "url": "https://example.com",
            "ai_import": config,
        })

    async def test_auto_import_uses_only_the_matching_occurrence_and_reports_the_drop(self):
        self.peers.extend([
            self.run_item("elsewhere", "wrongother", schedule="other"),
            self.run_item("yesterday", "wrongdate", when=WHEN - dt.timedelta(days=1)),
            self.run_item("someone", "wrongowner", account="another-account"),
        ])
        result = await self.start()
        self.assertEqual(result["ai_import"]["saved_answers"], 1)
        self.assertEqual(result["ai_import"]["alert"]["lost_questions"], 1)
        self.assertEqual(result["ai_import"]["alert"]["examples"], ["Best notebooks?"])
        self.assertEqual(result["ai_import"]["alert"]["compared_questions"], 1)
        self.assertEqual(result["ai_import"]["alert"]["compared_answers_per_round"], 1)
        history = await runner.run_tool("get_history", {"project": "acme"})
        self.assertEqual(history["scheduled_alert"]["lost_questions"], 1)
        repeated = await self.start()
        self.assertEqual(repeated["ai_import"]["saved_answers"], 1)
        history = await runner.run_tool("get_history", {"project": "acme"})
        self.assertEqual(len(history["snapshots"]), 2)

    async def test_failed_occurrence_does_not_save_a_round(self):
        self.peers[:] = [self.run_item("failed", "dataset01", status="FAILED")]
        result = await self.start()
        self.assertEqual(result["ai_import"]["status"], "failed")
        history = await runner.run_tool("get_history", {"project": "acme"})
        self.assertEqual(len(history["snapshots"]), 1)

    async def test_a_missing_engine_is_not_reported_as_a_lost_question(self):
        await runner.run_tool("save_results", {"project": "acme", "append": True, "runs": [{
            "snapshot": "baseline", "prompt_id": "buy", "platform": "gemini", "recommended": True,
        }]})
        result = await self.start()
        self.assertEqual(result["ai_import"]["saved_answers"], 1)
        self.assertIsNone(result["ai_import"]["alert"])

    async def test_only_contributing_datasets_count_as_coverage_and_partial_round_cannot_alert(self):
        plan = await runner.run_tool("schedule_checks", {"project":"acme","repeats":1,"platforms":["chatgpt","google-aio"]})
        config = plan["ai_checks"]["site_check_input"]["arguments"]["ai_import"]
        self.be.datasets["ignored02"] = [{"query":"Other question?", "platform":"chatgpt", "brand_mentioned":False}]
        self.be.dataset_sources["ignored02"] = ACTOR
        snapshot = "scheduled-site-run"
        with patch.object(runner.scheduled_import, "managed_datasets",
                          AsyncMock(return_value=(snapshot, ["dataset01","ignored02"]))):
            for _ in range(2):
                imported = await runner.import_scheduled("acme",config)
                self.assertEqual(imported["status"],"partial")
                self.assertEqual((imported["saved_datasets"],imported["expected_datasets"]),(1,2))
                self.assertEqual((imported["matched_answers"],imported["expected_answers"]),(1,2))
                self.assertIsNone(imported["alert"])
            saved = await runner.run_tool("get_history",{"project":"acme"})
            self.assertIsNone(saved["scheduled_alert"])
            self.assertEqual(len(saved["snapshots"]),2)

    async def test_api_or_manual_run_cannot_import_scheduled_datasets(self):
        self.site.meta.origin = "API"
        result = await self.start()
        self.assertEqual(result["ai_import"]["status"], "failed")

    async def test_plan_includes_the_exact_actor_counts(self):
        plan = await runner.run_tool("schedule_checks", {"project": "acme"})
        self.assertEqual(plan["ai_checks"]["site_check_input"]["arguments"]["ai_import"]["expected_runs"],
                         {ACTOR: 3})
        self.assertNotIn("ai_import", plan["free_site_check"]["input"]["arguments"])

    async def test_changed_run_input_is_not_imported_into_the_project(self):
        self.actor_input = {**self.actor_input, "brandName": "Another company"}
        result = await self.start()
        self.assertEqual(result["ai_import"]["status"], "failed")

    async def test_changed_saved_brand_requires_an_updated_schedule(self):
        await runner.run_tool("save_results", {"project": "acme", "brand": {"name": "Another company"}})
        result = await self.start()
        self.assertEqual(result["ai_import"]["status"], "failed")

    async def test_new_scheduled_import_starts_only_granted_children_and_reuses_the_saved_ids(self):
        self.be.client.runs = None
        run_child = self.run_item("child01", "dataset01")
        run_child.act_id = "BZdaMdtW2S4K6w4t9"
        run_child.meta.actor_run_id = self.site.id
        start = AsyncMock(return_value=run_child)
        self.be.child_client = NS(actor=lambda _: NS(start=start))
        self.be.client.run = lambda _: NS(
            get=AsyncMock(return_value=self.site),
            wait_for_finish=AsyncMock(return_value=run_child),
        )
        self.assertIn("managed_checks", self.config)
        first = await self.start()
        self.assertEqual(first["ai_import"]["status"], "imported")
        self.assertEqual(first["ai_import"]["saved_answers"], 1)
        self.assertEqual((await self.start())["ai_import"]["saved_answers"], 1)
        start.assert_awaited_once()
        self.assertFalse(start.await_args.kwargs["restart_on_error"])
        self.assertTrue(start.await_args.kwargs["max_total_charge_usd"] > 0)

    async def test_changed_managed_plan_never_starts_paid_checks(self):
        start = AsyncMock()
        self.be.child_client = NS(actor=lambda _: NS(start=start))
        self.config["managed_checks"]["settings_fingerprint"] = "different"
        self.assertEqual((await self.start())["ai_import"]["status"], "failed")
        start.assert_not_awaited()

    async def test_managed_schedule_refuses_mismatched_child_provenance(self):
        wrong = self.run_item("child01", "dataset01")
        wrong.act_id = "BZdaMdtW2S4K6w4t9"
        wrong.meta.actor_run_id = "other-parent"
        self.be.child_client = NS(actor=lambda _: NS(start=AsyncMock(return_value=wrong)))
        self.be.client.run = lambda _: NS(get=AsyncMock(return_value=self.site),
                                          wait_for_finish=AsyncMock(return_value=wrong))
        self.assertEqual((await self.start())["ai_import"]["status"], "failed")

    async def test_managed_schedule_cannot_start_ai_checks_from_the_api(self):
        self.site.meta.origin = "API"
        start = AsyncMock()
        self.be.child_client = NS(actor=lambda _: NS(start=start))
        config = await self.start()
        self.assertEqual(config["ai_import"]["status"], "failed")
        start.assert_not_awaited()

    async def test_schedule_carries_the_project_store_grant_on_its_outer_input(self):
        self.be.project_store_id = "ExistingStore123"
        plan = await runner.run_tool("schedule_checks", {"project": "acme", "repeats": 1})
        self.assertEqual(plan["ai_checks"]["site_check_input"]["project_store_id"], "ExistingStore123")
        self.assertEqual(plan["free_site_check"]["input"]["project_store_id"], "ExistingStore123")

    async def test_full_project_never_starts_paid_children(self):
        start = AsyncMock()
        self.be.child_client = NS(actor=lambda _: NS(start=start))
        with patch.object(storage, "MAX_SNAPSHOTS", 1):
            self.assertEqual((await self.start())["ai_import"]["status"], "failed")
        start.assert_not_awaited()

    async def test_duplicate_legacy_managed_occurrence_never_bills_a_second_parent(self):
        child = self.run_item("child01", "dataset01")
        child.act_id = "BZdaMdtW2S4K6w4t9"
        child.meta.actor_run_id = self.site.id
        start = AsyncMock(return_value=child)
        self.be.child_client = NS(actor=lambda _: NS(start=start))
        self.be.client.run = lambda _: NS(get=AsyncMock(return_value=self.site),
                                          wait_for_finish=AsyncMock(return_value=child))
        self.assertEqual((await self.start())["ai_import"]["status"], "imported")
        with patch.dict(os.environ, {"ACTOR_RUN_ID":"new-parent"}):
            self.assertEqual((await self.start())["ai_import"]["status"], "failed")
        start.assert_awaited_once()
