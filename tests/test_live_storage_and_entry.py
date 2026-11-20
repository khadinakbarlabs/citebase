"""The parts that only run on Apify: the key-value store backend, the one-shot entry point, and the failure log."""
import asyncio
import io
import json
import logging
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import history as hist  # noqa: E402
import storage as stg  # noqa: E402

try:
    import main as entry  # needs the Apify SDK
    import server
except ImportError:  # pragma: no cover - plain python without the connector's dependencies
    entry = server = None


def run(coro):
    return asyncio.run(coro)


class FakeStore:
    """Stands in for Apify's key-value store: values by key, keys listed in pages, None deletes."""

    def __init__(self, page_size=1000):
        self.values, self.page_size, self.calls = {}, page_size, 0

    async def get_value(self, key):
        return self.values.get(key)

    async def set_value(self, key, value, content_type=None):
        if value is None:
            self.values.pop(key, None)
        else:
            self.values[key] = value

    async def list_keys(self, exclusive_start_key=None, limit=1000):
        self.calls += 1
        keys = sorted(self.values)
        if exclusive_start_key is not None:
            keys = [k for k in keys if k > exclusive_start_key]
        return [SimpleNamespace(key=k) for k in keys[:limit]]

    async def get_public_url(self, key):
        return f"https://store.example/{key}"


class ApifyBackendTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.backend = stg.ApifyBackend(self.store)

    @unittest.skipUnless(entry, "Apify SDK is not installed")
    def test_answer_store_is_opened_only_after_access_is_restricted(self):
        provision = mock.AsyncMock(return_value=SimpleNamespace(id="private-id", general_access="FOLLOW_USER_SETTING"))
        update = mock.AsyncMock(return_value=SimpleNamespace(id="private-id", general_access="RESTRICTED"))
        client = SimpleNamespace(key_value_stores=lambda: SimpleNamespace(get_or_create=provision),
                                 key_value_store=lambda _: SimpleNamespace(update=update))
        backend = stg.ApifyBackend(self.store, client)
        with mock.patch.object(entry.Actor, "open_key_value_store", new=mock.AsyncMock(return_value=self.store)) as opened:
            private = run(backend.private_store())
            self.assertIs(private.kvs, self.store)
            provision.assert_awaited_once_with(name="citebase-private-answers")
            update.assert_awaited_once_with(general_access="RESTRICTED")
            opened.assert_awaited_once_with(id="private-id")
        update.return_value.general_access = "PUBLIC_READ"
        with mock.patch.object(entry.Actor, "open_key_value_store", new=mock.AsyncMock()) as opened:
            with self.assertRaisesRegex(ValueError, "confirm.*private"):
                run(stg.ApifyBackend(self.store, client).private_store())
            opened.assert_not_called()

    @unittest.skipUnless(entry, "Apify SDK is not installed")
    def test_explicit_prospect_sharing_is_preserved_before_open(self):
        for access in ("ANYONE_WITH_ID_CAN_READ", "ANYONE_WITH_NAME_CAN_READ", "UNKNOWN_POLICY"):
            with self.subTest(access=access), mock.patch.object(entry.Actor, "open_key_value_store", new=mock.AsyncMock()) as opened:
                client = mock.Mock()
                client.key_value_stores.return_value.get_or_create = mock.AsyncMock(
                    return_value=SimpleNamespace(id="prospect-id", general_access=access))
                client.key_value_store.return_value.update = mock.AsyncMock(
                    return_value=SimpleNamespace(id="prospect-id", general_access="RESTRICTED"))
                with self.assertRaisesRegex(ValueError, "Restricted"):
                    run(stg.ApifyBackend(self.store, client).prospect_store())
                client.key_value_store.return_value.update.assert_not_awaited()
                opened.assert_not_awaited()

    @unittest.skipUnless(entry, "Apify SDK is not installed")
    def test_limited_runtime_creates_its_own_store_when_legacy_access_is_denied(self):
        class Denied(Exception):
            status_code = 403

        api = mock.Mock()
        api.user.side_effect = AssertionError("A Limited Actor can lack account directory access")
        legacy = mock.Mock(get=mock.AsyncMock(side_effect=Denied()))
        fallback = mock.Mock(get=mock.AsyncMock(return_value=None))
        api.key_value_store.side_effect = {"~citebase-projects":legacy,
                                           "~citebase-projects-v2-privateactor":fallback}.__getitem__
        new = mock.AsyncMock(return_value=SimpleNamespace(id="fresh1"))
        actor = SimpleNamespace(configuration=SimpleNamespace(user_id="owner1"), apify_client=api,
                                open_key_value_store=mock.AsyncMock(return_value=self.store))
        stg.set_backend(None)
        self.addCleanup(stg.set_backend, None)
        with (mock.patch.dict(os.environ, {"APIFY_IS_AT_HOME": "1", "ACTOR_ID": "PrivateActor",
                                           "ACTOR_PERMISSION_LEVEL": "LIMITED_PERMISSIONS"}),
              mock.patch.object(stg, "new_private_project_store", new), mock.patch("apify.Actor", actor)):
            self.assertIs(run(stg.get_backend()).kvs, self.store)
        new.assert_awaited_once_with(api, "owner1", "", "citebase-projects-v2-privateactor")
        actor.open_key_value_store.assert_awaited_once_with(id="fresh1")

    @unittest.skipUnless(entry, "Apify SDK is not installed")
    def test_an_explicit_project_storage_grant_is_used_for_that_call(self):
        opened = mock.AsyncMock(return_value=self.store)
        with (mock.patch.dict(os.environ, {"APIFY_IS_AT_HOME": "1"}),
              mock.patch("apify.Actor", SimpleNamespace(open_key_value_store=opened, apify_client=None))):
            async def check():
                with stg.project_store_grant("AttachedStore123"):
                    self.assertIs((await stg.get_backend()).kvs, self.store)
            run(check())
        opened.assert_awaited_once_with(id="AttachedStore123")

    def test_restricted_store_requires_a_signed_share_link(self):
        store = FakeStore()
        backend = stg.ApifyBackend(store, signed_urls=True)
        self.assertIsNone(run(backend.public_url("report.html")))
        good = "https://api.apify.com/v2/key-value-stores/test/records/report.html?signature=fixture"
        store.get_public_url = mock.AsyncMock(return_value=good)
        self.assertEqual(run(backend.public_url("report.html")), good)
        store.get_public_url.return_value = good + "&token=fixture"
        self.assertIsNone(run(backend.public_url("report.html")))

    def test_values_round_trip_and_delete_removes_the_record(self):
        run(self.backend.set("p.acme.meta", {"a": 1}))
        self.assertEqual(run(self.backend.get("p.acme.meta")), {"a": 1})
        run(self.backend.delete("p.acme.meta"))
        self.assertIsNone(run(self.backend.get("p.acme.meta")))
        self.assertEqual(run(self.backend.keys("p.")), [])

    def test_keys_are_filtered_by_prefix_and_sorted(self):
        for key in ("p.beta.meta", "p.acme.runs.baseline", "other", "p.acme.meta"):
            run(self.backend.set(key, 1))
        self.assertEqual(run(self.backend.keys("p.acme.")), ["p.acme.meta", "p.acme.runs.baseline"])

    def test_listing_follows_every_page(self):
        for n in range(2500):
            self.store.values[f"p.site.audit.{n:05d}"] = 1
        keys = run(self.backend.keys("p.site."))
        self.assertEqual(len(keys), 2500)
        self.assertEqual(self.store.calls, 3)

    def test_a_share_link_failure_does_not_break_saving(self):
        async def broken(key):
            raise RuntimeError("no links today")
        self.store.get_public_url = broken
        self.assertIsNone(run(self.backend.public_url("p.acme.report")))

    def test_a_whole_project_saves_and_loads_through_the_live_backend(self):
        # The first panel also acquires its immutable slot through the account's queue.
        queue = SimpleNamespace(add_request=mock.AsyncMock(return_value=SimpleNamespace(was_already_present=False)))
        client = mock.Mock()
        client.request_queues.return_value.get_or_create = mock.AsyncMock(return_value=SimpleNamespace(id="queue"))
        client.request_queue.return_value = queue
        self.backend.client = client
        stg.set_backend(self.backend)
        try:
            panel = [{"prompt_id": "p1", "prompt": "question one", "type": "awareness"}]
            rows = [{"snapshot": "baseline", "prompt_id": "p1", "platform": "chatgpt", "repeat": 1, "recommended": True}]
            run(hist.save_results("acme-site", rows, panel, brand={"name": "Acme"}, settings={"country": "gb"}))
            run(hist.save_audit("acme-site", {"site": "https://acme.com", "health_score": 80, "problems": [], "passed": []}))
            data = run(hist.load_project("acme-site"))
            self.assertEqual(len(data["runs"]), 1)
            self.assertEqual(len(data["audits"]), 1)
            self.assertEqual(run(hist.history(None))["projects"][0]["project"], "acme-site")
        finally:
            stg.set_backend(None)


class RoundLimitTests(unittest.TestCase):
    def setUp(self):
        stg.set_backend(stg.MemoryBackend())

    def tearDown(self):
        stg.set_backend(None)

    def test_there_is_room_for_years_of_weekly_rounds(self):
        self.assertGreaterEqual(stg.MAX_SNAPSHOTS, 156)

    def test_a_full_project_says_how_to_carry_on_and_saves_nothing(self):
        panel = [{"prompt_id": "p1", "prompt": "question one", "type": "awareness"}]

        def row(label):
            return [{"snapshot": label, "prompt_id": "p1", "platform": "chatgpt", "repeat": 1, "recommended": False}]
        with mock.patch.object(stg, "MAX_SNAPSHOTS", 2):
            run(hist.save_results("acme-site", row("r1"), panel))
            run(hist.save_results("acme-site", row("r2")))
            with self.assertRaises(ValueError) as caught:
                run(hist.save_results("acme-site", row("r3")))
        self.assertIn("Nothing was saved", str(caught.exception))
        self.assertIn("new project", str(caught.exception))
        self.assertEqual(sorted(run(hist.load_project("acme-site"))["meta"]["snapshots"]), ["r1", "r2"])


@unittest.skipIf(entry is None, "connector dependencies are not installed")
class OneShotRunTests(unittest.TestCase):
    """main.run_once: what a normal (non-Standby) run and an Apify Schedule execute."""

    def go(self, data, run_tool, access=None):
        actor = mock.Mock()
        if access is not None:
            actor.configuration = SimpleNamespace(default_key_value_store_id="store1", default_dataset_id="dataset1")
            actor.apify_client = SimpleNamespace(
                key_value_store=lambda _: SimpleNamespace(get=mock.AsyncMock(return_value=SimpleNamespace(general_access=access[0]))),
                dataset=lambda _: SimpleNamespace(get=mock.AsyncMock(return_value=SimpleNamespace(general_access=access[1]))),
            )
        actor.get_input = mock.AsyncMock(return_value=data)
        for name in ("push_data", "fail", "set_value", "set_status_message"):
            setattr(actor, name, mock.AsyncMock())
        with mock.patch.object(entry, "Actor", actor), mock.patch.object(entry.runner, "run_tool", run_tool):
            run(entry.run_once())
        return actor

    def test_a_result_is_pushed_and_stored_as_output(self):
        actor = self.go({"tool": "get_playbook", "arguments": {"name": "start"}}, mock.AsyncMock(return_value={"x": 1}))
        actor.push_data.assert_awaited_once_with({"tool": "get_playbook", "ok": True, "result": {"x": 1}, "error": None})
        actor.set_value.assert_awaited_once_with("OUTPUT", {"x": 1})
        actor.fail.assert_not_awaited()

    def test_no_input_reads_the_playbook_list(self):
        tool = mock.AsyncMock(return_value={})
        self.go(None, tool)
        tool.assert_awaited_once_with("get_playbook", {})

    def test_public_history_and_schedule_plan_remove_private_resource_locators(self):
        from main import protect_run_summary
        overview = {"projects":[{"project":"demo-site", "rounds":1,"imported_dataset_ids":["internalDataset"],
                                  "attributed_runs":{"parentRun":"managed"},"new_receipt":{"private":"only"}}]}
        plan = {"free_site_check":{"input":{"tool":"scheduled_check","project_store_id":"internalStore",
                                           "schedule_lock_id":"internalLock","arguments":{"project":"demo-site"}}},
                "ai_checks":{"site_check_input":{"project_store_id":"internalStore","schedule_ledger_id":"internalLedger"}}}
        ai = {"ai_import":{"status":"imported","saved_answers":3,"dataset_ids":["internalDataset"],
                           "snapshot":"scheduled-internalRun","runs":[{"run_id":"internalRun"}],
                           "alert":{"lost_questions":1,"examples":["private question"]}}}
        with mock.patch.dict(os.environ, {"APIFY_IS_AT_HOME":"1"}):
            for tool, source in (("get_history", overview), ("schedule_checks", plan), ("scheduled_check", {**ai,"health_score":7})):
                with self.subTest(tool=tool):
                    actor = self.go({"tool":tool}, mock.AsyncMock(return_value=source))
                    public = json.dumps(actor.set_value.await_args.args[1])
                    for needle in ("internal", "parentRun", "new_receipt", "private question"):
                        self.assertNotIn(needle, public)
                    self.assertEqual(actor.push_data.await_args.args[0]["result"], actor.set_value.await_args.args[1])
        self.assertEqual(overview["projects"][0]["attributed_runs"], {"parentRun":"managed"})

    def test_arguments_that_are_not_an_object_become_empty(self):
        tool = mock.AsyncMock(return_value={})
        self.go({"tool": "get_history", "arguments": "acme"}, tool)
        tool.assert_awaited_once_with("get_history", {})

    def test_public_run_output_cannot_return_private_answer_text(self):
        runner = mock.AsyncMock(return_value={"answer_review": {"text": "Private fixture wording"}})
        data = {"tool": "get_history", "arguments": {"project": "acme", "answer_review": {"snapshot": "latest"}}}
        with mock.patch.dict(os.environ, {"APIFY_IS_AT_HOME": "1"}):
            actor = self.go(data, runner, access=("RESTRICTED", "ANYONE_WITH_ID_CAN_READ"))
        runner.assert_not_awaited()
        actor.set_value.assert_not_awaited()
        actor.fail.assert_awaited_once()
        self.assertIn("dashboard", actor.push_data.await_args.args[0]["error"])

    def test_public_import_output_cannot_copy_answer_excerpts_from_datasets(self):
        runner = mock.AsyncMock(return_value={"needs_review": [{"context": "Private fixture wording"}]})
        data = {"tool": "import_ai_results", "arguments": {"project": "acme", "dataset_ids": ["dataset123"]}}
        with mock.patch.dict(os.environ, {"APIFY_IS_AT_HOME": "1"}):
            actor = self.go(data, runner, access=("RESTRICTED", "ANYONE_WITH_ID_CAN_READ"))
        runner.assert_not_awaited()
        actor.set_value.assert_not_awaited()
        actor.fail.assert_awaited_once()

    def test_public_scheduled_outputs_keep_the_alert_counts_and_omit_question_text(self):
        alert = {"lost_questions": 2, "examples": ["Private fixture question"]}
        for tool, result, expected in [
            ("scheduled_check", {"health_score": 72, "ai_import": {"status": "imported", "alert": alert}},
             {"health_score": 72, "ai_import": {"status": "imported", "alert": {"lost_questions": 2}}}),
            ("get_history", {"scheduled_alert": alert}, {"scheduled_alert": {"lost_questions": 2}}),
            ("get_history", {"latest_audit": {"problems": [{"detail": "Private page notes"}]}, "audits": []}, {"audits": []}),
        ]:
            with self.subTest(tool=tool), mock.patch.dict(os.environ, {"APIFY_IS_AT_HOME": "1"}):
                actor = self.go({"tool": tool}, mock.AsyncMock(return_value=result),
                                access=("ANYONE_WITH_ID_CAN_READ", "RESTRICTED"))
            actor.set_value.assert_awaited_once_with("OUTPUT", expected)
            actor.fail.assert_not_awaited()

    def test_restricted_metadata_alone_cannot_allow_one_shot_private_answers(self):
        result = {"answer_review": {"text": "Private fixture wording"}}
        data = {"tool": "get_history", "arguments": {"project": "acme", "answer_review": {"snapshot": "latest"}}}
        with mock.patch.dict(os.environ, {"APIFY_IS_AT_HOME": "1"}):
            actor = self.go(data, mock.AsyncMock(return_value=result), access=("RESTRICTED", "RESTRICTED"))
        actor.set_value.assert_not_awaited()
        actor.fail.assert_awaited_once()

    def test_scheduled_output_with_public_stores_leaves_out_report_link(self):
        data = {"tool": "scheduled_check"}
        result = {"health_score": 72, "report_url": "https://example.com/share"}
        with mock.patch.dict(os.environ, {"APIFY_IS_AT_HOME": "1"}):
            actor = self.go(data, mock.AsyncMock(return_value=result), access=("ANYONE_WITH_ID_CAN_READ", "RESTRICTED"))
        actor.set_value.assert_awaited_once_with("OUTPUT", {"health_score": 72, "report_url": None})
        actor.fail.assert_not_awaited()

    def test_a_scheduled_run_with_no_site_or_ai_data_fails(self):
        actor = self.go({"tool": "scheduled_check"}, mock.AsyncMock(return_value={"health_score": None}))
        actor.fail.assert_awaited_once()
        self.assertFalse(actor.push_data.await_args.args[0]["ok"])

    def test_a_scheduled_run_with_only_ai_data_keeps_its_result(self):
        actor = self.go({"tool": "scheduled_check"}, mock.AsyncMock(return_value={
            "health_score": None, "ai_import": {"status": "imported", "saved_answers": 3},
        }))
        actor.fail.assert_not_awaited()
        self.assertTrue(actor.push_data.await_args.args[0]["ok"])

    def test_bad_input_fails_the_run_with_the_plain_message(self):
        actor = self.go({"tool": "nope"}, mock.AsyncMock(side_effect=ValueError("Unknown tool 'nope'.")))
        actor.fail.assert_awaited_once()
        self.assertEqual(actor.push_data.await_args.args[0]["error"], "Unknown tool 'nope'.")
        actor.set_value.assert_not_awaited()

    def test_an_unexpected_fault_fails_honestly_without_leaking_details(self):
        actor = self.go({"tool": "get_history"}, mock.AsyncMock(side_effect=RuntimeError("secret path /x/y")))
        actor.fail.assert_awaited_once()
        pushed = actor.push_data.await_args.args[0]
        self.assertFalse(pushed["ok"])
        self.assertNotIn("secret", pushed["error"])
        self.assertIn("RuntimeError", actor.log.error.call_args.args[0])
        self.assertNotIn("secret", actor.log.error.call_args.args[0])


@unittest.skipIf(server is None, "connector dependencies are not installed")
class FailureLogTests(unittest.TestCase):
    """One safe line per call: the kind of failure, never the content."""

    def lines(self, fn, **kwargs):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        server.log.addHandler(handler)
        server.log.setLevel(logging.INFO)
        try:
            try:
                fn(**kwargs)
            except Exception:
                pass
        finally:
            server.log.removeHandler(handler)
        return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]

    def test_bad_input_is_logged_as_bad_input(self):
        def tool(text=""):
            raise ValueError("the user's private text was wrong")
        line = self.lines(server.friendly(tool), text="private words")[0]
        self.assertEqual((line["ok"], line["error_class"]), (False, "bad_input"))
        self.assertNotIn("private", json.dumps(line))

    def test_an_unexpected_fault_is_logged_by_class_only(self):
        def tool(text=""):
            raise KeyError("secret-key-name")
        line = self.lines(server.friendly(tool), text="x")[0]
        self.assertEqual(line["error_class"], "KeyError")
        self.assertNotIn("secret", json.dumps(line))

    def test_a_good_call_has_no_error_class(self):
        line = self.lines(server.friendly(lambda text="": {"ok": True}), text="x")[0]
        self.assertTrue(line["ok"])
        self.assertNotIn("error_class", line)


if __name__ == "__main__":
    unittest.main()
