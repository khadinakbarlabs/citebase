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

    def go(self, data, run_tool):
        actor = mock.Mock()
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

    def test_arguments_that_are_not_an_object_become_empty(self):
        tool = mock.AsyncMock(return_value={})
        self.go({"tool": "get_history", "arguments": "acme"}, tool)
        tool.assert_awaited_once_with("get_history", {})

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
