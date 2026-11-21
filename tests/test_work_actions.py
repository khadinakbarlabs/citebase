import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))

import storage
import work_actions as work


class WorkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = storage.MemoryBackend()
        storage.set_backend(self.backend)
        self.addCleanup(storage.set_backend, None)
        for slug in ("alpha", "bravo"):
            await self.backend.set(storage.key(slug, "meta"), {
                "brand": {"domain": "example.org"}, "settings": {"language": "en"},
                "todo": [{"step": "Fix title", "status": "done", "updated": "2026-11-10"}]})

    async def run_op(self, op, **data):
        return await work.execute("alpha", op, data)

    async def test_brief_is_private_revisioned_and_isolated(self):
        self.assertEqual((await self.run_op("brief_get"))["brief"]["language"], "en")
        await self.run_op("brief_save", goal="Appointments", expected_revision=0, inferred_facts=["Local"])
        with self.assertRaises(ValueError):
            await self.run_op("brief_save", expected_revision=0, goal="Wrong")
        brief = (await self.run_op("brief_save", expected_revision=1, confirmed_facts=["Local"]))["brief"]
        self.assertEqual((brief["goal"], brief["inferred_facts"]), ("Appointments", []))
        self.assertNotIn("Appointments", str(self.backend.data))
        self.assertNotIn("Appointments", str(await work.execute("bravo", "brief_get", {})))
        self.backend.project_store_id = "differentStore"
        self.assertNotIn("Appointments", str(await self.run_op("brief_get")))

    async def test_migrated_todo_keeps_identity(self):
        item, = (await self.run_op("actions_list"))["actions"]
        self.assertEqual(item["status"], "done")
        edited = (await self.run_op("action_save", id=item["id"], expected_revision=0,
                                    title="Improve category title", owner="Sam"))["action"]
        self.assertEqual(edited["id"], item["id"])
        self.assertEqual(edited["history"][0]["title"], "Fix title")
        self.assertEqual((await self.run_op("actions_list"))["actions"], [edited])

    async def test_single_finding_and_conflict(self):
        data = dict(title="Repair", finding_id="audit-title", expected_revision=0)
        a, b = await asyncio.gather(self.run_op("action_save", **data), self.run_op("action_save", **data))
        self.assertEqual(a["action"]["id"], b["action"]["id"])
        item = a["action"]
        await self.run_op("action_save", id=item["id"], expected_revision=1, owner="Sam")
        with self.assertRaises(ValueError):
            await self.run_op("action_save", id=item["id"], expected_revision=1, owner="Bob")

    async def test_exact_page_verification_is_invalidated_by_edits(self):
        url = "https://example.org/pricing"
        item = (await self.run_op("action_save", title="Pricing", finding_id="pricing", page_url=url,
                                  after_title="Annual pricing", status="approved", expected_revision=0))["action"]
        response = dict(status=200, body=b"<html><title>Annual pricing</title></html>",
                        headers={"content-type": "text/html"})
        with patch.object(work.sa, "fetch", return_value=response) as fetch:
            checked = (await self.run_op("action_recheck", id=item["id"], expected_revision=1))["action"]
            fetch.assert_called_once_with(url)
        self.assertEqual(checked["recheck"]["status"], "verified")
        self.assertIn(url, checked["technical_ticket"])
        edited = (await self.run_op("action_save", id=item["id"], expected_revision=2,
                                    after_title="New"))["action"]
        self.assertFalse(edited["recheck"])
        self.assertNotEqual(edited["status"], "approved")
        for result, status in ((response, "mismatch"), (dict(status=302), "unavailable")):
            with patch.object(work.sa, "fetch", return_value=result):
                edited = (await self.run_op("action_recheck", id=item["id"],
                                            expected_revision=edited["revision"]))["action"]
            self.assertEqual(edited["recheck"]["status"], status)

    async def test_explicit_project_scope_and_valid_values(self):
        for fields in ({"page_url": "https://unrelated.example/pricing"}, {"status": "broken"},
                       {"due_date": "yesterday"}, {"evidence_url": "javascript:alert(1)"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                await self.run_op("action_save", title="Fix", **fields)
        with self.assertRaises(ValueError):
            await work.execute("unknown", "actions_list", {})

    async def test_canonical_check_and_ticket(self):
        args = {"page_url": "https://example.org/shop", "technical_check": "canonical",
                "expected_value": "https://example.org/catalog", "before_value": "https://example.org/",
                "acceptance_condition": "Raw canonical points to catalog", "title": "Repair canonical"}
        item = (await self.run_op("action_save", **args))["action"]
        self.assertIn(args["acceptance_condition"], item["technical_ticket"])
        response = {"status": 200, "body": b'<html><link rel="canonical" href="/catalog"></html>',
                    "headers": {"content-type": "text/html"}}
        with patch.object(work.sa, "fetch", return_value=response):
            checked = (await self.run_op("action_recheck", id=item["id"], expected_revision=1))["action"]["recheck"]
        self.assertEqual((checked["status"], checked["observed_value"]), ("verified", args["expected_value"]))
        self.assertIs(checked["changed_from_before"], True)

    async def test_keep_current_copy_is_verifiable(self):
        url = "https://example.org/overview"
        item = (await self.run_op("action_save", title="Keep current wording", page_url=url,
                                  before_title="Overview", after_title="Overview"))["action"]
        with patch.object(work.sa, "fetch", return_value={"status": 200, "body": b"<title>Overview</title>",
                                                        "headers": {"content-type": "text/html"}}):
            check = (await self.run_op("action_recheck", id=item["id"], expected_revision=1))["action"]["recheck"]
        self.assertEqual(check["status"], "verified")
        self.assertFalse(check["changed_from_before"])

    async def test_migrated_todo_remains_if_old_list_rolls_off(self):
        item, = (await self.run_op("actions_list"))["actions"]
        meta = await self.backend.get(storage.key("alpha", "meta"))
        await self.backend.set(storage.key("alpha", "meta"), {**meta, "todo": []})
        self.assertEqual((await self.run_op("actions_list"))["actions"], [item])

    async def test_old_and_new_clients_agree_on_legacy_status(self):
        item, = (await self.run_op("actions_list"))["actions"]
        await self.run_op("action_save", id=item["id"], expected_revision=0, status="open", owner="Sam")
        meta = await self.backend.get(storage.key("alpha", "meta"))
        self.assertEqual(meta["todo"][0]["step"], "Fix title")
        self.assertEqual((await self.run_op("actions_list"))["legacy_todo"][0]["status"], "open")
        meta["todo"][0]["status"] = "skipped"
        await self.backend.set(storage.key("alpha", "meta"), meta)
        fresh, = (await self.run_op("actions_list"))["actions"]
        self.assertEqual((fresh["status"], fresh["owner"], fresh["revision"]), ("skipped", "Sam", 2))

    async def test_independent_writers_and_lost_ack(self):
        private = await self.backend.private_store()
        one = await work.RevisionStore.open(self.backend, private, "one")
        two = await work.RevisionStore.open(self.backend, private, "two")
        results = await asyncio.gather(one.set("doc", {"revision": 1, "goal": "A"}),
                                       two.set("doc", {"revision": 1, "goal": "B"}), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)
        self.assertEqual((await one.get("doc"))["goal"], (await two.get("doc"))["goal"])
        with patch.object(work.RevisionStore, "commit", autospec=True, side_effect=self.lost_ack):
            with self.assertRaises(TimeoutError):
                await self.run_op("action_save", title="Check catalog", expected_revision=0)
        retried = (await self.run_op("action_save", title="Check catalog", expected_revision=0))["action"]
        self.assertEqual(retried["revision"], 1)
        items = (await self.run_op("actions_list"))["actions"]
        self.assertEqual(sum(a["title"] == "Check catalog" for a in items), 1)

    async def lost_ack(self, journal, slot, token):
        journal.store.data.setdefault("vote." + slot, token)
        raise TimeoutError("lost acknowledgement")

    async def test_queue_receipt_uses_only_opaque_ids_and_concurrent_objects_survive(self):
        from types import SimpleNamespace
        from apify.storage_clients._apify._utils import unique_key_to_request_id

        class AtomicQueue:
            def __init__(self):
                self.records = {}

            async def add_request(self, value):
                await asyncio.sleep(0)
                ref = unique_key_to_request_id(value["uniqueKey"])
                present = ref in self.records
                self.records.setdefault(ref, SimpleNamespace(url=value["url"]))
                return SimpleNamespace(was_already_present=present)

            async def get_request(self, ref):
                return self.records.get(ref)

        queue = AtomicQueue()
        private = await self.backend.private_store()
        a = work.RevisionStore(private, queue, "save alpha")
        b = work.RevisionStore(private, queue, "save bravo")
        commits = await asyncio.gather(a.set("alpha", {"revision": 1, "value": "private A"}),
                                       b.set("bravo", {"revision": 1, "value": "private B"}))
        self.assertEqual(len(commits), 2)
        self.assertNotIn("private", str(queue.records))
        other = work.RevisionStore(private, queue, "conflicting edit")
        conflict = await asyncio.gather(a.set("alpha", {"revision": 2, "value": "A"}),
                                        other.set("alpha", {"revision": 2, "value": "B"}), return_exceptions=True)
        self.assertEqual(sum(isinstance(x, ValueError) for x in conflict), 1)
        self.assertEqual(len(await b.records("")), 2)

    async def test_page_inspection_uses_observed_metadata_and_exact_project_url(self):
        page_url = "https://example.org/pricing"
        response = {"status": 200, "body": b'<title>Plans</title><meta name="description" content="Options"><h1>Prices</h1><a href="/faq">FAQ</a>',
                    "headers": {"content-type": "text/html"}}
        with patch.object(work.sa, "fetch", return_value=response) as fetch:
            item = (await self.run_op("page_inspect", page_url=page_url))["page"]
            fetch.assert_called_once_with(page_url)
            self.assertEqual((item["status"], item["title"], item["description"], item["h1"]),
                             ("observed", "Plans", "Options", ["Prices"]))
            self.assertEqual((item["suggested_title"], item["title_guidance"]), ("Plans", "keep_current"))
            self.assertIn("https://example.org/faq", item["internal_links"])
        with patch.object(work.sa, "fetch") as fetch:
            with self.assertRaises(ValueError):
                await self.run_op("page_inspect", page_url="https://elsewhere.org/pricing")
            fetch.assert_not_called()

    async def test_inspection_empty_title_only_suggests_a_real_heading(self):
        url = "https://example.org/a"
        for body, suggestion, guidance in ((b"<h1>Membership details</h1>", "Membership details", "review_heading"),
                                          (b"<p>Information</p>", "", "draft_needed")):
            response = {"status": 200, "headers": {"content-type": "text/html"}, "body": body}
            with patch.object(work.sa, "fetch", return_value=response):
                page = (await self.run_op("page_inspect", page_url=url))["page"]
            self.assertEqual((page["title"], page["suggested_title"], page["title_guidance"]),
                             ("", suggestion, guidance))
        for response in ({"status": 301}, {"status": 0}, {"status": 200, "truncated": True},
                         {"status": 200, "body": b"PDF", "headers": {"content-type": "application/pdf"}}):
            with patch.object(work.sa, "fetch", return_value=response):
                page = (await self.run_op("page_inspect", page_url=url))["page"]
            self.assertEqual((page["status"], page["suggested_title"], page["title"]), ("unavailable", "", None))
